export default function CircuitSelector({ circuits, activeCircuitId, onSelect, onDelete, onAddNew }) {
  return (
    <div className="border-b border-gray-700 px-3 py-2.5">
      <div className="flex items-center gap-1.5 flex-wrap">

        {circuits.length === 0 ? (
          <button
            onClick={onAddNew}
            className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-600/40 text-blue-400 text-sm font-medium rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Créer un circuit
          </button>
        ) : (
          <>
            {circuits.map(c => (
              <div
                key={c.id}
                onClick={() => onSelect(c.id)}
                className={`flex items-center gap-1 pl-2.5 pr-1 py-1 rounded-full text-xs font-medium transition-all cursor-pointer select-none ${
                  c.id === activeCircuitId
                    ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/20'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                <span>{c.name}</span>
                {c.status === 'ai_suggesting' && (
                  <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse ml-0.5" />
                )}
                {c.status === 'complete' && (
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 ml-0.5" />
                )}
                <button
                  onClick={e => { e.stopPropagation(); onDelete(c.id) }}
                  className={`ml-0.5 w-4 h-4 flex items-center justify-center rounded-full transition-colors ${
                    c.id === activeCircuitId ? 'hover:bg-blue-500' : 'hover:bg-gray-500'
                  }`}
                  title="Supprimer ce circuit"
                >
                  <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}

            <button
              onClick={onAddNew}
              className="w-6 h-6 flex items-center justify-center rounded-full bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-white transition-colors flex-shrink-0"
              title="Ajouter un circuit"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
            </button>
          </>
        )}
      </div>
    </div>
  )
}
