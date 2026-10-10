/**
 * ocadInventory.js — Inventaire des symboles OCAD depuis le GeoJSON objets.
 *
 * Travaille sur objectsGeoJson (generateSymbolElements:false) — objets de la
 * carte uniquement, sans les primitives graphiques auto-générées par les symboles.
 * Ne modifie pas geojson (flux d'affichage/génération) ni ATTRACTIVE_ISOM.
 */

/**
 * Construit un inventaire consultable par code symbole brut.
 *
 * @param {object} rawOcad        Résultat de readOcad() — .symbols = table symboles
 * @param {object} objectsGeoJson FeatureCollection WGS84 (generateSymbolElements:false)
 * @returns {InventoryResult}
 *
 * @typedef {Object} SymbolEntry
 * @property {number}   symNum      Valeur brute de la propriété sym (ex: 201000)
 * @property {string|null} number   Numéro formaté OCAD (ex: "201.0") — null si absent
 * @property {string|null} description Texte de la définition symbole
 * @property {number|null} otp      Object type preference (ocad2geojson)
 * @property {boolean}  hasDef      true si une définition OCAD existe pour ce symNum
 * @property {string[]} geomTypes   Types de géométrie observés (Point/LineString/Polygon…)
 * @property {number}   count       Nombre de features avec ce symNum
 * @property {number[]} featureIndices Indices dans objectsGeoJson.features
 *
 * @typedef {Object} InventoryResult
 * @property {SymbolEntry[]} entries       Triées par symNum croissant
 * @property {number[]}      noSymIndices  Indices de features sans propriété sym
 * @property {number[]}      unknownSymNums symNums sans définition dans la table OCAD
 */
export function buildSymbolInventory(rawOcad, objectsGeoJson) {
  const symbolTable = _buildSymbolTable(rawOcad?.symbols)
  const features = objectsGeoJson?.features ?? []

  const bySymNum = new Map()
  const noSymIndices = []

  for (let idx = 0; idx < features.length; idx++) {
    const feat = features[idx]
    const rawSym = feat?.properties?.sym

    if (rawSym == null) {
      noSymIndices.push(idx)
      continue
    }

    const symNum = typeof rawSym === 'number' ? rawSym : parseInt(String(rawSym), 10)
    if (!Number.isFinite(symNum)) {
      noSymIndices.push(idx)
      continue
    }

    if (!bySymNum.has(symNum)) {
      const def = symbolTable.get(symNum) ?? null
      bySymNum.set(symNum, {
        symNum,
        number: def?.number ?? null,
        description: def?.description ?? null,
        otp: def?.otp ?? null,
        hasDef: def != null,
        _geomTypesSet: new Set(),
        count: 0,
        featureIndices: [],
      })
    }

    const entry = bySymNum.get(symNum)
    const geomType = feat.geometry?.type ?? 'Unknown'
    entry._geomTypesSet.add(geomType)
    entry.count++
    entry.featureIndices.push(idx)
  }

  const entries = [...bySymNum.values()].map(e => {
    const { _geomTypesSet, ...rest } = e
    return { ...rest, geomTypes: [..._geomTypesSet].sort() }
  }).sort((a, b) => a.symNum - b.symNum)

  const unknownSymNums = entries.filter(e => !e.hasDef).map(e => e.symNum)

  return { entries, noSymIndices, unknownSymNums }
}

/**
 * Construit une Map<symNum, def> depuis rawOcad.symbols (tableau ou objet).
 * @param {Array|object|undefined} symbols
 * @returns {Map<number, object>}
 */
function _buildSymbolTable(symbols) {
  const table = new Map()
  if (!symbols) return table

  const arr = Array.isArray(symbols) ? symbols : Object.values(symbols)
  for (const sym of arr) {
    if (sym != null && sym.symNum != null) {
      table.set(sym.symNum, sym)
    }
  }
  return table
}

/**
 * Calcule l'empreinte stable d'une carte OCAD chargée.
 * Utilisée pour rattacher les observations terrain au bon fichier.
 *
 * L'empreinte repose sur des propriétés déterministes du fichier :
 * nom, version OCAD, code CRS, nombre d'objets exportés.
 * Elle n'inclut PAS le chemin complet du fichier (varie selon l'OS/utilisateur).
 *
 * @param {{ version: *, crsCode: *, featuresObjects: number, fileName: string }} info
 * @returns {string}
 */
export function computeMapFingerprint({ version, crsCode, featuresObjects, fileName }) {
  const v = version != null ? String(version) : '?'
  const c = crsCode != null ? String(crsCode) : '0'
  const o = featuresObjects != null ? String(featuresObjects) : '0'
  // Normalise le nom de fichier (enlève le chemin, garde l'extension)
  const n = fileName
    ? String(fileName).replace(/.*[/\\]/, '').replace(/[^\w.-]/g, '_')
    : ''
  return `${n}|v${v}|crs${c}|obj${o}`
}
