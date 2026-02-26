import { useState, useEffect } from 'react'

const CATEGORIES = [
  '10', '12', '14', '16', '18', '20', '21', '21E',
  '35', '40', '45', '50', '55', '60', '65', '70', '75', '80',
]

const COLORS = ['Vert', 'Bleu', 'Jaune', 'Orange', 'Violet', 'Noir']

const TYPE_LABELS = {
  sprint: 'Sprint',
  md: 'Moyenne distance',
  ld: 'Longue distance',
  couleur: 'Circuit de couleur',
}

const TYPE_SHORT = { sprint: 'Sprint', md: 'MD', ld: 'LD' }

function buildName({ type, sex, category, color }) {
  if (type === 'couleur') return color || 'Couleur'
  return `${sex}${category} ${TYPE_SHORT[type]}`
}

export default function CircuitCreationModal({ isOpen, onClose, onCreateCircuit }) {
  const [type, setType] = useState('md')
  const [sex, setSex] = useState('H')
  const [category, setCategory] = useState('21E')
  const [color, setColor] = useState('Vert')

  useEffect(() => {
    if (isOpen) { setType('md'); setSex('H'); setCategory('21E'); setColor('Vert') }
  }, [isOpen])

  if (!isOpen) return null

  const isCompetitive = type !== 'couleur'
  const name = buildName({ type, sex, category, color })

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-gray-800 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-sm">

        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-gray-700">
          <h2 className="text-base font-semibold text-white">Nouveau circuit</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-5 space-y-4">

          {/* Type */}
          <div>
            <label className="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-2">Type de circuit</label>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(TYPE_LABELS).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setType(key)}
                  className={`py-2 px-3 rounded-lg text-sm font-medium transition-all ${
                    type === key
                      ? 'bg-blue-600 text-white border border-blue-500'
                      : 'bg-gray-700 text-gray-300 border border-gray-600 hover:border-gray-500'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Compétitif : Sexe + Catégorie */}
          {isCompetitive && (
            <>
              <div>
                <label className="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-2">Sexe</label>
                <div className="grid grid-cols-2 gap-2">
                  {[['H', 'Homme (H)'], ['D', 'Dame (D)']].map(([s, label]) => (
                    <button
                      key={s}
                      onClick={() => setSex(s)}
                      className={`py-2 rounded-lg text-sm font-medium transition-all ${
                        sex === s
                          ? 'bg-blue-600 text-white border border-blue-500'
                          : 'bg-gray-700 text-gray-300 border border-gray-600 hover:border-gray-500'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-2">Catégorie</label>
                <select
                  value={category}
                  onChange={e => setCategory(e.target.value)}
                  className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-blue-500"
                >
                  {CATEGORIES.map(cat => (
                    <option key={cat} value={cat}>{sex}{cat}</option>
                  ))}
                </select>
              </div>
            </>
          )}

          {/* Couleur FFCO */}
          {!isCompetitive && (
            <div>
              <label className="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-2">Couleur FFCO</label>
              <div className="grid grid-cols-3 gap-2">
                {COLORS.map(c => (
                  <button
                    key={c}
                    onClick={() => setColor(c)}
                    className={`py-2 rounded-lg text-sm font-medium transition-all ${
                      color === c
                        ? 'bg-blue-600 text-white border border-blue-500'
                        : 'bg-gray-700 text-gray-300 border border-gray-600 hover:border-gray-500'
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Résumé */}
          <div className="bg-blue-900/20 border border-blue-700/30 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400 mb-1">Circuit</p>
            <p className="text-xl font-bold text-white tracking-wide">{name}</p>
            <p className="text-xs text-blue-400">{TYPE_LABELS[type]}</p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex gap-3 p-5 pt-0">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm font-medium transition-colors"
          >
            Annuler
          </button>
          <button
            onClick={() => onCreateCircuit({ name, type, sex: isCompetitive ? sex : null, category: isCompetitive ? category : null, color: !isCompetitive ? color : null })}
            className="flex-1 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold transition-colors"
          >
            Créer
          </button>
        </div>
      </div>
    </div>
  )
}
