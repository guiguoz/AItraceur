export default function AISuggestionPanel({ activeCircuit, onValidate, onSkip }) {
  if (!activeCircuit || activeCircuit.status !== 'ai_suggesting') return null

  const { aiSuggestions, suggestionIdx } = activeCircuit
  const total = aiSuggestions.length
  const suggestion = aiSuggestions[suggestionIdx]

  if (!suggestion) return null

  const typeLabel =
    suggestion.type === 'start' ? 'Départ suggéré' :
    suggestion.type === 'finish' ? 'Arrivée suggérée' :
    `Poste #${aiSuggestions.slice(0, suggestionIdx).filter(s => s.type === 'control').length + 1} suggéré`

  return (
    <div className="bg-purple-900/30 border border-purple-700/50 p-4 rounded-xl">

      {/* Header + progress */}
      <div className="flex items-center gap-2 mb-2">
        <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse flex-shrink-0" />
        <h3 className="text-sm font-semibold text-purple-200">Suggestion IA</h3>
        <span className="ml-auto text-xs text-purple-400 font-mono">{suggestionIdx + 1}/{total}</span>
      </div>

      <div className="w-full h-1 bg-gray-700 rounded-full mb-3 overflow-hidden">
        <div
          className="h-full bg-purple-500 rounded-full transition-all duration-300"
          style={{ width: `${Math.round((suggestionIdx / total) * 100)}%` }}
        />
      </div>

      <p className="text-sm text-white font-medium mb-0.5">{typeLabel}</p>
      {suggestion.description && suggestion.description !== 'Position libre' && (
        <p className="text-xs text-purple-300 font-medium mb-1 flex items-center gap-1">
          <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          {suggestion.description}
        </p>
      )}
      <p className="text-xs text-gray-400 mb-3">
        {suggestion.lat.toFixed(5)}°N, {suggestion.lng.toFixed(5)}°E
        <span className="block text-gray-500 mt-0.5">Faites glisser le marqueur violet pour ajuster la position</span>
      </p>

      <div className="flex gap-2">
        <button
          onClick={onValidate}
          className="flex-1 py-2 bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-1.5"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Valider
        </button>
        <button
          onClick={onSkip}
          className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-1.5"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
          Refuser
        </button>
      </div>

      {suggestionIdx + 1 >= total && (
        <p className="text-xs text-center text-gray-500 mt-2">Dernier poste — validez ou refusez pour terminer</p>
      )}
    </div>
  )
}
