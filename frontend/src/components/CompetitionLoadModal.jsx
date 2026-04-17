import { useState, useEffect } from 'react'
import { listCompetitions, deleteCompetition } from '../services/api'

/**
 * Modal de chargement d'une compétition sauvegardée.
 * Affiche la liste des compétitions (nom + date) et permet de charger ou supprimer.
 */
export default function CompetitionLoadModal({ isOpen, onLoad, onClose }) {
  const [competitions, setCompetitions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(null)

  useEffect(() => {
    if (!isOpen) return
    setLoading(true)
    setError(null)
    listCompetitions()
      .then(res => setCompetitions(res.data))
      .catch(() => setError('Impossible de charger la liste des compétitions.'))
      .finally(() => setLoading(false))
  }, [isOpen])

  if (!isOpen) return null

  const handleDelete = async (id, e) => {
    e.stopPropagation()
    if (!window.confirm('Supprimer cette compétition ?')) return
    setDeleting(id)
    try {
      await deleteCompetition(id)
      setCompetitions(prev => prev.filter(c => c.id !== id))
    } catch {
      setError('Erreur lors de la suppression.')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-gray-800 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-md">

        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-gray-700">
          <h2 className="text-base font-semibold text-white">Charger une compétition</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-5">
          {loading && (
            <p className="text-gray-400 text-sm text-center py-6">Chargement…</p>
          )}

          {error && (
            <p className="text-red-400 text-sm text-center py-4">{error}</p>
          )}

          {!loading && !error && competitions.length === 0 && (
            <p className="text-gray-500 text-sm text-center py-6">Aucune compétition sauvegardée.</p>
          )}

          {!loading && competitions.length > 0 && (
            <ul className="space-y-2 max-h-72 overflow-y-auto">
              {competitions.map(comp => (
                <li
                  key={comp.id}
                  onClick={() => onLoad(comp.id)}
                  className="flex items-center justify-between bg-gray-700/50 hover:bg-gray-700 border border-gray-600 rounded-lg px-4 py-3 cursor-pointer transition-colors group"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-white truncate">{comp.name}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {comp.updated_at
                        ? new Date(comp.updated_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
                        : new Date(comp.created_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}
                    </p>
                  </div>
                  <button
                    onClick={(e) => handleDelete(comp.id, e)}
                    disabled={deleting === comp.id}
                    className="ml-3 text-gray-500 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 flex-shrink-0"
                    title="Supprimer"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

      </div>
    </div>
  )
}
