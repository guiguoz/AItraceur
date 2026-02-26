/**
 * mapContext.js — ISOM map summary for AI generation context.
 *
 * Reads the GeoJSON produced by ocad2geojson and builds a short
 * human-readable terrain description grouped by ISOM symbol category.
 * This description is sent to the AI so it can place controls on
 * meaningful features (path junctions, forest edges, etc.).
 */

// ISOM symbol → terrain category
const CATEGORIES = [
  { min: 101, max: 103, key: 'contour',       label: 'Courbes de niveau' },
  { min: 104, max: 106, key: 'depression',    label: 'Dépressions/creux' },
  { min: 107, max: 115, key: 'cliff',         label: 'Falaises/rochers' },
  { min: 201, max: 213, key: 'rock',          label: 'Rochers/pierriers' },
  { min: 301, max: 303, key: 'water_area',    label: "Plans d'eau" },
  { min: 304, max: 308, key: 'water_line',    label: "Cours d'eau" },
  { min: 401, max: 403, key: 'open',          label: 'Zones ouvertes' },
  { min: 406, max: 406, key: 'forest_slow',   label: 'Forêt lente' },
  { min: 408, max: 408, key: 'forest_med',    label: 'Forêt (marche rapide)' },
  { min: 410, max: 412, key: 'forest_dense',  label: 'Forêt dense/infranchissable' },
  { min: 501, max: 501, key: 'road',          label: 'Routes asphaltées' },
  { min: 502, max: 503, key: 'track',         label: 'Chemins larges/étroits' },
  { min: 504, max: 504, key: 'path',          label: 'Sentiers' },
  { min: 521, max: 526, key: 'built',         label: 'Bâtiments/murs' },
];

function getCat(sym) {
  // Normalize: handle integers, floats (401.0), strings
  const n = Math.floor(typeof sym === 'number' ? sym : parseFloat(sym));
  if (isNaN(n)) return null;
  // Also handle OCAD internal encoding ×1000 (e.g. 401000 → 401)
  const normalized = n > 10000 ? Math.floor(n / 1000) : n;
  return CATEGORIES.find(c => normalized >= c.min && normalized <= c.max) ?? null;
}

/**
 * Builds a short terrain description from OCAD GeoJSON for the AI prompt.
 * @param {object} geojson  FeatureCollection from ocad2geojson
 * @returns {string|null}   Multi-line terrain description, or null if no data
 */
export function buildMapContext(geojson) {
  if (!geojson?.features?.length) return null;

  // Count features per category
  const counts = {};
  for (const feat of geojson.features) {
    const sym = feat.properties?.sym ?? feat.properties?.symbol;
    const cat = getCat(sym);
    if (!cat) continue;
    counts[cat.key] = (counts[cat.key] ?? 0) + 1;
  }

  if (!Object.keys(counts).length) return null;

  // Compute approximate map dimensions from feature bbox
  let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
  const walk = (c) => {
    if (typeof c[0] === 'number') {
      if (c[0] < minLng) minLng = c[0]; if (c[0] > maxLng) maxLng = c[0];
      if (c[1] < minLat) minLat = c[1]; if (c[1] > maxLat) maxLat = c[1];
    } else c.forEach(walk);
  };
  geojson.features.forEach(f => f.geometry?.coordinates && walk(f.geometry.coordinates));

  const lines = [];

  if (isFinite(minLat)) {
    const latKm = ((maxLat - minLat) * 111).toFixed(1);
    const lngKm = ((maxLng - minLng) * 111 * Math.cos((minLat + maxLat) / 2 * Math.PI / 180)).toFixed(1);
    lines.push(`Zone cartographiée: ~${latKm} km × ${lngKm} km`);
  }

  // Paths & roads
  const paths = [];
  if (counts.road)  paths.push(`${counts.road} route(s) asphaltée(s)`);
  if (counts.track) paths.push(`${counts.track} chemin(s)`);
  if (counts.path)  paths.push(`${counts.path} sentier(s)`);
  if (paths.length) lines.push('Chemins/routes: ' + paths.join(', '));

  // Vegetation
  const veg = [];
  if (counts.open)          veg.push(`zones ouvertes (×${counts.open})`);
  if (counts.forest_slow)   veg.push(`forêt lente (×${counts.forest_slow})`);
  if (counts.forest_med)    veg.push(`forêt (marche rapide) (×${counts.forest_med})`);
  if (counts.forest_dense)  veg.push(`forêt dense/infranchissable (×${counts.forest_dense})`);
  if (veg.length) lines.push('Végétation: ' + veg.join(', '));

  // Water
  const water = [];
  if (counts.water_area) water.push(`${counts.water_area} plan(s) d'eau`);
  if (counts.water_line) water.push(`${counts.water_line} cours d'eau`);
  if (water.length) lines.push('Eau: ' + water.join(', '));

  // Relief
  const relief = [];
  if (counts.contour)    relief.push(`${counts.contour} courbes de niveau`);
  if (counts.depression) relief.push(`${counts.depression} dépression(s)`);
  if (counts.cliff)      relief.push(`${counts.cliff} falaise(s)`);
  if (counts.rock)       relief.push(`${counts.rock} rocher(s)/pierrier(s)`);
  if (relief.length) lines.push('Relief: ' + relief.join(', '));

  // Built
  if (counts.built) lines.push(`Constructions: ${counts.built} objet(s)`);

  return lines.length ? lines.join('\n') : null;
}
