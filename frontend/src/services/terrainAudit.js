/**
 * terrainAudit.js — Stockage local des observations de vérification terrain.
 *
 * Les observations sont liées à une carte OCAD via son empreinte (computeMapFingerprint).
 * Elles référencent des features par featureIndex (index dans objectsGeoJson) et symNum,
 * mais ne déplacent jamais la géométrie OCAD et ne modifient pas le fichier source.
 *
 * Persistance : localStorage uniquement.
 * Pas de compte, pas de sync cloud, pas de base de données.
 */

const STORAGE_PREFIX = 'aitraceur_terrain_obs_'

/** Statuts valides pour une observation terrain */
export const OBSERVATION_STATUS = /** @type {const} */ ({
  TO_VERIFY: 'to_verify',
  OK: 'ok',
  ABSENT: 'absent',
  INACCESSIBLE: 'inaccessible',
})

export const STATUS_LABELS = {
  [OBSERVATION_STATUS.TO_VERIFY]: 'À vérifier',
  [OBSERVATION_STATUS.OK]: 'Conforme sur le terrain',
  [OBSERVATION_STATUS.ABSENT]: 'Absent / différent',
  [OBSERVATION_STATUS.INACCESSIBLE]: 'Inaccessible / dangereux',
}

export const STATUS_COLORS = {
  [OBSERVATION_STATUS.TO_VERIFY]: 'text-yellow-400 bg-yellow-900/30 border-yellow-700/40',
  [OBSERVATION_STATUS.OK]: 'text-green-400 bg-green-900/30 border-green-700/40',
  [OBSERVATION_STATUS.ABSENT]: 'text-red-400 bg-red-900/30 border-red-700/40',
  [OBSERVATION_STATUS.INACCESSIBLE]: 'text-orange-400 bg-orange-900/30 border-orange-700/40',
}

function _storageKey(fingerprint) {
  return STORAGE_PREFIX + fingerprint
}

/**
 * Charge les observations d'une empreinte depuis localStorage.
 * @param {string} fingerprint
 * @returns {Observation[]}
 *
 * @typedef {Object} Observation
 * @property {string}      id
 * @property {number|null} featureIndex  Index dans objectsGeoJson.features (ou null)
 * @property {number|null} symNum        Valeur brute sym (ou null)
 * @property {string}      status        OBSERVATION_STATUS value
 * @property {string}      note
 * @property {string}      date          ISO date YYYY-MM-DD
 * @property {number|null} gpsLat        Position GPS observée (consentement utilisateur)
 * @property {number|null} gpsLng
 */
export function loadObservations(fingerprint) {
  if (!fingerprint) return []
  try {
    const raw = localStorage.getItem(_storageKey(fingerprint))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

/** Persiste le tableau d'observations complet pour une empreinte. */
export function _saveObservations(fingerprint, observations) {
  if (!fingerprint) return
  localStorage.setItem(_storageKey(fingerprint), JSON.stringify(observations))
}

/** Ajoute une observation. Retourne la liste mise à jour. */
export function addObservation(fingerprint, obs) {
  const existing = loadObservations(fingerprint)
  const newObs = {
    id: `obs_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    featureIndex: obs.featureIndex ?? null,
    symNum: obs.symNum ?? null,
    status: obs.status ?? OBSERVATION_STATUS.TO_VERIFY,
    note: obs.note ?? '',
    date: obs.date ?? new Date().toISOString().slice(0, 10),
    gpsLat: obs.gpsLat ?? null,
    gpsLng: obs.gpsLng ?? null,
  }
  const updated = [...existing, newObs]
  _saveObservations(fingerprint, updated)
  return updated
}

/** Modifie une observation existante par id. Retourne la liste mise à jour. */
export function updateObservation(fingerprint, id, patch) {
  const existing = loadObservations(fingerprint)
  const updated = existing.map(o => o.id === id ? { ...o, ...patch, id } : o)
  _saveObservations(fingerprint, updated)
  return updated
}

/** Supprime une observation par id. Retourne la liste mise à jour. */
export function removeObservation(fingerprint, id) {
  const existing = loadObservations(fingerprint)
  const updated = existing.filter(o => o.id !== id)
  _saveObservations(fingerprint, updated)
  return updated
}

/**
 * Exporte les observations en objet JSON sérialisable.
 * Inclut l'empreinte pour valider la compatibilité à la réimport.
 * @param {string} fingerprint
 * @param {Observation[]} observations
 * @returns {object}
 */
export function exportToJson(fingerprint, observations) {
  return {
    _aitraceur_terrain_audit: true,
    fingerprint,
    exportedAt: new Date().toISOString(),
    observations,
  }
}

/**
 * Importe des observations depuis un objet JSON.
 * Lance une Error si l'empreinte ne correspond pas ou si le format est invalide.
 * Ne persiste pas — l'appelant doit appeler _saveObservations si l'import est accepté.
 *
 * @param {object} json
 * @param {string} currentFingerprint
 * @returns {Observation[]}
 * @throws {Error}
 */
export function importFromJson(json, currentFingerprint) {
  if (!json?._aitraceur_terrain_audit) {
    throw new Error('Format invalide — fichier non reconnu comme export AItraceur.')
  }
  if (json.fingerprint !== currentFingerprint) {
    throw new Error(
      `Empreinte de carte incompatible.\n` +
      `Fichier importé : ${json.fingerprint}\n` +
      `Carte actuelle  : ${currentFingerprint}`
    )
  }
  if (!Array.isArray(json.observations)) {
    throw new Error('Format invalide — champ observations manquant ou non-tableau.')
  }
  return json.observations
}
