/**
 * DialogueLog — Affiche les échanges traceur ↔ contrôleur
 * pendant et après la génération sprint avec validation IOF/FFCO.
 */

export default function DialogueLog({ dialogue, controleurReport, isGenerating, progressLabel }) {
  if (!dialogue?.length && !isGenerating) return null

  return (
    <div className="bg-gray-900/60 border border-gray-700 rounded-xl p-3 mt-2 space-y-1.5">
      {/* Barre de progression */}
      {isGenerating && (
        <div className="mb-2">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="w-3 h-3 border-2 border-purple-400/30 border-t-purple-400 rounded-full animate-spin inline-block flex-shrink-0" />
            <span className="text-xs text-purple-300 font-medium">{progressLabel || 'Génération en cours…'}</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-1.5 overflow-hidden">
            <div className="h-full bg-gradient-to-r from-purple-500 to-blue-500 rounded-full animate-pulse" style={{ width: '60%' }} />
          </div>
        </div>
      )}

      {/* Log des échanges */}
      {dialogue.map((entry, i) => (
        <DialogueEntry key={i} entry={entry} />
      ))}

      {/* Rapport final */}
      {!isGenerating && controleurReport && (
        <ControleurSummary report={controleurReport} />
      )}
    </div>
  )
}

function DialogueEntry({ entry }) {
  const isTraceur = entry.role === 'traceur'
  const isControleur = entry.role === 'controleur'
  const isSystem = entry.role === 'system'

  if (isSystem) {
    return (
      <div className="text-[10px] text-gray-500 italic px-1">
        {entry.message}
      </div>
    )
  }

  const icon = isTraceur ? '🗺' : '⚖️'
  const label = isTraceur ? 'Traceur' : 'Contrôleur'
  const colorClass = isTraceur
    ? 'text-blue-400 bg-blue-900/20 border-blue-700/30'
    : 'text-amber-400 bg-amber-900/20 border-amber-700/30'

  return (
    <div className={`flex gap-2 p-2 rounded-lg border ${colorClass}`}>
      <span className="text-base flex-shrink-0 mt-0.5">{icon}</span>
      <div className="min-w-0">
        <p className="text-[9px] font-semibold uppercase tracking-wider opacity-70 mb-0.5">
          {label} {entry.step ? `· iter. ${entry.step}` : ''}
        </p>
        <p className="text-xs leading-relaxed break-words">{entry.message}</p>
      </div>
    </div>
  )
}

function ControleurSummary({ report }) {
  const scoreColor = report.global_score >= 85
    ? 'text-green-400'
    : report.global_score >= 65
    ? 'text-yellow-400'
    : 'text-red-400'

  return (
    <div className="mt-2 pt-2 border-t border-gray-700">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] text-gray-400 font-semibold uppercase tracking-wider">Rapport contrôleur</span>
        <span className={`text-sm font-bold ${scoreColor}`}>{report.global_score?.toFixed(0)}/100</span>
      </div>
      <div className="flex gap-3 text-[10px]">
        <span className="text-red-400">{report.error_count} erreur(s)</span>
        <span className="text-yellow-400">{report.warning_count} avert.</span>
        <span className={report.iof_compliant ? 'text-green-400' : 'text-gray-500'}>
          {report.iof_compliant ? '✓ IOF' : '✗ IOF'}
        </span>
        <span className={report.ffco_compliant ? 'text-green-400' : 'text-gray-500'}>
          {report.ffco_compliant ? '✓ FFCO' : '✗ FFCO'}
        </span>
      </div>
      {report.issues?.filter(i => i.severity === 'ERROR').map((issue, j) => (
        <div key={j} className="mt-1 text-[10px] text-red-300 pl-2 border-l border-red-700/50">
          {issue.code} P{issue.control_index + 1} — {issue.message}
        </div>
      ))}
    </div>
  )
}
