/**
 * GpxImporter — Import GPX/KMZ sprint urbain
 *
 * Deux actions indépendantes :
 *  1. Charger sur la carte  → parse coordonnées → crée circuit dans l'app
 *  2. Contribuer au ML      → envoie au backend → Overpass terrain → DB anonymisée
 */

import { useRef, useState } from 'react'
import { contributeGpx, parseKmzCoords } from '../services/api'

// ─── Parsing GPX client-side (DOMParser, aucune lib) ────────────────────────

function parseGpxWaypoints(text) {
  const doc = new DOMParser().parseFromString(text, 'application/xml')
  if (doc.querySelector('parsererror')) return []

  // Waypoints <wpt> = postes de contrôle dans la plupart des apps CO
  const wpts = [...doc.querySelectorAll('wpt')]
  if (wpts.length >= 2) {
    return wpts.map((w, i) => ({
      lat: parseFloat(w.getAttribute('lat')),
      lng: parseFloat(w.getAttribute('lon')),
      name: w.querySelector('name')?.textContent?.trim() || String(i),
    })).filter(p => isFinite(p.lat) && isFinite(p.lng))
  }

  // Fallback : trackpoints <trkpt> → échantillonnage tous les ~50m
  const trkpts = [...doc.querySelectorAll('trkpt')]
  if (trkpts.length < 3) return []
  const all = trkpts.map(w => ({
    lat: parseFloat(w.getAttribute('lat')),
    lng: parseFloat(w.getAttribute('lon')),
  })).filter(p => isFinite(p.lat) && isFinite(p.lng))
  return sampleTrack(all, 50)
}

function sampleTrack(pts, minDistM = 50) {
  if (pts.length <= 15) return pts.map((p, i) => ({ ...p, name: String(i) }))
  const result = [{ ...pts[0], name: '0' }]
  for (let i = 1; i < pts.length - 1; i++) {
    const d = haversinePx(result[result.length - 1], pts[i])
    if (d >= minDistM) result.push({ ...pts[i], name: String(result.length) })
  }
  result.push({ ...pts[pts.length - 1], name: String(result.length) })
  return result
}

function haversinePx(a, b) {
  const R = 6_371_000
  const dLat = (b.lat - a.lat) * Math.PI / 180
  const dLng = (b.lng - a.lng) * Math.PI / 180
  const s = Math.sin(dLat / 2) ** 2
    + Math.cos(a.lat * Math.PI / 180) * Math.cos(b.lat * Math.PI / 180) * Math.sin(dLng / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(s), Math.sqrt(1 - s))
}

function computeDistance(pts) {
  let d = 0
  for (let i = 1; i < pts.length; i++) d += haversinePx(pts[i - 1], pts[i])
  return Math.round(d)
}

// ─── Composant ───────────────────────────────────────────────────────────────

const FFCO_CATEGORIES = [
  'Open', 'H21E', 'H21', 'H20', 'H18', 'H16',
  'D21E', 'D21', 'D20', 'D18', 'D16',
  'H35', 'H40', 'H45', 'H50', 'H55', 'H60',
  'D35', 'D40', 'D45', 'D50', 'D55', 'D60',
]

export default function GpxImporter({ onLoadControls }) {
  const [file, setFile] = useState(null)
  const [parsed, setParsed] = useState(null)      // { points, distanceM, name }
  const [parseError, setParsError] = useState(null)
  const [isParsing, setIsParsing] = useState(false)

  const [ffcoCategory, setFfcoCategory] = useState('Open')
  const [consentEducational, setConsentEducational] = useState(false)
  const [contributing, setContributing] = useState(false)
  const [contributeStatus, setContributeStatus] = useState(null) // null | 'loading' | 'ok' | 'error' | 'doublon'
  const [contributeResult, setContributeResult] = useState(null)

  const dropRef = useRef(null)
  const inputRef = useRef(null)

  // ── Lecture du fichier ──────────────────────────────────────────────────────

  const processFile = async (f) => {
    setFile(f)
    setParsed(null)
    setParsError(null)
    setContributeStatus(null)
    setContributeResult(null)
    setIsParsing(true)

    const ext = f.name.split('.').pop().toLowerCase()

    try {
      let points = []
      if (ext === 'gpx') {
        const text = await f.text()
        points = parseGpxWaypoints(text)
      } else if (ext === 'kmz') {
        // KMZ : parser backend léger (pas de lib ZIP côté client)
        const res = await parseKmzCoords(f)
        points = (res.data.points || []).map(p => ({ lat: p.lat, lng: p.lon, name: p.name || '' }))
      }

      if (points.length < 2) {
        setParsError('Aucun poste détecté. Vérifiez que le fichier contient des waypoints.')
        setIsParsing(false)
        return
      }

      setParsed({
        points,
        distanceM: computeDistance(points),
        name: f.name.replace(/\.(gpx|kmz)$/i, ''),
      })
    } catch (e) {
      setParsError(`Erreur de lecture : ${e.message}`)
    } finally {
      setIsParsing(false)
    }
  }

  const handleFileChange = (e) => {
    const f = e.target.files?.[0]
    if (f) processFile(f)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    dropRef.current?.classList.remove('border-violet-500', 'bg-violet-900/20')
    const f = e.dataTransfer.files?.[0]
    if (f) processFile(f)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    dropRef.current?.classList.add('border-violet-500', 'bg-violet-900/20')
  }

  const handleDragLeave = () => {
    dropRef.current?.classList.remove('border-violet-500', 'bg-violet-900/20')
  }

  // ── Charger sur la carte ────────────────────────────────────────────────────

  const handleLoadOnMap = () => {
    if (!parsed?.points?.length) return
    const controls = parsed.points.map((p, i) => ({
      id: `gpx_${Date.now()}_${i}`,
      lat: p.lat,
      lng: p.lng,
      order: i + 1,
      type: i === 0 ? 'start' : i === parsed.points.length - 1 ? 'finish' : 'control',
      description: p.name || '',
    }))
    onLoadControls?.({
      controls,
      name: parsed.name,
      type: 'sprint',
      sex: 'H',
      category: '21',
    })
  }

  // ── Contribuer au ML ────────────────────────────────────────────────────────

  const handleContribute = async () => {
    if (!file || !parsed) return
    setContributeStatus('loading')
    setContributeResult(null)
    try {
      const res = await contributeGpx(file, { ffcoCategory, consentEducational })
      setContributeStatus('ok')
      setContributeResult(res.data)
    } catch (err) {
      if (err.response?.status === 409) {
        setContributeStatus('doublon')
      } else {
        setContributeStatus('error')
        setContributeResult({ detail: err.response?.data?.detail || err.message })
      }
    }
  }

  // ── Rendu ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-3">

      {/* Zone de dépôt */}
      <div
        ref={dropRef}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed border-gray-600 rounded-lg p-4 text-center cursor-pointer transition-colors hover:border-violet-400 hover:bg-violet-900/10"
      >
        <input
          ref={inputRef}
          type="file"
          accept=".gpx,.kmz"
          className="hidden"
          onChange={handleFileChange}
        />
        {isParsing ? (
          <p className="text-xs text-gray-400 animate-pulse">Analyse en cours…</p>
        ) : file ? (
          <p className="text-xs text-violet-300 font-medium truncate">{file.name}</p>
        ) : (
          <>
            <p className="text-xs text-gray-400">Glisser un fichier ou cliquer</p>
            <p className="text-xs text-gray-500 mt-1">.gpx  ·  .kmz</p>
          </>
        )}
      </div>

      {/* Erreur parsing */}
      {parseError && (
        <p className="text-xs text-red-400 px-1">{parseError}</p>
      )}

      {/* Résultat parsing */}
      {parsed && (
        <>
          {/* Résumé */}
          <div className="rounded-lg bg-gray-800/60 border border-gray-700 px-3 py-2 text-xs flex justify-between items-center">
            <span className="text-gray-300">
              <span className="text-white font-semibold">{parsed.points.length}</span> postes
            </span>
            <span className="text-gray-300">
              <span className="text-white font-semibold">{(parsed.distanceM / 1000).toFixed(2)}</span> km
            </span>
            <span className="text-gray-500 text-xs">sprint urbain</span>
          </div>

          {/* Aperçu des postes */}
          <div className="max-h-24 overflow-y-auto flex flex-col gap-0.5">
            {parsed.points.map((p, i) => (
              <div key={i} className="flex items-center gap-2 px-1 py-0.5 rounded text-xs">
                <span className={`w-4 h-4 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                  i === 0 ? 'bg-green-700 text-white' :
                  i === parsed.points.length - 1 ? 'bg-red-700 text-white' :
                  'bg-violet-800 text-violet-200'
                }`}>
                  {i === 0 ? '▶' : i === parsed.points.length - 1 ? '⬤' : i}
                </span>
                <span className="text-gray-400 truncate">{p.name || `Poste ${i}`}</span>
              </div>
            ))}
          </div>

          {/* Action : charger sur la carte */}
          <button
            onClick={handleLoadOnMap}
            className="w-full py-2 rounded-lg bg-violet-700 hover:bg-violet-600 text-white text-sm font-medium transition-colors"
          >
            Charger sur la carte
          </button>

          {/* Séparateur */}
          <div className="flex items-center gap-2">
            <div className="flex-1 h-px bg-gray-700" />
            <span className="text-xs text-gray-500">Contribuer au ML</span>
            <div className="flex-1 h-px bg-gray-700" />
          </div>

          {/* Formulaire contribution ML */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-400 w-20 flex-shrink-0">Catégorie</label>
              <select
                value={ffcoCategory}
                onChange={e => setFfcoCategory(e.target.value)}
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white"
              >
                {FFCO_CATEGORIES.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={consentEducational}
                onChange={e => setConsentEducational(e.target.checked)}
                className="mt-0.5 accent-violet-500"
              />
              <span className="text-xs text-gray-400">
                Partage éducatif (CC BY-NC) — permet l'export CSV pour la recherche
              </span>
            </label>

            {contributeStatus === 'ok' ? (
              <div className="rounded-lg bg-green-900/40 border border-green-700/50 px-3 py-2 text-xs text-green-300">
                ✓ Contribué — {contributeResult?.n_controls} postes, {contributeResult?.length_m}m, TD{contributeResult?.td_grade}
              </div>
            ) : contributeStatus === 'doublon' ? (
              <div className="rounded-lg bg-yellow-900/40 border border-yellow-700/50 px-3 py-2 text-xs text-yellow-300">
                Ce fichier a déjà été contribué.
              </div>
            ) : contributeStatus === 'error' ? (
              <div className="rounded-lg bg-red-900/40 border border-red-700/50 px-3 py-2 text-xs text-red-300">
                Erreur : {contributeResult?.detail || 'inconnue'}
              </div>
            ) : (
              <button
                onClick={handleContribute}
                disabled={contributeStatus === 'loading'}
                className="w-full py-2 rounded-lg bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm transition-colors"
              >
                {contributeStatus === 'loading'
                  ? <span className="animate-pulse">Enrichissement OSM en cours…</span>
                  : 'Envoyer au ML (anonyme)'}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
