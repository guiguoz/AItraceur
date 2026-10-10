import { describe, it, expect } from 'vitest'
import { buildSymbolInventory, computeMapFingerprint } from '../services/ocadInventory.js'

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

// ── computeMapFingerprint ─────────────────────────────────────────────────────

describe('computeMapFingerprint', () => {
  it('produit une empreinte reproductible avec les mêmes entrées', () => {
    const info = { version: '12.18.18', crsCode: 2154, featuresObjects: 3504, fileName: 'carte.ocd' }
    expect(computeMapFingerprint(info)).toBe(computeMapFingerprint(info))
  })

  it('empreintes différentes pour des fichiers distincts', () => {
    const a = computeMapFingerprint({ version: '12', crsCode: 2154, featuresObjects: 3504, fileName: 'a.ocd' })
    const b = computeMapFingerprint({ version: '12', crsCode: 2154, featuresObjects: 3504, fileName: 'b.ocd' })
    expect(a).not.toBe(b)
  })

  it('empreintes différentes si featuresObjects diffère', () => {
    const a = computeMapFingerprint({ version: '12', crsCode: 2154, featuresObjects: 3504, fileName: 'x.ocd' })
    const b = computeMapFingerprint({ version: '12', crsCode: 2154, featuresObjects: 9999, fileName: 'x.ocd' })
    expect(a).not.toBe(b)
  })

  it('tolère les champs null/undefined', () => {
    const fp = computeMapFingerprint({ version: null, crsCode: null, featuresObjects: null, fileName: null })
    expect(typeof fp).toBe('string')
    expect(fp.length).toBeGreaterThan(0)
  })

  it("extrait le nom de fichier sans chemin complet", () => {
    const fp = computeMapFingerprint({
      version: '12', crsCode: 2154, featuresObjects: 100,
      fileName: 'C:\\Users\\user\\Maps\\carte.ocd',
    })
    expect(fp).not.toContain('Users')
    expect(fp).toContain('carte.ocd')
  })
})
