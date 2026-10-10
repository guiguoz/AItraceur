/**
 * OcadDiagPanel — Diagnostic factuel d'un fichier OCAD chargé.
 *
 * Affiche : version OCAD, CRS déclaré, statut reprojection, échelle (source),
 * comptes features (total / objets / primitives / sans sym) et inventaire
 * des symboles bruts avec leurs définitions OCAD.
 *
 * NE CONTIENT PAS de recommandation forêt/sprint, de nombre de candidats
 * postes ni de conseils de circuit — ces informations restent dans OcadAnalysisPanel.
 */

import { useState, useMemo } from 'react'

/**
 * @param {{
 *   diagInfo: {
 *     version: *,
 *     crsInfo: string,
 *     crsCode: number|null,
 *     scale: number|null,
 *     crsScale: number|null,
 *     featuresTotal: number,
 *     featuresObjects: number,
 *     featuresPrimitives: number,
 *     featuresNoSym: number,
 *   },
 *   inventory: import('../services/ocadInventory').InventoryResult,
 *   selectedSymNum: number|null,
 *   onSelectSymbol: (symNum: number|null) => void,
 * }} props
 */
export function OcadDiagPanel({ diagInfo, inventory, selectedSymNum, onSelectSymbol }) {
  const [showInventory, setShowInventory] = useState(false)
  const [filter, setFilter] = useState('')

  const filteredEntries = useMemo(() => {
    if (!inventory?.entries) return []
    const q = filter.trim().toLowerCase()
    if (!q) return inventory.entries
    return inventory.entries.filter(e =>
      String(e.symNum).includes(q) ||
      (e.number ?? '').toLowerCase().includes(q) ||
      (e.description ?? '').toLowerCase().includes(q)
    )
  }, [inventory, filter])

  if (!diagInfo) return null

  const {
    version, crsInfo, scale, crsScale,
    featuresTotal, featuresObjects, featuresPrimitives, featuresNoSym,
  } = diagInfo

  const scaleSource =
    scale != null && crsScale != null && scale !== crsScale
      ? `${scale} (setup) / ${crsScale} (CRS) — valeurs différentes`
      : scale != null
        ? `1 : ${scale.toLocaleString('fr-FR')} (setup)`
        : crsScale != null
          ? `1 : ${crsScale.toLocaleString('fr-FR')} (CRS)`
          : 'non détectée'

  const hasUnknown = inventory?.unknownSymNums?.length > 0
  const hasNoSym = featuresNoSym > 0

  return (
    <div className="mt-3 p-3 bg-gray-800/60 rounded-lg border border-gray-700 text-xs space-y-2">
      {/* En-tête */}
      <div className="flex items-center justify-between">
        <span className="text-blue-400 font-semibold">Diagnostic OCAD</span>
        {version != null && <span className="text-gray-500 font-mono">v{String(version)}</span>}
      </div>

      {/* CRS */}
      <div>
        <span className="text-gray-500 mr-1">CRS :</span>
        <span className="text-gray-300">{crsInfo || 'inconnu'}</span>
      </div>

      {/* Échelle */}
      <div>
        <span className="text-gray-500 mr-1">Échelle :</span>
        <span className={scale == null && crsScale == null ? 'text-yellow-400' : 'text-gray-300'}>
          {scaleSource}
        </span>
        {scale == null && crsScale == null && (
          <span className="ml-1 text-yellow-600">(attention : échelle inconnue)</span>
        )}
      </div>

      {/* Comptes features */}
      <div className="border-t border-gray-700 pt-2 space-y-0.5">
        <div className="flex justify-between">
          <span className="text-gray-500">Total (avec primitives)</span>
          <span className="font-mono text-gray-300">{featuresTotal ?? '–'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Objets exportés</span>
          <span className="font-mono text-green-400 font-semibold">{featuresObjects ?? '–'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Primitives graphiques</span>
          <span className="font-mono text-gray-500">{featuresPrimitives ?? '–'}</span>
        </div>
        {hasNoSym && (
          <div className="flex justify-between text-yellow-600">
            <span>Sans sym (hors inventaire)</span>
            <span className="font-mono">{featuresNoSym}</span>
          </div>
        )}
      </div>

      {/* Avertissements */}
      {(hasUnknown || hasNoSym) && (
        <div className="border-t border-gray-700 pt-1 space-y-0.5">
          {hasUnknown && (
            <p className="text-yellow-500">
              {inventory.unknownSymNums.length} symNum(s) sans définition dans la table OCAD
            </p>
          )}
          {hasNoSym && (
            <p className="text-yellow-600">
              {featuresNoSym} feature(s) sans propriété sym (primitives échappées ?)
            </p>
          )}
        </div>
      )}

      {/* Inventaire symboles — dépliable */}
      <div className="border-t border-gray-700 pt-2">
        <button
          onClick={() => setShowInventory(v => !v)}
          className="flex items-center gap-1 text-gray-400 hover:text-blue-400 transition-colors w-full text-left"
        >
          <span className="text-xs">{showInventory ? '▾' : '▸'}</span>
          <span>
            Inventaire symboles
            {inventory?.entries?.length != null && (
              <span className="ml-1 text-gray-500">({inventory.entries.length})</span>
            )}
          </span>
          {selectedSymNum != null && (
            <span className="ml-auto text-blue-400 font-mono">sym {selectedSymNum}</span>
          )}
        </button>

        {showInventory && (
          <div className="mt-2 space-y-1">
            <input
              type="text"
              placeholder="Filtrer par code, numéro ou description…"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
            />

            <div className="max-h-56 overflow-y-auto rounded border border-gray-700 mt-1">
              <table className="w-full text-xs border-collapse">
                <thead className="sticky top-0 bg-gray-900 text-gray-500">
                  <tr>
                    <th className="text-left px-1 py-0.5 font-normal">sym brut</th>
                    <th className="text-left px-1 py-0.5 font-normal">N°</th>
                    <th className="text-left px-1 py-0.5 font-normal">Description</th>
                    <th className="text-right px-1 py-0.5 font-normal">n</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEntries.length === 0 && (
                    <tr>
                      <td colSpan={4} className="text-center text-gray-600 py-2 italic">Aucun résultat</td>
                    </tr>
                  )}
                  {filteredEntries.map(entry => {
                    const isSelected = selectedSymNum === entry.symNum
                    const isUnknown = !entry.hasDef
                    return (
                      <tr
                        key={entry.symNum}
                        onClick={() => onSelectSymbol?.(isSelected ? null : entry.symNum)}
                        className={`cursor-pointer border-t border-gray-800 transition-colors ${
                          isSelected
                            ? 'bg-blue-900/40 text-blue-200'
                            : isUnknown
                              ? 'text-yellow-500 hover:bg-gray-700/40'
                              : 'text-gray-300 hover:bg-gray-700/40'
                        }`}
                      >
                        <td className="px-1 py-0.5 font-mono">{entry.symNum}</td>
                        <td className="px-1 py-0.5 font-mono text-gray-400">
                          {entry.number ?? <span className="text-gray-700">—</span>}
                        </td>
                        <td className="px-1 py-0.5 truncate max-w-[120px]" title={entry.description ?? ''}>
                          {isUnknown
                            ? <span className="text-yellow-600 italic">sym inconnu</span>
                            : entry.description ?? <span className="text-gray-600 italic">sans desc.</span>
                          }
                        </td>
                        <td className="px-1 py-0.5 text-right font-mono text-gray-400">
                          {entry.count}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {selectedSymNum != null && (() => {
              const entry = inventory?.entries?.find(e => e.symNum === selectedSymNum)
              if (!entry) return null
              return (
                <div className="mt-1 p-2 bg-blue-900/20 border border-blue-700/40 rounded text-xs">
                  <div className="flex justify-between mb-0.5">
                    <span className="text-gray-400">otp :</span>
                    <span className="font-mono">{entry.otp ?? '—'}</span>
                  </div>
                  <div className="flex justify-between mb-0.5">
                    <span className="text-gray-400">Géométries :</span>
                    <span className="font-mono text-gray-300">{entry.geomTypes.join(', ') || '—'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Définition OCAD :</span>
                    <span className={entry.hasDef ? 'text-green-400' : 'text-yellow-500'}>
                      {entry.hasDef ? 'présente' : 'absente'}
                    </span>
                  </div>
                  <button
                    onClick={() => onSelectSymbol?.(null)}
                    className="mt-1 text-gray-600 hover:text-gray-400 text-xs"
                  >
                    Désélectionner
                  </button>
                </div>
              )
            })()}
          </div>
        )}
      </div>
    </div>
  )
}
