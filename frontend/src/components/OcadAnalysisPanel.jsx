// Panel affiché dans la sidebar quand un .ocd a été analysé (Étape 13c)
// Affiche le rapport par catégorie ISOM + nombre de candidats extraits

const CATEGORY_LABELS = {
  courbes_niveau:   { icon: '⛰️', label: 'Courbes de niveau' },
  rochers_reliefs:  { icon: '🪨', label: 'Rochers / reliefs' },
  eau_marecages:    { icon: '💧', label: 'Eau / marécages' },
  vegetation:       { icon: '🌲', label: 'Végétation' },
  chemins_sentiers: { icon: '🛤️', label: 'Chemins / sentiers' },
  batiments_urbain: { icon: '🏢', label: 'Bâtiments / urbain' },
  zones_oob:        { icon: '🚫', label: 'Zones hors-limites' },
}

export function OcadAnalysisPanel({ analysis }) {
  if (!analysis) return null

  return (
    <div className="mt-3 p-3 bg-gray-800/60 rounded-lg border border-gray-700 text-xs">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-violet-400 font-semibold">Analyse OCAD</span>
        <span className="text-gray-500">{analysis.total_features} éléments</span>
      </div>

      {/* Catégories */}
      <div className="space-y-1 mb-3">
        {Object.entries(analysis.by_category || {})
          .filter(([, v]) => v.count > 0)
          .sort(([, a], [, b]) => b.count - a.count)
          .map(([key, val]) => {
            const meta = CATEGORY_LABELS[key] || { icon: '📍', label: key }
            return (
              <div key={key} className="flex items-center justify-between">
                <span className="text-gray-400">
                  {meta.icon} {meta.label}
                </span>
                <span className="text-gray-300 font-mono">{val.count}</span>
              </div>
            )
          })}
      </div>

      {/* Candidats postes */}
      <div className="border-t border-gray-700 pt-2 mb-2">
        <div className="flex items-center justify-between">
          <span className="text-gray-400">Candidats postes</span>
          <span className="text-violet-300 font-semibold">{analysis.candidate_points_extracted}</span>
        </div>
      </div>

      {/* Résumé terrain */}
      {analysis.terrain_summary && (
        <p className="text-gray-500 leading-snug mb-1">{analysis.terrain_summary}</p>
      )}
      {analysis.recommendations && (
        <p className="text-violet-400/80 leading-snug">{analysis.recommendations}</p>
      )}
    </div>
  )
}
