import { useState } from 'react'
import { MapViewer } from './components/MapViewer'
import OcadUploader from './components/OcadUploader'
import ControlsList from './components/ControlsList'
import AiChatPanel from './components/AiChatPanel'
import TerrainPanel from './components/TerrainPanel'
import CircuitCreationModal from './components/CircuitCreationModal'
import CircuitSelector from './components/CircuitSelector'
import AISuggestionPanel from './components/AISuggestionPanel'
import { generateCircuit, uploadOcdForRender, TILE_SERVICE_URL } from './services/api'
import { buildMapContext } from './services/mapContext'

// IOF/FFCO reference params — auto-computed per circuit type/sex/category
const CIRCUIT_BASE_PARAMS = {
  sprint: { target_length_m: 3500, winning_time_minutes: 12, technical_level: 'TD4', target_controls: 15 },
  md:     { target_length_m: 8000, winning_time_minutes: 30, technical_level: 'TD4', target_controls: 18 },
  ld:     { target_length_m: 14000, winning_time_minutes: 60, technical_level: 'TD4', target_controls: 25 },
}
const COLOR_PARAMS = {
  Jaune:  { target_length_m: 1500, technical_level: 'TD1', target_controls: 8 },
  Orange: { target_length_m: 2000, technical_level: 'TD2', target_controls: 10 },
  Vert:   { target_length_m: 2500, technical_level: 'TD2', target_controls: 10 },
  Bleu:   { target_length_m: 3500, technical_level: 'TD3', target_controls: 12 },
  Violet: { target_length_m: 5000, technical_level: 'TD4', target_controls: 15 },
  Noir:   { target_length_m: 7000, technical_level: 'TD5', target_controls: 20 },
}
const AGE_FACTOR = {
  '10': 0.38, '12': 0.48, '14': 0.62, '16': 0.78, '18': 0.88,
  '20': 0.93, '21': 0.97, '21E': 1.0,
  '35': 0.88, '40': 0.82, '45': 0.76, '50': 0.70, '55': 0.65,
  '60': 0.60, '65': 0.54, '70': 0.48, '75': 0.44, '80': 0.40,
}

function getCircuitParams(circuit) {
  if (circuit.type === 'couleur') {
    return { ...(COLOR_PARAMS[circuit.color] ?? COLOR_PARAMS.Vert), category: 'Couleur' }
  }
  const base = CIRCUIT_BASE_PARAMS[circuit.type] ?? CIRCUIT_BASE_PARAMS.md
  const ageFactor = AGE_FACTOR[circuit.category] ?? 1.0
  const sexFactor = circuit.sex === 'D' ? 0.78 : 1.0
  const factor = ageFactor * sexFactor
  return {
    ...base,
    target_length_m: Math.round(base.target_length_m * factor / 100) * 100,
    winning_time_minutes: Math.round(base.winning_time_minutes * factor),
    target_controls: Math.max(5, Math.round(base.target_controls * factor)),
    category: `${circuit.sex}${circuit.category}`,
  }
}

function haversineDistance(p, q) {
  const R = 6371000
  const dLat = (q.lat - p.lat) * Math.PI / 180
  const dLng = (q.lng - p.lng) * Math.PI / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(p.lat * Math.PI / 180) * Math.cos(q.lat * Math.PI / 180) *
    Math.sin(dLng / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function computeCourseDistance(controls) {
  const ordered = [...controls]
    .filter(c => ['start', 'control', 'finish'].includes(c.type))
    .sort((a, b) => a.order - b.order)
  if (ordered.length < 2) return 0
  let total = 0
  for (let i = 1; i < ordered.length; i++) total += haversineDistance(ordered[i - 1], ordered[i])
  return Math.round(total)
}

function extractBoundingBox(geojson) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const walk = (coords) => {
    if (typeof coords[0] === 'number') {
      minX = Math.min(minX, coords[0]); maxX = Math.max(maxX, coords[0])
      minY = Math.min(minY, coords[1]); maxY = Math.max(maxY, coords[1])
    } else coords.forEach(walk)
  }
  geojson.features.forEach(f => f.geometry?.coordinates && walk(f.geometry.coordinates))
  return { min_x: minX, min_y: minY, max_x: maxX, max_y: maxY }
}

// ISOM codes with notable orienteering control attractiveness
// Source: backend/src/data/ocad_semantics.json (high/medium attractiveness)
const ATTRACTIVE_ISOM = new Set([
  101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,
  201,202,203,204,205,206,209,210,211,212,215,
  301,302,303,304,305,306,308,
  401,402,403,404,405,406,
  501,502,516,521,522,529,
])

function computeGeoCentroid(geometry) {
  if (!geometry) return null
  const coords =
    geometry.type === 'Point'      ? [geometry.coordinates] :
    geometry.type === 'LineString' ? geometry.coordinates :
    geometry.type === 'Polygon'    ? geometry.coordinates[0] : null
  if (!coords?.length) return null
  return [
    coords.reduce((s, c) => s + c[0], 0) / coords.length,
    coords.reduce((s, c) => s + c[1], 0) / coords.length,
  ]
}

function extractCandidatePoints(geojson, max = 400) {
  const pts = []
  for (const f of geojson.features) {
    const sym = f.properties?.sym
    if (!sym) continue
    const isom = Math.floor(sym / 1000)
    if (!ATTRACTIVE_ISOM.has(isom)) continue
    const c = computeGeoCentroid(f.geometry)
    if (c) pts.push({ x: c[0], y: c[1], isom })
  }
  // Shuffle then limit
  for (let i = pts.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pts[i], pts[j]] = [pts[j], pts[i]]
  }
  return pts.slice(0, max)
}

const tools = [
  { id: 'view', icon: '🖐️', label: 'Déplacer' },
  { id: 'start', icon: '🔺', label: 'Départ' },
  { id: 'control', icon: '⭕', label: 'Poste' },
  { id: 'finish', icon: '🎯', label: 'Arrivée' },
  { id: 'forbidden', icon: '🛑', label: 'Zone Interdite' },
]

function App() {
  const [ocadData, setOcadData] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeTool, setActiveTool] = useState('view')
  const [imageData, setImageData] = useState(null)
  const [renderLoading, setRenderLoading] = useState(false)
  const [showChat, setShowChat] = useState(false)
  const [terrainData, setTerrainData] = useState(null)
  const [showRunnability, setShowRunnability] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationError, setGenerationError] = useState(null)

  // Multi-circuit state
  const [circuits, setCircuits] = useState([])
  const [activeCircuitId, setActiveCircuitId] = useState(null)
  const [showCreationForm, setShowCreationForm] = useState(false)

  // Derived active circuit
  const activeCircuit = circuits.find(c => c.id === activeCircuitId) ?? null

  // Helper: update only the active circuit
  const updateActiveCircuit = (updater) => {
    setCircuits(prev => prev.map(c =>
      c.id === activeCircuitId
        ? { ...c, ...(typeof updater === 'function' ? updater(c) : updater) }
        : c
    ))
  }

  // ── Map loading ──────────────────────────────────────────────────────────────

  const handleOcadLoaded = (data) => {
    setOcadData(data)
    setError(null)
    setCircuits([])
    setActiveCircuitId(null)
    setImageData(null)

    if (data.rawFile) {
      setRenderLoading(true)
      uploadOcdForRender(data.rawFile)
        .then((res) => {
          const { imageUrl, bounds } = res.data
          if (imageUrl && bounds?.southWest && bounds?.northEast) {
            setImageData({
              url: `${TILE_SERVICE_URL}${imageUrl}`,
              bounds: [
                [bounds.southWest[0], bounds.southWest[1]],
                [bounds.northEast[0], bounds.northEast[1]],
              ],
            })
          }
        })
        .catch(err => console.warn('[Render] Service unavailable:', err.message))
        .finally(() => setRenderLoading(false))
    }
  }

  const handleError = (errMsg) => {
    setError(errMsg)
    setIsLoading(false)
  }

  // ── Circuit management ───────────────────────────────────────────────────────

  const handleCreateCircuit = (def) => {
    const circuit = {
      id: crypto.randomUUID(),
      ...def,
      controls: [],
      forbiddenZones: [],
      status: 'setup',
      aiSuggestions: [],
      suggestionIdx: 0,
    }
    setCircuits(prev => [...prev, circuit])
    setActiveCircuitId(circuit.id)
    setShowCreationForm(false)
    setActiveTool('start')
  }

  const handleDeleteCircuit = (id) => {
    setCircuits(prev => {
      const remaining = prev.filter(c => c.id !== id)
      if (id === activeCircuitId) {
        setActiveCircuitId(remaining[remaining.length - 1]?.id ?? null)
      }
      return remaining
    })
  }

  // ── Controls placement ───────────────────────────────────────────────────────

  const handleMapClick = (latlng) => {
    if (activeTool === 'view' || activeTool === 'forbidden' || !ocadData || !activeCircuit) return
    if (activeCircuit.status === 'ai_suggesting') return

    updateActiveCircuit(c => {
      const controls = [
        ...c.controls,
        {
          id: Date.now().toString(),
          type: activeTool,
          lat: latlng.lat,
          lng: latlng.lng,
          order: c.controls.length + 1,
        },
      ]
      return { controls }
    })
    if (activeTool === 'start') setActiveTool('control')
  }

  const handleDeleteControl = (controlId) => {
    updateActiveCircuit(c => {
      const filtered = c.controls.filter(ctrl => ctrl.id !== controlId)
      return { controls: filtered.map((ctrl, i) => ({ ...ctrl, order: i + 1 })) }
    })
  }

  // ── Forbidden zones ──────────────────────────────────────────────────────────

  const handleAddForbiddenZone = (polygon) => {
    if (!activeCircuit || polygon.length < 3) return
    updateActiveCircuit(c => ({ forbiddenZones: [...c.forbiddenZones, polygon] }))
  }

  // ── AI suggestion workflow ───────────────────────────────────────────────────

  const handleAiGenerate = async () => {
    if (!ocadData?.geojson || isGenerating || !activeCircuit) return
    setIsGenerating(true)
    setGenerationError(null)
    try {
      const bbox = extractBoundingBox(ocadData.geojson)
      const circuitParams = getCircuitParams(activeCircuit)
      const startControl = activeCircuit.controls.find(c => c.type === 'start')
      const mapContext = buildMapContext(ocadData.geojson)

      const params = {
        bounding_box: bbox,
        method: 'genetic',
        num_variants: 1,
        ...circuitParams,
        ...(mapContext && { map_context: mapContext }),
        ...(startControl && { start_position: [startControl.lng, startControl.lat] }),
        // Pass forbidden zones in polygon format
        forbidden_zones_polygons: activeCircuit.forbiddenZones,
        // Pass already-placed mandatory controls
        required_controls: activeCircuit.controls
          .filter(c => c.type === 'control')
          .map(c => ({ lat: c.lat, lng: c.lng })),
        // OCAD feature centroids (attractive features) for terrain-aware placement
        candidate_points: extractCandidatePoints(ocadData.geojson),
      }

      const res = await generateCircuit(params)
      console.log('[AI Generate] response:', res.data)
      const best = res.data?.circuits?.[0]
      console.log('[AI Generate] best circuit:', best)
      if (!best?.controls?.length) throw new Error('Aucun circuit généré')

      const hasStart = activeCircuit.controls.some(c => c.type === 'start')
      const hasFinish = activeCircuit.controls.some(c => c.type === 'finish')

      const suggestions = best.controls
        .map((c, idx) => ({
          id: `ai_${Date.now()}_${idx}`,
          type: c.type || (idx === 0 ? 'start' : idx === best.controls.length - 1 ? 'finish' : 'control'),
          lat: c.y,
          lng: c.x,
          order: c.order ?? idx + 1,
        }))
        .filter(s => !(s.type === 'start' && hasStart) && !(s.type === 'finish' && hasFinish))

      console.log('[AI Generate] suggestions:', suggestions)
      updateActiveCircuit({ aiSuggestions: suggestions, suggestionIdx: 0, status: 'ai_suggesting' })
    } catch (err) {
      const detail = err.response?.data?.detail
      setGenerationError(
        typeof detail === 'string' ? detail :
        Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join(' | ') :
        err.message || 'Erreur génération IA'
      )
    } finally {
      setIsGenerating(false)
    }
  }

  const handleValidateSuggestion = () => {
    updateActiveCircuit(c => {
      const suggestion = c.aiSuggestions[c.suggestionIdx]
      if (!suggestion) return { status: 'complete' }
      const newControl = { ...suggestion, order: c.controls.length + 1 }
      const controls = [...c.controls, newControl].map((ctrl, i) => ({ ...ctrl, order: i + 1 }))
      const newIdx = c.suggestionIdx + 1
      return {
        controls,
        suggestionIdx: newIdx,
        status: newIdx >= c.aiSuggestions.length ? 'complete' : 'ai_suggesting',
      }
    })
  }

  const handleSkipSuggestion = () => {
    updateActiveCircuit(c => {
      const newIdx = c.suggestionIdx + 1
      return {
        suggestionIdx: newIdx,
        status: newIdx >= c.aiSuggestions.length ? 'complete' : 'ai_suggesting',
      }
    })
  }

  const handleUpdateSuggestion = ({ lat, lng }) => {
    updateActiveCircuit(c => {
      const suggestions = [...c.aiSuggestions]
      suggestions[c.suggestionIdx] = { ...suggestions[c.suggestionIdx], lat, lng }
      return { aiSuggestions: suggestions }
    })
  }

  // ── IOF XML export ───────────────────────────────────────────────────────────

  const handleExportIOF = () => {
    if (!activeCircuit?.controls?.length) return
    const ordered = [...activeCircuit.controls]
      .filter(c => ['start', 'control', 'finish'].includes(c.type))
      .sort((a, b) => a.order - b.order)

    const now = new Date().toISOString()
    const date = now.split('T')[0]
    const courseName = activeCircuit.name

    let xml = `<?xml version="1.0" encoding="UTF-8"?>\n`
    xml += `<CourseData xmlns="http://www.orienteering.org/datastandard/3.0" iofVersion="3.0" createTime="${now}" creator="AItraceur">\n`
    xml += `  <Event><Name>${ocadData?.fileName || 'AItraceur'}</Name><StartTime><Date>${date}</Date></StartTime></Event>\n`
    xml += `  <RaceCourseData>\n`
    ordered.forEach((c, i) => {
      const ctrlId = c.type === 'start' ? 'S' : c.type === 'finish' ? 'F' : String(30 + i)
      xml += `    <Control><Id>${ctrlId}</Id><Position lat="${c.lat}" lng="${c.lng}"/></Control>\n`
    })
    xml += `    <Course>\n`
    xml += `      <Name>${courseName}</Name>\n`
    xml += `      <Length>${computeCourseDistance(activeCircuit.controls)}</Length>\n`
    xml += `      <Climb>0</Climb>\n`
    ordered.forEach((c, i) => {
      const ctrlId = c.type === 'start' ? 'S' : c.type === 'finish' ? 'F' : String(30 + i)
      const type = c.type === 'start' ? 'Start' : c.type === 'finish' ? 'Finish' : 'Control'
      xml += `      <CourseControl type="${type}"><Control>${ctrlId}</Control></CourseControl>\n`
    })
    xml += `    </Course>\n`
    xml += `  </RaceCourseData>\n`
    xml += `</CourseData>\n`

    const blob = new Blob([xml], { type: 'application/xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${courseName.replace(/\s+/g, '_')}_IOF3.xml`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ── Derived values for active circuit ────────────────────────────────────────

  const controls = activeCircuit?.controls ?? []
  const courseDistance = computeCourseDistance(controls)
  const controlCount = controls.filter(c => c.type === 'control').length
  const currentSuggestion =
    activeCircuit?.status === 'ai_suggesting'
      ? activeCircuit.aiSuggestions[activeCircuit.suggestionIdx] ?? null
      : null

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-screen bg-gray-900 text-white overflow-hidden font-sans">

      {/* SIDEBAR */}
      <aside className="w-80 flex-shrink-0 bg-gray-800 border-r border-gray-700 flex flex-col z-20 shadow-xl">

        {/* Header */}
        <div className="p-4 border-b border-gray-700 bg-gray-800">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-500 rounded-md flex items-center justify-center shadow-lg shadow-blue-500/20">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-bold text-white tracking-tight">AItraceur</h1>
              <p className="text-[10px] text-blue-400 font-medium uppercase tracking-wider">Éditeur de parcours</p>
            </div>
          </div>
        </div>

        {/* Circuit selector (visible when map loaded) */}
        {ocadData && (
          <CircuitSelector
            circuits={circuits}
            activeCircuitId={activeCircuitId}
            onSelect={setActiveCircuitId}
            onDelete={handleDeleteCircuit}
            onAddNew={() => setShowCreationForm(true)}
          />
        )}

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">

          {error && (
            <div className="mb-4 p-3 bg-red-900/50 border border-red-500/50 rounded-lg text-sm text-red-200">
              {error}
            </div>
          )}

          {/* No map loaded */}
          {!ocadData ? (
            <div className="space-y-4">
              <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
                <h2 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
                  <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                  Projet
                </h2>
                <OcadUploader onOcadLoaded={handleOcadLoaded} onLoading={setIsLoading} onError={handleError} />
              </div>
              <div className="text-xs text-gray-500 p-4 bg-gray-800/50 rounded-lg border border-gray-700/50 text-center">
                Chargez un fichier .ocd pour commencer à tracer.
              </div>
            </div>
          ) : (
            <div className="space-y-4">

              {/* Map info */}
              <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
                <div className="flex justify-between items-start mb-2">
                  <h2 className="text-sm font-semibold text-gray-200">Carte Active</h2>
                  <button
                    onClick={() => { setOcadData(null); setCircuits([]); setActiveCircuitId(null); setImageData(null) }}
                    className="text-xs text-gray-400 hover:text-red-400 transition-colors"
                  >
                    Fermer
                  </button>
                </div>
                <div className="flex items-center gap-2 text-sm text-blue-300 bg-blue-900/20 p-2 rounded truncate">
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="truncate">{ocadData.fileName}</span>
                </div>
                <div className="mt-2 text-xs text-gray-500 flex justify-between">
                  <span>OCAD v{ocadData.version}</span>
                  <span>{ocadData.geojson?.features?.length || 0} objets</span>
                </div>
                <div className="mt-2 text-xs flex items-center gap-1.5">
                  {renderLoading ? (
                    <>
                      <span className="w-3 h-3 border-2 border-blue-400/30 border-t-blue-400 rounded-full animate-spin inline-block" />
                      <span className="text-blue-400">Rendu ISOM en cours…</span>
                    </>
                  ) : imageData ? (
                    <>
                      <span className="w-2 h-2 rounded-full bg-green-500" />
                      <span className="text-green-400">Rendu raster ISOM actif</span>
                    </>
                  ) : (
                    <>
                      <span className="w-2 h-2 rounded-full bg-yellow-500" />
                      <span className="text-yellow-400">Service de rendu indisponible</span>
                    </>
                  )}
                </div>
              </div>

              {/* Active circuit panel */}
              {activeCircuit ? (
                <>
                  {/* Circuit info */}
                  <div className="bg-blue-900/20 border border-blue-700/30 rounded-xl p-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-blue-400 uppercase tracking-wider font-medium">Circuit actif</p>
                        <p className="text-lg font-bold text-white">{activeCircuit.name}</p>
                      </div>
                      <div className="text-right text-xs text-gray-400">
                        {activeCircuit.status === 'complete' && <span className="text-green-400 font-medium">✓ Complet</span>}
                        {activeCircuit.status === 'ai_suggesting' && <span className="text-purple-400 animate-pulse">Suggestion IA…</span>}
                        {activeCircuit.status === 'setup' && <span className="text-gray-500">En cours</span>}
                      </div>
                    </div>
                  </div>

                  {/* Tools */}
                  {activeCircuit.status !== 'ai_suggesting' && (
                    <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
                      <h2 className="text-sm font-semibold text-gray-200 mb-3">Outils de tracé</h2>
                      <div className="grid grid-cols-2 gap-2">
                        {tools.map(tool => (
                          <button
                            key={tool.id}
                            onClick={() => setActiveTool(tool.id)}
                            className={`flex flex-col items-center justify-center p-3 rounded-lg border transition-all ${
                              activeTool === tool.id
                                ? 'bg-blue-600 border-blue-500 shadow-inner'
                                : 'bg-gray-800 border-gray-700 hover:border-gray-500 hover:bg-gray-700 text-gray-400'
                            }`}
                          >
                            <span className="text-xl mb-1">{tool.icon}</span>
                            <span className={`text-[10px] font-medium ${activeTool === tool.id ? 'text-white' : ''}`}>
                              {tool.label}
                            </span>
                          </button>
                        ))}
                      </div>
                      {activeTool === 'forbidden' && (
                        <p className="text-xs text-gray-500 text-center mt-2">
                          Cliquez pour ajouter des sommets · Bouton "✓" sur la carte pour fermer
                        </p>
                      )}
                    </div>
                  )}

                  {/* AI suggestion panel */}
                  <AISuggestionPanel
                    activeCircuit={activeCircuit}
                    onValidate={handleValidateSuggestion}
                    onSkip={handleSkipSuggestion}
                  />

                  {/* Controls list */}
                  {controls.length > 0 && (
                    <ControlsList
                      controls={controls}
                      onDelete={handleDeleteControl}
                      totalDistance={courseDistance}
                      controlCount={controlCount}
                    />
                  )}

                  {/* Terrain */}
                  <TerrainPanel
                    ocadData={ocadData}
                    onTerrainLoaded={(data) => { setTerrainData(data); setShowRunnability(true) }}
                    showRunnability={showRunnability}
                    onToggleRunnability={() => setShowRunnability(v => !v)}
                  />

                  {/* Actions */}
                  <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
                    <h2 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
                      <span className="text-purple-400">✨</span> Actions IA
                    </h2>

                    <button
                      onClick={handleAiGenerate}
                      disabled={isGenerating || activeCircuit.status === 'ai_suggesting'}
                      className="w-full mb-2 py-2.5 px-4 bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2 shadow-lg shadow-purple-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isGenerating ? (
                        <>
                          <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin inline-block" />
                          Génération…
                        </>
                      ) : (
                        <>
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                          Générer avec l'IA
                        </>
                      )}
                    </button>

                    {generationError && (
                      <p className="text-xs text-red-400 mt-1 mb-2">{generationError}</p>
                    )}

                    <button
                      onClick={handleExportIOF}
                      disabled={controls.length === 0}
                      className="w-full py-2.5 px-4 bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-600 text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                      Export IOF XML 3.0
                    </button>

                    <button
                      onClick={() => setShowChat(v => !v)}
                      className="w-full mt-2 py-2 px-4 bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-600 text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                      </svg>
                      {showChat ? 'Fermer le chat' : 'Chat IA (ffco-iof-v7)'}
                    </button>
                  </div>
                </>
              ) : (
                /* No active circuit — prompt to create one */
                <div className="text-center p-6 bg-gray-700/30 rounded-xl border border-dashed border-gray-600">
                  <p className="text-gray-400 text-sm mb-3">Carte chargée. Créez votre premier circuit.</p>
                  <button
                    onClick={() => setShowCreationForm(true)}
                    className="py-2.5 px-5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    Créer un circuit
                  </button>
                </div>
              )}

            </div>
          )}
        </div>
      </aside>

      {/* AI Chat panel */}
      {showChat && <AiChatPanel onClose={() => setShowChat(false)} />}

      {/* MAIN MAP */}
      <main className="flex-1 relative z-10 bg-gray-950">
        {isLoading && (
          <div className="absolute inset-0 bg-gray-900/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center">
            <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mb-4" />
            <p className="text-blue-400 font-medium animate-pulse">Conversion OCAD en cours...</p>
          </div>
        )}

        {/* Top info bar */}
        {ocadData && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 bg-gray-800/90 backdrop-blur border border-gray-700 px-6 py-2 rounded-full shadow-lg pointer-events-none flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-sm font-medium text-gray-200">
                {activeCircuit
                  ? <>Circuit : <span className="text-blue-400 font-bold">{activeCircuit.name}</span></>
                  : <span className="text-gray-400">Aucun circuit actif</span>
                }
              </span>
            </div>
            {activeCircuit && (
              <>
                <div className="w-px h-4 bg-gray-600" />
                <div className="text-sm text-gray-400">
                  Mode: <span className="text-blue-400">{tools.find(t => t.id === activeTool)?.label}</span>
                </div>
                <div className="w-px h-4 bg-gray-600" />
                <div className="text-sm text-gray-400">{controls.length} point(s)</div>
              </>
            )}
          </div>
        )}

        <MapViewer
          ocadData={ocadData}
          onMapClick={handleMapClick}
          controls={controls}
          forbiddenZones={activeCircuit?.forbiddenZones ?? []}
          currentSuggestion={currentSuggestion}
          activeTool={activeTool}
          terrainData={showRunnability ? terrainData : null}
          imageData={imageData}
          onAddForbiddenZone={handleAddForbiddenZone}
          onUpdateSuggestion={handleUpdateSuggestion}
        />
      </main>

      {/* Circuit creation modal */}
      <CircuitCreationModal
        isOpen={showCreationForm}
        onClose={() => setShowCreationForm(false)}
        onCreateCircuit={handleCreateCircuit}
      />
    </div>
  )
}

export default App
