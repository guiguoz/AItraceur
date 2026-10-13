import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  loadObservations, addObservation, updateObservation, removeObservation,
  exportToJson, importFromJson, _saveObservations,
  OBSERVATION_STATUS,
} from '../services/terrainAudit.js'
import { OCAD_PARSER_VERSION } from '../services/ocadInventory.js'

// ── Mock localStorage ─────────────────────────────────────────────────────────

function makeMockStorage() {
  const store = {}
  return {
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: (k) => { delete store[k] },
    clear: () => { Object.keys(store).forEach(k => delete store[k]) },
    get _store() { return store },
  }
}

let mockStorage

beforeEach(() => {
  mockStorage = makeMockStorage()
  vi.stubGlobal('localStorage', mockStorage)
})

// ── loadObservations ──────────────────────────────────────────────────────────

describe('loadObservations', () => {
  it('retourne [] si fingerprint null', () => {
    expect(loadObservations(null)).toEqual([])
  })

  it('retourne [] si aucune entrée en storage', () => {
    expect(loadObservations('fp_abc')).toEqual([])
  })

  it('retourne le tableau persisté', () => {
    const fp = 'fp_test'
    const obs = [{ id: 'obs_1', status: OBSERVATION_STATUS.OK, note: 'test' }]
    _saveObservations(fp, obs)
    expect(loadObservations(fp)).toEqual(obs)
  })

  it('retourne [] si la valeur stockée est du JSON invalide', () => {
    localStorage.setItem('aitraceur_terrain_obs_fp_bad', '{not json}')
    expect(loadObservations('fp_bad')).toEqual([])
  })
})

// ── addObservation ────────────────────────────────────────────────────────────

describe('addObservation', () => {
  it('ajoute une observation et retourne la liste mise à jour', () => {
    const fp = 'fp_add'
    const updated = addObservation(fp, { note: 'Falaise visible', status: OBSERVATION_STATUS.OK })
    expect(updated).toHaveLength(1)
    expect(updated[0].note).toBe('Falaise visible')
    expect(updated[0].status).toBe(OBSERVATION_STATUS.OK)
  })

  it('attribue un id unique à chaque observation', () => {
    const fp = 'fp_ids'
    addObservation(fp, { note: 'obs1' })
    addObservation(fp, { note: 'obs2' })
    const loaded = loadObservations(fp)
    expect(loaded[0].id).not.toBe(loaded[1].id)
  })

  it('utilise TO_VERIFY comme statut par défaut', () => {
    const fp = 'fp_default'
    const [obs] = addObservation(fp, { note: 'x' })
    expect(obs.status).toBe(OBSERVATION_STATUS.TO_VERIFY)
  })

  it('persiste les champs featureIndex et symNum', () => {
    const fp = 'fp_link'
    addObservation(fp, { featureIndex: 42, symNum: 201000 })
    const [obs] = loadObservations(fp)
    expect(obs.featureIndex).toBe(42)
    expect(obs.symNum).toBe(201000)
  })

  it('stocke gpsLat/gpsLng quand fournis', () => {
    const fp = 'fp_gps'
    addObservation(fp, { gpsLat: 48.1234, gpsLng: 2.5678 })
    const [obs] = loadObservations(fp)
    expect(obs.gpsLat).toBe(48.1234)
    expect(obs.gpsLng).toBe(2.5678)
  })
})

// ── updateObservation ─────────────────────────────────────────────────────────

describe('updateObservation', () => {
  it('met à jour uniquement l\'observation ciblée', () => {
    const fp = 'fp_upd'
    addObservation(fp, { note: 'A' })
    addObservation(fp, { note: 'B' })
    const list = loadObservations(fp)
    const id = list[0].id

    const updated = updateObservation(fp, id, { status: OBSERVATION_STATUS.ABSENT })
    expect(updated.find(o => o.id === id).status).toBe(OBSERVATION_STATUS.ABSENT)
    expect(updated.find(o => o.id !== id).status).toBe(OBSERVATION_STATUS.TO_VERIFY)
  })

  it('ne modifie pas l\'id lors du patch', () => {
    const fp = 'fp_id_preserve'
    const [obs] = addObservation(fp, { note: 'x' })
    const id = obs.id
    const updated = updateObservation(fp, id, { note: 'y', id: 'hacked' })
    expect(updated[0].id).toBe(id)
  })
})

// ── removeObservation ─────────────────────────────────────────────────────────

describe('removeObservation', () => {
  it('supprime l\'observation par id', () => {
    const fp = 'fp_rm'
    addObservation(fp, { note: 'keep' })
    const [obs2] = addObservation(fp, { note: 'remove' }).slice(-1)
    // obs2 est la dernière ajoutée
    const beforeRemoval = loadObservations(fp)
    const toRemove = beforeRemoval[beforeRemoval.length - 1].id
    const updated = removeObservation(fp, toRemove)
    expect(updated.some(o => o.id === toRemove)).toBe(false)
    expect(updated).toHaveLength(beforeRemoval.length - 1)
  })
})

// ── exportToJson / importFromJson ─────────────────────────────────────────────

describe('exportToJson', () => {
  it('inclut l\'empreinte et le tableau d\'observations', () => {
    const fp = 'fp_export'
    const obs = [{ id: 'o1', note: 'test' }]
    const result = exportToJson(fp, obs)
    expect(result._aitraceur_terrain_audit).toBe(true)
    expect(result.fingerprint).toBe(fp)
    expect(result.observations).toEqual(obs)
  })
})

// ── parsedWith / ocadObjectId ─────────────────────────────────────────────────

describe('parsedWith et ocadObjectId', () => {
  it('une nouvelle observation individuelle enregistre parsedWith et ocadObjectId', () => {
    const fp = 'fp_pw_new'
    const added = addObservation(fp, {
      featureIndex: 3,
      ocadObjectId: 42,
      symNum: 201000,
      status: OBSERVATION_STATUS.OK,
      note: '',
      date: '2026-10-13',
      parsedWith: OCAD_PARSER_VERSION,
    })
    const obs = added[0]
    expect(obs.parsedWith).toBe(OCAD_PARSER_VERSION)
    expect(obs.ocadObjectId).toBe(42)
    expect(obs.featureIndex).toBe(3)
  })

  it('une ancienne observation sans parsedWith est préservée intacte', () => {
    const fp = 'fp_pw_old'
    const oldObs = [{
      id: 'obs_old_1',
      featureIndex: 5,
      symNum: 201000,
      status: OBSERVATION_STATUS.TO_VERIFY,
      note: 'ancienne',
      date: '2026-01-01',
      gpsLat: null,
      gpsLng: null,
    }]
    _saveObservations(fp, oldObs)
    const loaded = loadObservations(fp)
    expect(loaded).toHaveLength(1)
    expect(loaded[0].featureIndex).toBe(5)
    expect(loaded[0].parsedWith).toBeUndefined()
    expect(loaded[0].ocadObjectId).toBeUndefined()
  })

  it('sans ocadObjectId, même parsedWith courant → ocadObjectId null (index de liste seulement)', () => {
    const fp = 'fp_pw_noocadid'
    const added = addObservation(fp, {
      featureIndex: 7,
      ocadObjectId: null,  // explicitement absent
      symNum: 201000,
      status: OBSERVATION_STATUS.OK,
      note: '',
      date: '2026-10-13',
      parsedWith: OCAD_PARSER_VERSION,  // version actuelle, mais pas d'id OCAD
    })
    const obs = added[0]
    expect(obs.ocadObjectId).toBeNull()
    expect(obs.featureIndex).toBe(7)
    expect(obs.parsedWith).toBe(OCAD_PARSER_VERSION)
  })

  it('avec ocadObjectId présent → identifiant fiable conservé tel quel', () => {
    const fp = 'fp_pw_withocadid'
    const added = addObservation(fp, {
      featureIndex: 2,
      ocadObjectId: 137,
      symNum: 101000,
      status: OBSERVATION_STATUS.OK,
      note: '',
      date: '2026-10-13',
      parsedWith: OCAD_PARSER_VERSION,
    })
    const obs = added[0]
    expect(obs.ocadObjectId).toBe(137)
    expect(obs.featureIndex).toBe(2)
  })

  it('une observation créée avec une autre version du parseur est préservée', () => {
    const fp = 'fp_pw_other'
    const obs = addObservation(fp, {
      featureIndex: 2,
      ocadObjectId: 10,
      symNum: 501000,
      status: OBSERVATION_STATUS.OK,
      note: '',
      date: '2026-10-13',
      parsedWith: 'ocad2geojson@2.0.0',
    })
    const loaded = loadObservations(fp)
    expect(loaded).toHaveLength(1)
    expect(loaded[0].parsedWith).toBe('ocad2geojson@2.0.0')
    expect(loaded[0].parsedWith).not.toBe(OCAD_PARSER_VERSION)
    expect(loaded[0].featureIndex).toBe(2)
    expect(loaded[0].ocadObjectId).toBe(10)
  })
})

describe('importFromJson', () => {
  it('retourne les observations si empreinte correspond', () => {
    const fp = 'fp_import'
    const obs = [{ id: 'o1', note: 'a' }]
    const json = exportToJson(fp, obs)
    expect(importFromJson(json, fp)).toEqual(obs)
  })

  it('lève une erreur si le format est invalide', () => {
    expect(() => importFromJson({ foo: 'bar' }, 'fp')).toThrow(/Format invalide/)
  })

  it('lève une erreur si l\'empreinte ne correspond pas', () => {
    const json = exportToJson('fp_origine', [])
    expect(() => importFromJson(json, 'fp_autre')).toThrow(/incompatible/)
  })

  it('lève une erreur si observations n\'est pas un tableau', () => {
    const json = { _aitraceur_terrain_audit: true, fingerprint: 'fp', observations: null }
    expect(() => importFromJson(json, 'fp')).toThrow(/observations/)
  })
})
