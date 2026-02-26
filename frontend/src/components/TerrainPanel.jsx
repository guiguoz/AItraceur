import { useState } from 'react'
import { getRunnabilityGrid } from '../services/api'

/**
 * Extrait la bounding box d'un GeoJSON FeatureCollection.
 * Retourne { min_x, min_y, max_x, max_y } en WGS84 (lng/lat).
 */
function extractBbox(geojson) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const walk = (c) => {
    if (typeof c[0] === 'number') {
      if (minX > c[0]) minX = c[0]; if (maxX < c[0]) maxX = c[0]
      if (minY > c[1]) minY = c[1]; if (maxY < c[1]) maxY = c[1]
    } else c.forEach(walk)
  }
  geojson.features.forEach(f => f.geometry?.coordinates && walk(f.geometry.coordinates))
  return { min_x: minX, min_y: minY, max_x: maxX, max_y: maxY }
}

export default function TerrainPanel({ ocadData, onTerrainLoaded, showRunnability, onToggleRunnability }) {
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  const handleAnalyze = async () => {
    if (!ocadData?.geojson || loading) return
    setLoading(true)
    setError(null)
    try {
      const bbox = extractBbox(ocadData.geojson)
      const res = await getRunnabilityGrid(bbox, 100)
      const features = res.data?.features || []

      if (features.length === 0) {
        setError('Aucune donnée de terrain reçue.')
        return
      }

      const scores = features.map(f => f.properties.runnability)
      const avgScore = scores.reduce((a, b) => a + b, 0) / scores.length
      const avgSpeed = features.reduce((a, f) => a + f.properties.speed_mpm, 0) / features.length
      const forestCells = features.filter(f => f.properties.vegetation_height > 2).length
      const steepCells = features.filter(f => f.properties.slope_percent > 15).length

      setStats({
        cells: features.length,
        avgRunnability: Math.round(avgScore * 100),
        avgSpeed: Math.round(avgSpeed),
        forestCells,
        steepCells,
        pctForest: Math.round((forestCells / features.length) * 100),
        pctSteep: Math.round((steepCells / features.length) * 100),
      })
      onTerrainLoaded(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Erreur analyse terrain')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
      {/* Header */}
      <h2 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
        <svg className="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M5 3l3.5 6L12 5l3.5 4L19 3H5zm0 0v18m14-18v18M5 21h14" />
        </svg>
        Terrain & Runnabilité
      </h2>

      {/* Bouton d'analyse */}
      <button
        onClick={handleAnalyze}
        disabled={loading || !ocadData}
        className="w-full mb-2 py-2.5 px-4 bg-green-700 hover:bg-green-600 text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? (
          <>
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin inline-block" />
            Analyse en cours…
          </>
        ) : (
          <>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
            Analyser la runnabilité
          </>
        )}
      </button>

      {error && (
        <p className="text-xs text-red-400 mb-2">{error}</p>
      )}

      {/* Stats */}
      {stats && (
        <div className="mt-2 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-gray-800/60 rounded-lg p-2 text-center">
              <div className="text-lg font-bold text-green-400">{stats.avgRunnability}%</div>
              <div className="text-[10px] text-gray-400 mt-0.5">Runnabilité moy.</div>
            </div>
            <div className="bg-gray-800/60 rounded-lg p-2 text-center">
              <div className="text-lg font-bold text-blue-400">{stats.avgSpeed}</div>
              <div className="text-[10px] text-gray-400 mt-0.5">m/min moy.</div>
            </div>
            <div className="bg-gray-800/60 rounded-lg p-2 text-center">
              <div className="text-lg font-bold text-emerald-500">{stats.pctForest}%</div>
              <div className="text-[10px] text-gray-400 mt-0.5">Forêt/végét.</div>
            </div>
            <div className="bg-gray-800/60 rounded-lg p-2 text-center">
              <div className="text-lg font-bold text-amber-400">{stats.pctSteep}%</div>
              <div className="text-[10px] text-gray-400 mt-0.5">Pente &gt;15%</div>
            </div>
          </div>

          {/* Toggle overlay */}
          <button
            onClick={onToggleRunnability}
            className={`w-full py-2 px-3 text-sm font-medium rounded-lg border transition-colors flex items-center justify-center gap-2 ${
              showRunnability
                ? 'bg-green-900/40 border-green-600 text-green-300'
                : 'bg-gray-800 border-gray-600 text-gray-400 hover:border-green-600 hover:text-green-300'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${showRunnability ? 'bg-green-400' : 'bg-gray-600'}`} />
            {showRunnability ? 'Overlay activé' : 'Afficher l\'overlay'}
          </button>

          {/* Légende */}
          {showRunnability && (
            <div className="mt-1 p-2 bg-gray-800/40 rounded-lg">
              <p className="text-[10px] text-gray-500 mb-1.5 font-medium uppercase tracking-wide">Légende IOF</p>
              <div className="space-y-1">
                {[
                  { color: 'bg-transparent border border-gray-600', label: 'Terrain ouvert (rapide)' },
                  { color: 'bg-[#d4e6a0]', label: 'Terrain lent' },
                  { color: 'bg-[#8bc34a]', label: 'Forêt légère' },
                  { color: 'bg-[#4caf50]', label: 'Forêt dense' },
                  { color: 'bg-[#2e7d32]', label: 'Forêt très dense' },
                  { color: 'bg-[#1b5e20]', label: 'Impraticable' },
                ].map(({ color, label }) => (
                  <div key={label} className="flex items-center gap-2">
                    <div className={`w-3 h-3 rounded-sm flex-shrink-0 ${color}`} />
                    <span className="text-[10px] text-gray-400">{label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
