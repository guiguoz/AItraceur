/**
 * TerrainAuditPanel — Audit de vérification terrain sans création de postes.
 *
 * Permet à un humain de consigner des observations sur les features OCAD
 * visibles dans OcadDiagPanel. Les observations sont stockées en localStorage,
 * liées à l'empreinte de la carte, exportables/importables en JSON.
 *
 * N'alimente PAS les candidats postes, ne modifie PAS le fichier OCAD.
 */

import { useState, useEffect } from 'react'
import {
  loadObservations, addObservation, updateObservation, removeObservation,
  exportToJson, importFromJson, _saveObservations,
  OBSERVATION_STATUS, STATUS_LABELS, STATUS_COLORS,
} from '../services/terrainAudit'

const STATUS_OPTIONS = Object.entries(STATUS_LABELS)

/**
 * @param {{
 *   fingerprint: string|null,
 *   selectedFeatureIndex: number|null,
 *   selectedSymNum: number|null,
 * }} props
 */
export function TerrainAuditPanel({ fingerprint, selectedFeatureIndex, selectedSymNum }) {
  const [open, setOpen] = useState(false)
  const [observations, setObservations] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [importError, setImportError] = useState(null)
  const [form, setForm] = useState({
    status: OBSERVATION_STATUS.TO_VERIFY,
    note: '',
    date: new Date().toISOString().slice(0, 10),
    gpsLat: null,
    gpsLng: null,
    featureIndex: null,
    symNum: null,
  })

  // Recharge les observations quand l'empreinte change
  useEffect(() => {
    setObservations(loadObservations(fingerprint))
    setShowForm(false)
    setImportError(null)
  }, [fingerprint])

  // Pré-remplit le formulaire avec la feature sélectionnée dans OcadDiagPanel
  useEffect(() => {
    if (!showForm) return
    setForm(prev => ({
      ...prev,
      featureIndex: selectedFeatureIndex ?? null,
      symNum: selectedSymNum ?? null,
    }))
  }, [showForm, selectedFeatureIndex, selectedSymNum])

  const handleAdd = () => {
    if (!fingerprint) return
    const updated = addObservation(fingerprint, form)
    setObservations(updated)
    setShowForm(false)
    setForm({
      status: OBSERVATION_STATUS.TO_VERIFY,
      note: '',
      date: new Date().toISOString().slice(0, 10),
      gpsLat: null, gpsLng: null,
      featureIndex: null, symNum: null,
    })
  }

  const handleStatusChange = (id, status) => {
    const updated = updateObservation(fingerprint, id, { status })
    setObservations(updated)
  }

  const handleRemove = (id) => {
    const updated = removeObservation(fingerprint, id)
    setObservations(updated)
  }

  const handleGetGps = () => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      pos => setForm(prev => ({
        ...prev,
        gpsLat: parseFloat(pos.coords.latitude.toFixed(6)),
        gpsLng: parseFloat(pos.coords.longitude.toFixed(6)),
      })),
      () => {}
    )
  }

  const handleExport = () => {
    if (!fingerprint) return
    const data = exportToJson(fingerprint, observations)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `terrain_audit_${fingerprint.slice(0, 20)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleImport = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const json = JSON.parse(ev.target.result)
        const imported = importFromJson(json, fingerprint)
        _saveObservations(fingerprint, imported)
        setObservations(imported)
        setImportError(null)
      } catch (err) {
        setImportError(err.message)
      }
    }
    reader.readAsText(file)
  }

  if (!fingerprint) return null

  return (
    <div className="mt-3 p-3 bg-gray-800/60 rounded-lg border border-gray-700 text-xs space-y-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-gray-400 hover:text-blue-400 transition-colors w-full text-left"
      >
        <span className="text-xs">{open ? '▾' : '▸'}</span>
        <span className="text-blue-300 font-semibold">Audit terrain</span>
        {observations.length > 0 && (
          <span className="ml-auto text-gray-500">{observations.length} obs.</span>
        )}
      </button>

      {open && (
        <div className="space-y-2">
          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowForm(v => !v)}
              disabled={!fingerprint}
              className="flex-1 py-1 px-2 bg-blue-700/40 hover:bg-blue-700/60 text-blue-300 rounded transition-colors disabled:opacity-40"
            >
              + Ajouter observation
            </button>
            <button
              onClick={handleExport}
              disabled={observations.length === 0}
              title="Exporter en JSON"
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors disabled:opacity-40"
            >
              ↑ Export
            </button>
            <label
              className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors cursor-pointer"
              title="Importer depuis JSON"
            >
              ↓ Import
              <input type="file" accept=".json" onChange={handleImport} className="hidden" />
            </label>
          </div>

          {importError && (
            <div className="p-2 bg-red-900/40 border border-red-700/40 rounded text-red-300 whitespace-pre-wrap">
              {importError}
            </div>
          )}

          {/* Formulaire d'ajout */}
          {showForm && (
            <div className="p-2 bg-gray-900/60 border border-gray-700 rounded space-y-1.5">
              {(selectedFeatureIndex != null || selectedSymNum != null) && (
                <div className="text-gray-500 text-xs">
                  {selectedFeatureIndex != null && <span>Feature #{selectedFeatureIndex} </span>}
                  {selectedSymNum != null && <span className="font-mono">sym {selectedSymNum}</span>}
                </div>
              )}

              <select
                value={form.status}
                onChange={e => setForm(prev => ({ ...prev, status: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-600 rounded px-1.5 py-1 text-gray-200 text-xs focus:outline-none focus:border-blue-500"
              >
                {STATUS_OPTIONS.map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>

              <textarea
                placeholder="Note libre (facultative)…"
                value={form.note}
                onChange={e => setForm(prev => ({ ...prev, note: e.target.value }))}
                rows={2}
                className="w-full bg-gray-800 border border-gray-600 rounded px-1.5 py-1 text-gray-200 text-xs placeholder-gray-600 focus:outline-none focus:border-blue-500 resize-none"
              />

              <div className="flex gap-2 items-center">
                <input
                  type="date"
                  value={form.date}
                  onChange={e => setForm(prev => ({ ...prev, date: e.target.value }))}
                  className="flex-1 bg-gray-800 border border-gray-600 rounded px-1.5 py-0.5 text-gray-200 text-xs focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={handleGetGps}
                  title="Utiliser la position GPS actuelle (consentement navigateur requis)"
                  className="px-1.5 py-0.5 bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-green-400 rounded transition-colors"
                >
                  GPS
                </button>
              </div>

              {(form.gpsLat != null) && (
                <div className="font-mono text-green-600 text-xs">
                  {form.gpsLat}, {form.gpsLng}
                </div>
              )}

              <div className="flex gap-2">
                <button
                  onClick={handleAdd}
                  className="flex-1 py-1 bg-blue-700 hover:bg-blue-600 text-white rounded transition-colors"
                >
                  Enregistrer
                </button>
                <button
                  onClick={() => setShowForm(false)}
                  className="px-3 py-1 text-gray-500 hover:text-gray-300 transition-colors"
                >
                  Annuler
                </button>
              </div>
            </div>
          )}

          {/* Liste des observations */}
          {observations.length === 0 && !showForm && (
            <p className="text-gray-600 text-center italic py-2">Aucune observation</p>
          )}

          {observations.map(obs => (
            <div key={obs.id} className="p-2 bg-gray-900/40 border border-gray-800 rounded space-y-0.5">
              <div className="flex items-center justify-between gap-1">
                <select
                  value={obs.status}
                  onChange={e => handleStatusChange(obs.id, e.target.value)}
                  className={`text-xs px-1 py-0.5 rounded border bg-transparent font-medium focus:outline-none ${STATUS_COLORS[obs.status] ?? ''}`}
                >
                  {STATUS_OPTIONS.map(([v, l]) => (
                    <option key={v} value={v} className="bg-gray-900 text-gray-200">{l}</option>
                  ))}
                </select>
                <button
                  onClick={() => handleRemove(obs.id)}
                  className="text-gray-600 hover:text-red-400 transition-colors text-xs ml-auto"
                  title="Supprimer"
                >
                  ✕
                </button>
              </div>

              {obs.note && (
                <p className="text-gray-400 leading-snug whitespace-pre-wrap">{obs.note}</p>
              )}

              <div className="flex gap-3 text-gray-600">
                <span>{obs.date}</span>
                {obs.featureIndex != null && <span className="font-mono">feat #{obs.featureIndex}</span>}
                {obs.symNum != null && <span className="font-mono">sym {obs.symNum}</span>}
                {obs.gpsLat != null && (
                  <span className="font-mono text-green-800">
                    {obs.gpsLat},{obs.gpsLng}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
