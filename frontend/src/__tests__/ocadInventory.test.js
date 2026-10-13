import { describe, it, expect } from 'vitest'
import { buildSymbolInventory, computeFileFingerprint, resolveHighlightFeatures } from '../services/ocadInventory.js'

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeFeature(sym, geomType = 'Point') {
  const geometry =
    geomType === 'Point'
      ? { type: 'Point', coordinates: [2.0, 48.0] }
      : geomType === 'LineString'
        ? { type: 'LineString', coordinates: [[2.0, 48.0], [2.1, 48.1]] }
        : { type: 'Polygon', coordinates: [[[2.0, 48.0], [2.1, 48.0], [2.1, 48.1], [2.0, 48.0]]] }
  return {
    type: 'Feature',
    properties: sym != null ? { sym } : {},
    geometry,
  }
}

function makeOcad(symbols = []) {
  return { symbols }
}

// ── buildSymbolInventory ──────────────────────────────────────────────────────

describe('buildSymbolInventory', () => {
  it('sépare objets (avec sym) des features sans sym', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [
        makeFeature(201000),   // objet avec sym
        makeFeature(null),     // feature sans sym (primitive échappée ?)
        makeFeature(501000),   // objet avec sym
      ],
    }
    const { entries, noSymIndices } = buildSymbolInventory(makeOcad(), geojson)

    expect(entries).toHaveLength(2)
    expect(noSymIndices).toEqual([1])
  })

  it('regroupe les features par symNum exact', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [
        makeFeature(201000),
        makeFeature(201000, 'LineString'),
        makeFeature(201100),  // sous-numéro distinct
      ],
    }
    const { entries } = buildSymbolInventory(makeOcad(), geojson)

    expect(entries).toHaveLength(2)
    const e201000 = entries.find(e => e.symNum === 201000)
    expect(e201000.count).toBe(2)
    expect(e201000.geomTypes).toContain('Point')
    expect(e201000.geomTypes).toContain('LineString')
    const e201100 = entries.find(e => e.symNum === 201100)
    expect(e201100.count).toBe(1)
  })

  it('préserve le symNum brut, ne calcule pas de code base en remplacement', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [makeFeature(201100)],
    }
    const { entries } = buildSymbolInventory(makeOcad(), geojson)
    // symNum doit être 201100 (brut), pas 201 (code base)
    expect(entries[0].symNum).toBe(201100)
  })

  it('lie symNum à la définition OCAD via symNum exact', () => {
    const symDef = { symNum: 201000, number: '201.0', description: 'Falaise', otp: 3 }
    const geojson = {
      type: 'FeatureCollection',
      features: [makeFeature(201000)],
    }
    const { entries } = buildSymbolInventory(makeOcad([symDef]), geojson)

    const entry = entries[0]
    expect(entry.hasDef).toBe(true)
    expect(entry.number).toBe('201.0')
    expect(entry.description).toBe('Falaise')
    expect(entry.otp).toBe(3)
  })

  it('signale les symNums sans définition correspondante dans la table OCAD', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [makeFeature(999000)],
    }
    const { entries, unknownSymNums } = buildSymbolInventory(makeOcad([]), geojson)

    expect(entries[0].hasDef).toBe(false)
    expect(unknownSymNums).toContain(999000)
  })

  it('ne mélange pas définitions pour 201000 et 201100', () => {
    const defs = [
      { symNum: 201000, number: '201.0', description: 'Falaise haute', otp: 2 },
      { symNum: 201100, number: '201.1', description: 'Falaise basse', otp: 2 },
    ]
    const geojson = {
      type: 'FeatureCollection',
      features: [makeFeature(201000), makeFeature(201100)],
    }
    const { entries } = buildSymbolInventory(makeOcad(defs), geojson)

    const e0 = entries.find(e => e.symNum === 201000)
    const e1 = entries.find(e => e.symNum === 201100)
    expect(e0.description).toBe('Falaise haute')
    expect(e1.description).toBe('Falaise basse')
  })

  it('tolère rawOcad null (symboles = table vide)', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [makeFeature(101000)],
    }
    const { entries, unknownSymNums } = buildSymbolInventory(null, geojson)
    expect(entries).toHaveLength(1)
    expect(unknownSymNums).toContain(101000)
  })

  it('tolère objectsGeoJson null → inventaire vide', () => {
    const { entries, noSymIndices, unknownSymNums } = buildSymbolInventory(makeOcad(), null)
    expect(entries).toHaveLength(0)
    expect(noSymIndices).toHaveLength(0)
    expect(unknownSymNums).toHaveLength(0)
  })

  it('trie les entrées par symNum croissant', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [makeFeature(501000), makeFeature(101000), makeFeature(201000)],
    }
    const { entries } = buildSymbolInventory(makeOcad(), geojson)
    const nums = entries.map(e => e.symNum)
    expect(nums).toEqual([...nums].sort((a, b) => a - b))
  })

  it('utilise properties.objectIndex comme identifiant OCAD, pas feat.id', () => {
    const feat = {
      type: 'Feature',
      id: 999,  // numéro généré pendant le parcours — ne doit PAS être retenu
      properties: { sym: 201000, objectIndex: 42 },
      geometry: { type: 'Point', coordinates: [2.0, 48.0] },
    }
    const geojson = { type: 'FeatureCollection', features: [feat] }
    const { entries } = buildSymbolInventory(makeOcad(), geojson)
    expect(entries[0].ocadObjectIds[0]).toBe(42)
  })

  it('si objectIndex absent, ocadObjectId est null — feat.id non utilisé comme fallback', () => {
    const feat = {
      type: 'Feature',
      id: 999,
      properties: { sym: 201000 },  // pas de objectIndex
      geometry: { type: 'Point', coordinates: [2.0, 48.0] },
    }
    const geojson = { type: 'FeatureCollection', features: [feat] }
    const { entries } = buildSymbolInventory(makeOcad(), geojson)
    expect(entries[0].ocadObjectIds[0]).toBeNull()
  })

  it('stocke les featureIndices corrects', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [makeFeature(201000), makeFeature(501000), makeFeature(201000)],
    }
    const { entries } = buildSymbolInventory(makeOcad(), geojson)
    const e201 = entries.find(e => e.symNum === 201000)
    expect(e201.featureIndices).toEqual([0, 2])
    const e501 = entries.find(e => e.symNum === 501000)
    expect(e501.featureIndices).toEqual([1])
  })
})

// ── resolveHighlightFeatures ──────────────────────────────────────────────────

describe('resolveHighlightFeatures', () => {
  const f0 = makeFeature(201000)
  const f1 = makeFeature(201000, 'LineString')
  const f2 = makeFeature(501000)
  const geojson = {
    type: 'FeatureCollection',
    features: [f0, f1, f2],
  }

  function makeInventory() {
    return buildSymbolInventory(makeOcad(), geojson)
  }

  it('sans sym ni featureIndex → FeatureCollection vide', () => {
    const { features } = resolveHighlightFeatures(makeInventory(), geojson, null, null)
    expect(features).toHaveLength(0)
  })

  it('sym sélectionné sans featureIndex → toutes les features du sym', () => {
    const { features } = resolveHighlightFeatures(makeInventory(), geojson, 201000, null)
    expect(features).toHaveLength(2)
    expect(features).toContain(f0)
    expect(features).toContain(f1)
  })

  it('featureIndex sélectionné → uniquement cette feature', () => {
    const { features } = resolveHighlightFeatures(makeInventory(), geojson, 201000, 1)
    expect(features).toHaveLength(1)
    expect(features[0]).toBe(f1)
  })

  it('featureIndex prend le dessus — sym seul non retourné', () => {
    const { features } = resolveHighlightFeatures(makeInventory(), geojson, 201000, 0)
    expect(features).toHaveLength(1)
    expect(features[0]).toBe(f0)
  })

  it('sym inconnu dans inventaire → features vide', () => {
    const { features } = resolveHighlightFeatures(makeInventory(), geojson, 999000, null)
    expect(features).toHaveLength(0)
  })

  it('featureIndex hors-limites → features vide', () => {
    const { features } = resolveHighlightFeatures(makeInventory(), geojson, 201000, 99)
    expect(features).toHaveLength(0)
  })

  it('inventory null avec sym → features vide', () => {
    const { features } = resolveHighlightFeatures(null, geojson, 201000, null)
    expect(features).toHaveLength(0)
  })

  it('objectsGeoJson null avec featureIndex → features vide', () => {
    const { features } = resolveHighlightFeatures(makeInventory(), null, 201000, 0)
    expect(features).toHaveLength(0)
  })
})

// ── computeFileFingerprint ────────────────────────────────────────────────────

describe('computeFileFingerprint', () => {
  it('retourne une chaîne hex SHA-256 de 64 caractères', async () => {
    const buf = new Uint8Array([1, 2, 3]).buffer
    const fp = await computeFileFingerprint(buf)
    expect(fp).toHaveLength(64)
    expect(fp).toMatch(/^[0-9a-f]{64}$/)
  })

  it('est déterministe — même contenu → même empreinte', async () => {
    const buf = new Uint8Array([10, 20, 30, 40, 50]).buffer
    expect(await computeFileFingerprint(buf)).toBe(await computeFileFingerprint(buf))
  })

  it('deux contenus différents → deux empreintes différentes', async () => {
    const buf1 = new Uint8Array([1, 2, 3]).buffer
    const buf2 = new Uint8Array([4, 5, 6]).buffer
    expect(await computeFileFingerprint(buf1)).not.toBe(await computeFileFingerprint(buf2))
  })

  it('même nom et même nombre d\'objets mais contenu différent → empreintes différentes', async () => {
    // Simule deux versions d'un fichier portant le même nom et les mêmes métadonnées
    const versionA = new Uint8Array(new Array(200).fill(0xAA)).buffer
    const versionB = new Uint8Array(new Array(200).fill(0xBB)).buffer
    expect(await computeFileFingerprint(versionA)).not.toBe(await computeFileFingerprint(versionB))
  })

  it('un audit lié à une empreinte différente est refusé à l\'import', async () => {
    // Vérifie que la combinaison hash-based fingerprint + importFromJson rejette bien
    // un fichier d'audit provenant d'une autre carte
    const { importFromJson, exportToJson } = await import('../services/terrainAudit.js')
    const buf1 = new Uint8Array([0x01, 0x02]).buffer
    const buf2 = new Uint8Array([0x03, 0x04]).buffer
    const fp1 = await computeFileFingerprint(buf1)
    const fp2 = await computeFileFingerprint(buf2)
    const exported = exportToJson(fp1, [{ id: 'o1', note: 'test' }])
    expect(() => importFromJson(exported, fp2)).toThrow(/incompatible/)
  })
})
