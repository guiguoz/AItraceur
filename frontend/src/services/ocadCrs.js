/**
 * ocadCrs.js — OCAD CRS detection and reprojection to WGS84.
 *
 * ocad2geojson outputs coordinates in the map's projected CRS
 * (Lambert-93, UTM, etc.), NOT WGS84. This module registers
 * common European orienteering CRS definitions into proj4 and
 * reprojects any GeoJSON FeatureCollection to EPSG:4326 (WGS84).
 */

import proj4 from 'proj4';

// ── proj4 definitions for common European orienteering CRS ──────────────────
// proj4 already includes all WGS84 UTM zones (EPSG:32601-32760).
// The entries below cover national/regional CRS not included by default.

const EXTRA_DEFS = {
  // France — Lambert-93 (most common for modern French O-maps)
  'EPSG:2154':
    '+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=44 +lat_2=49 +x_0=700000 +y_0=6600000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs',

  // France — Lambert II étendu (older French O-maps)
  'EPSG:27572':
    '+proj=lcc +lat_1=45.8989188888889 +lat_2=47.6960144444444 +lat_0=46.8 +lon_0=0 +x_0=600000 +y_0=2200000 +ellps=clrk80ign +pm=paris +towgs84=-168,-60,320,0,0,0,0 +units=m +no_defs',

  // Switzerland — CH1903/LV03 (older Swiss maps)
  'EPSG:21781':
    '+proj=somerc +lat_0=46.9524055555556 +lon_0=7.43958333333333 +k_0=1 +x_0=600000 +y_0=200000 +ellps=bessel +towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs',

  // Switzerland — CH1903+/LV95 (newer Swiss maps)
  'EPSG:2056':
    '+proj=somerc +lat_0=46.9524055555556 +lon_0=7.43958333333333 +k_0=1 +x_0=2600000 +y_0=1200000 +ellps=bessel +towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs',

  // UK — OSGB 1936 / British National Grid
  'EPSG:27700':
    '+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 +ellps=airy +towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489 +units=m +no_defs',

  // Sweden — SWEREF99 TM
  'EPSG:3006':
    '+proj=utm +zone=33 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs',

  // Austria/Germany — MGI / Bundesmeldenetz M31 (Gauß-Krüger)
  'EPSG:31257':
    '+proj=tmerc +lat_0=0 +lon_0=10.3333333333333 +k=1 +x_0=150000 +y_0=-5000000 +ellps=bessel +towgs84=577.326,90.129,463.919,5.137,1.474,5.297,2.4232 +units=m +no_defs',
  'EPSG:31258':
    '+proj=tmerc +lat_0=0 +lon_0=13.3333333333333 +k=1 +x_0=450000 +y_0=-5000000 +ellps=bessel +towgs84=577.326,90.129,463.919,5.137,1.474,5.297,2.4232 +units=m +no_defs',
  'EPSG:31259':
    '+proj=tmerc +lat_0=0 +lon_0=16.3333333333333 +k=1 +x_0=750000 +y_0=-5000000 +ellps=bessel +towgs84=577.326,90.129,463.919,5.137,1.474,5.297,2.4232 +units=m +no_defs',

  // Finland — ETRS-TM35FIN (KKJ)
  'EPSG:3067':
    '+proj=utm +zone=35 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs',

  // Norway — UTM zone 32N (most common)
  // Already available as EPSG:32632 in proj4

  // Czech Republic / Slovakia — S-JTSK
  'EPSG:5514':
    '+proj=krovak +lat_0=49.5 +lon_0=24.8333333333333 +alpha=30.2881397527778 +k=0.9999 +x_0=0 +y_0=0 +ellps=bessel +towgs84=589,76,480,0,0,0,0 +units=m +no_defs',
};

// ETRS89 UTM variants → WGS84 UTM equivalents (sub-meter difference, fine for O-maps)
const ETRS89_TO_WGS84 = {
  'EPSG:25828': 'EPSG:32628',
  'EPSG:25829': 'EPSG:32629',
  'EPSG:25830': 'EPSG:32630',
  'EPSG:25831': 'EPSG:32631',
  'EPSG:25832': 'EPSG:32632',
  'EPSG:25833': 'EPSG:32633',
  'EPSG:25834': 'EPSG:32634',
  'EPSG:25835': 'EPSG:32635',
  'EPSG:25836': 'EPSG:32636',
  'EPSG:25837': 'EPSG:32637',
  'EPSG:25838': 'EPSG:32638',
};

// Register extra definitions (idempotent)
for (const [name, def] of Object.entries(EXTRA_DEFS)) {
  if (!proj4.defs[name]) proj4.defs(name, def);
}

// ── Coordinate walker ────────────────────────────────────────────────────────

/**
 * Recursively transforms all [x, y] pairs in a GeoJSON coordinate structure.
 * @param {Array} coords  GeoJSON coordinate array (any nesting depth)
 * @param {Function} fn   (x, y) → [lng, lat]
 * @returns {Array}       Transformed coordinate array
 */
function walkCoords(coords, fn) {
  if (typeof coords[0] === 'number') {
    return fn(coords[0], coords[1]);
  }
  return coords.map(c => walkCoords(c, fn));
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * Reprojects a GeoJSON FeatureCollection from the OCAD file's native CRS to WGS84.
 *
 * @param {object} geojson   FeatureCollection (output of ocad2geojson)
 * @param {object} crs       OcadFile.getCrs() result — must have `.code` (EPSG int)
 * @returns {{ geojson: object, crsInfo: string }}
 */
export function reprojectToWgs84(geojson, crs) {
  const code = crs?.code;

  // Already WGS84 or no CRS info
  if (!code || code === 4326) {
    return {
      geojson,
      crsInfo: code === 4326 ? 'WGS84 (EPSG:4326)' : 'Coordonnées locales (non géoréférencées)',
    };
  }

  let fromEpsg = `EPSG:${code}`;

  // Remap ETRS89 UTM → WGS84 UTM (equivalent for O-mapping)
  if (ETRS89_TO_WGS84[fromEpsg]) {
    fromEpsg = ETRS89_TO_WGS84[fromEpsg];
  }

  if (!proj4.defs[fromEpsg]) {
    console.warn(`[OCAD CRS] Projection non supportée: ${fromEpsg} — carte affichée sans géoréférencement.`);
    return {
      geojson,
      crsInfo: `Non supporté: ${fromEpsg}`,
    };
  }

  const transform = proj4(fromEpsg, 'EPSG:4326');
  const fn = (x, y) => transform.forward([x, y]);

  const reprojected = {
    ...geojson,
    features: geojson.features.map(feat => {
      if (!feat.geometry?.coordinates) return feat;
      return {
        ...feat,
        geometry: {
          ...feat.geometry,
          coordinates: walkCoords(feat.geometry.coordinates, fn),
        },
      };
    }),
  };

  const crsName = crs.name || fromEpsg;
  console.log(`[OCAD CRS] ${fromEpsg} → WGS84 (${geojson.features.length} features reprojectées)`);

  return {
    geojson: reprojected,
    crsInfo: `${crsName} (EPSG:${code}) → WGS84`,
  };
}
