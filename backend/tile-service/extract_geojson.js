/**
 * extract_geojson.js — Extraction GeoJSON anonymisée depuis un fichier OCAD
 * =========================================================================
 * Usage : node extract_geojson.js <chemin_vers_fichier.ocd>
 *
 * Sortie : GeoJSON sur stdout (features terrain avec codes ISOM)
 * Les coordonnées sont converties en WGS84 puis recentrées sur (0, 0)
 * et exprimées en mètres relatifs pour correspondance avec contrôles IOF XML.
 */

const { readOcad, ocadToGeoJson } = require('ocad2geojson')
const proj4 = require('proj4')

// Lambert-93 (EPSG:2154) — CRS des cartes OCAD françaises
proj4.defs('EPSG:2154',
  '+proj=lcc +lat_1=49 +lat_2=44 +lat_0=46.5 +lon_0=3 +x_0=700000 +y_0=6600000 ' +
  '+ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs')

const ocdPath = process.argv[2]

if (!ocdPath) {
  process.stderr.write('Usage: node extract_geojson.js <fichier.ocd>\n')
  process.exit(1)
}

/**
 * Détecte si les coordonnées sont projetées (Lambert-93 ou similaire)
 * plutôt que WGS84. Lambert-93 : x ~ 100k–1200k, y ~ 6000k–7200k.
 * En pratique : si |x| > 1000 ou |y| > 1000, c'est du projeté.
 */
function isProjected(x, y) {
  return Math.abs(x) > 1000 || Math.abs(y) > 1000
}

/**
 * Reprojete [x, y] depuis Lambert-93 vers WGS84 [lng, lat].
 * Si les coordonnées semblent déjà en WGS84, les retourne telles quelles.
 */
function toWGS84(x, y) {
  if (isProjected(x, y)) {
    return proj4('EPSG:2154', 'WGS84', [x, y])  // [lng, lat]
  }
  return [x, y]  // déjà WGS84
}

/**
 * Extrait tous les [x, y] d'une géométrie GeoJSON.
 */
function flatCoords(geom) {
  if (!geom) return []
  if (geom.type === 'Point') return [geom.coordinates]
  if (geom.type === 'LineString') return geom.coordinates
  if (geom.type === 'Polygon') return geom.coordinates[0] || []
  if (geom.type === 'MultiPolygon') return (geom.coordinates[0] || [[]])[0] || []
  return []
}

/**
 * Convertit une géométrie : reprojete vers WGS84, puis en mètres relatifs.
 * cx, cy = centroïde WGS84 (degrés) du circuit.
 */
function convertGeometry(geom, cx, cy) {
  const cosLat = Math.cos(cy * Math.PI / 180)
  const DEG_LAT_M = 111320  // mètres par degré latitude

  function convertPoint(coord) {
    const [lng, lat] = toWGS84(coord[0], coord[1])
    const dx = (lng - cx) * DEG_LAT_M * cosLat
    const dy = (lat - cy) * DEG_LAT_M
    return [dx, dy]
  }

  if (!geom) return geom
  switch (geom.type) {
    case 'Point':
      return { type: 'Point', coordinates: convertPoint(geom.coordinates) }
    case 'LineString':
      return { type: 'LineString', coordinates: geom.coordinates.map(convertPoint) }
    case 'Polygon':
      return { type: 'Polygon', coordinates: geom.coordinates.map(ring => ring.map(convertPoint)) }
    case 'MultiPolygon':
      return { type: 'MultiPolygon', coordinates: geom.coordinates.map(poly => poly.map(ring => ring.map(convertPoint))) }
    default:
      return geom
  }
}

readOcad(ocdPath)
  .then(ocadFile => {
    const geojson = ocadToGeoJson(ocadFile)

    if (!geojson || !geojson.features || geojson.features.length === 0) {
      process.stdout.write(JSON.stringify({ type: 'FeatureCollection', features: [] }))
      process.exit(0)
    }

    // Calculer le centroïde WGS84 de toutes les features
    let sumLng = 0, sumLat = 0, count = 0
    for (const feature of geojson.features) {
      for (const coord of flatCoords(feature.geometry)) {
        const [lng, lat] = toWGS84(coord[0], coord[1])
        sumLng += lng
        sumLat += lat
        count++
      }
    }
    const cx = count > 0 ? sumLng / count : 0
    const cy = count > 0 ? sumLat / count : 0

    // Convertir toutes les features : WGS84 → mètres relatifs centrés sur (0,0)
    const anonymized = {
      type: 'FeatureCollection',
      features: geojson.features.map(f => ({
        type: 'Feature',
        properties: { sym: f.properties.sym },  // Code ISOM uniquement
        geometry: convertGeometry(f.geometry, cx, cy)
      }))
    }

    process.stdout.write(JSON.stringify(anonymized))
    process.exit(0)
  })
  .catch(err => {
    process.stderr.write('Erreur lecture OCAD: ' + err.message + '\n')
    process.exit(1)
  })
