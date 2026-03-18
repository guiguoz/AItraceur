import { useState, useRef } from 'react'
import { MapViewer } from './components/MapViewer'
import OcadUploader from './components/OcadUploader'
import ControlsList from './components/ControlsList'
import TerrainPanel from './components/TerrainPanel'
import CircuitCreationModal from './components/CircuitCreationModal'
import CircuitSelector from './components/CircuitSelector'
import AISuggestionPanel from './components/AISuggestionPanel'
import { generateCircuit, getSprintCandidates, generateSprint, uploadOcdForRender, TILE_SERVICE_URL, getRoutesBetweenControls, analyzeOcadGeojson } from './services/api'
import DialogueLog from './components/DialogueLog'
import { buildMapContext } from './services/mapContext'
import { OcadAnalysisPanel } from './components/OcadAnalysisPanel'

// IOF/FFCO reference params — auto-computed per circuit type/sex/category
const CIRCUIT_BASE_PARAMS = {
  sprint: { target_length_m: 2200, winning_time_minutes: 12, technical_level: 'TD3', target_controls: 12 },
  md:     { target_length_m: 8000, winning_time_minutes: 30, technical_level: 'TD4', target_controls: 18 },
  ld:     { target_length_m: 14000, winning_time_minutes: 60, technical_level: 'TD4', target_controls: 25 },
}
const COLOR_PARAMS = {
  Jaune:  { target_length_m: 1500, technical_level: 'TD1', target_controls: 8 },
  Orange: { target_length_m: 2000, technical_level: 'TD2', target_controls: 10 },
  Vert:   { target_length_m: 2500, technical_level: 'TD2', target_controls: 10 },
  Bleu:   { target_length_m: 3500, technical_level: 'TD3', target_controls: 12 },
  Violet: { target_length_m: 5000, technical_level: 'TD4', target_controls: 15 },
  Noir:   { target_length_m: 7000, technical_level: 'TD5', target_controls: 20 },
}
const AGE_FACTOR = {
  '10': 0.38, '12': 0.48, '14': 0.62, '16': 0.78, '18': 0.88,
  '20': 0.93, '21': 0.97, '21E': 1.0,
  '35': 0.88, '40': 0.82, '45': 0.76, '50': 0.70, '55': 0.65,
  '60': 0.60, '65': 0.54, '70': 0.48, '75': 0.44, '80': 0.40,
}

function getCircuitParams(circuit) {
  if (circuit.type === 'couleur') {
    return { ...(COLOR_PARAMS[circuit.color] ?? COLOR_PARAMS.Vert), category: 'Couleur' }
  }
  const base = CIRCUIT_BASE_PARAMS[circuit.type] ?? CIRCUIT_BASE_PARAMS.md
  const ageFactor = AGE_FACTOR[circuit.category] ?? 1.0
  const sexFactor = circuit.sex === 'D' ? 0.78 : 1.0
  const factor = ageFactor * sexFactor
  return {
    ...base,
    target_length_m: Math.round(base.target_length_m * factor / 100) * 100,
    winning_time_minutes: Math.round(base.winning_time_minutes * factor),
    target_controls: Math.max(5, Math.round(base.target_controls * factor)),
    category: `${circuit.sex}${circuit.category}`,
  }
}

function haversineDistance(p, q) {
  const R = 6371000
  const dLat = (q.lat - p.lat) * Math.PI / 180
  const dLng = (q.lng - p.lng) * Math.PI / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(p.lat * Math.PI / 180) * Math.cos(q.lat * Math.PI / 180) *
    Math.sin(dLng / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function computeCourseDistance(controls) {
  const ordered = [...controls]
    .filter(c => ['start', 'control', 'finish'].includes(c.type))
    .sort((a, b) => a.order - b.order)
  if (ordered.length < 2) return 0
  let total = 0
  for (let i = 1; i < ordered.length; i++) total += haversineDistance(ordered[i - 1], ordered[i])
  return Math.round(total)
}

// Collect all GeoJSON vertices in [lat, lng] format for coverage check
function buildOcadVertices(geojson) {
  const pts = []
  const walk = (coords) => {
    if (typeof coords[0] === 'number') pts.push([coords[1], coords[0]])
    else coords.forEach(walk)
  }
  geojson.features.forEach(f => f.geometry?.coordinates && walk(f.geometry.coordinates))
  return pts
}

// Returns true if [lat, lng] is within thresholdM of at least one GeoJSON vertex
function isOnOcadMap(lat, lng, ocadVertices, thresholdM = 45) {
  if (!ocadVertices || ocadVertices.length === 0) return true
  const latRad = lat * Math.PI / 180
  const thr2 = thresholdM / 111320  // rough degrees threshold for quick pre-filter
  for (const [vlat, vlng] of ocadVertices) {
    if (Math.abs(vlat - lat) > thr2 || Math.abs(vlng - lng) > thr2 * Math.cos(latRad)) continue
    const d = haversineDistance({ lat, lng }, { lat: vlat, lng: vlng })
    if (d <= thresholdM) return true
  }
  return false
}

function extractBoundingBox(geojson) {
  const xs = [], ys = []
  const walk = (coords) => {
    if (typeof coords[0] === 'number') { xs.push(coords[0]); ys.push(coords[1]) }
    else coords.forEach(walk)
  }
  geojson.features.forEach(f => f.geometry?.coordinates && walk(f.geometry.coordinates))
  if (xs.length === 0) return { min_x: -180, min_y: -90, max_x: 180, max_y: 90 }
  xs.sort((a, b) => a - b); ys.sort((a, b) => a - b)
  const p = (arr, pct) => arr[Math.max(0, Math.min(arr.length - 1, Math.floor(arr.length * pct)))]
  return { min_x: p(xs, 0.01), min_y: p(ys, 0.01), max_x: p(xs, 0.99), max_y: p(ys, 0.99) }
}

// ISOM codes with notable orienteering control attractiveness (forest maps, ISOM 2017)
// Source: backend/src/data/ocad_semantics.json (high/medium attractiveness)
const ATTRACTIVE_ISOM = new Set([
  101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,
  201,202,203,204,205,206,209,210,211,212,215,
  301,302,303,304,305,306,308,
  401,402,403,404,405,406,
  501,502,516,521,522,
])

// ISSOM codes for sprint maps (urban — ISSOM 2017)
// Postes sprint : coins de bâtiments, carrefours, passages, fontaines, clôtures
const ATTRACTIVE_ISSOM = new Set([
  401, 402, 403, 404, 405,  // Intersections, carrefours, embranchements, coudes, extrémités
  501, 521, 522,             // Angle de bâtiment, angle de zone construite, angle de zone pavée
  529,                       // Carrefour de chemins pavés / passage entre bâtiments
  209,                       // Fontaine / source
  516,                       // Angle de clôture / haie
])

// ISOM codes representing out-of-bounds / forbidden areas (olive green, cross-hatched…)
// ISOM 2017: 520=OOB, 709=do-not-enter, 714=dangerous area
// ISSOM 2007/2019: 520=OOB, 526=OOB passage, 709=do-not-enter
// Also 521/522/527/528 = buildings — excluded from candidates separately
const OOB_ISOM = new Set([520, 526, 709, 714, 715])

// Ray-casting point-in-polygon test (WGS84 coords, [lng, lat] ring)
function pointInPolygon(lng, lat, ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1]
    const xj = ring[j][0], yj = ring[j][1]
    if (((yi > lat) !== (yj > lat)) && (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi)) {
      inside = !inside
    }
  }
  return inside
}

function computeGeoCentroid(geometry) {
  if (!geometry) return null
  const coords =
    geometry.type === 'Point'      ? [geometry.coordinates] :
    geometry.type === 'LineString' ? geometry.coordinates :
    geometry.type === 'Polygon'    ? geometry.coordinates[0] : null
  if (!coords?.length) return null
  return [
    coords.reduce((s, c) => s + c[0], 0) / coords.length,
    coords.reduce((s, c) => s + c[1], 0) / coords.length,
  ]
}

// Extract out-of-bounds polygon areas from OCAD GeoJSON.
// Returns list of coordinate rings [[lng, lat], ...] matching the backend's
// forbidden_zones format (GeoJSON WGS84, x=lng / y=lat).
function extractOobZones(geojson) {
  const zones = []
  for (const f of geojson.features) {
    const sym = f.properties?.sym
    if (!sym) continue
    const isom = Math.floor(sym / 1000)
    if (!OOB_ISOM.has(isom)) continue
    const geom = f.geometry
    if (!geom) continue
    if (geom.type === 'Polygon') {
      zones.push(geom.coordinates[0])
    } else if (geom.type === 'MultiPolygon') {
      for (const poly of geom.coordinates) zones.push(poly[0])
    }
  }
  return zones
}

// Compute angle (degrees) at vertex B between segments A→B and B→C
function computeAngleDeg(a, b, c) {
  const v1 = [a[0] - b[0], a[1] - b[1]]
  const v2 = [c[0] - b[0], c[1] - b[1]]
  const dot = v1[0]*v2[0] + v1[1]*v2[1]
  const mag = Math.sqrt((v1[0]**2+v1[1]**2) * (v2[0]**2+v2[1]**2))
  if (mag === 0) return 180
  return (Math.acos(Math.max(-1, Math.min(1, dot/mag))) * 180) / Math.PI
}

// Deduplicate points closer than ~threshDeg degrees (≈15m at ~0.000135°/m)
function deduplicatePoints(pts, threshDeg = 0.000135) {
  const out = []
  for (const p of pts) {
    const near = out.some(q => Math.abs(q.x - p.x) < threshDeg && Math.abs(q.y - p.y) < threshDeg)
    if (!near) out.push(p)
  }
  return out
}

// Building polygon ISOM codes — extract corners instead of centroid
const BUILDING_ISOM = new Set([521, 522, 527, 528])
// Path/road LineString ISOM codes — extract direction-change vertices + intersections
const PATH_ISOM = new Set([501, 502, 503, 504, 505, 506])
// Sprint equivalents
const BUILDING_ISSOM = new Set([521, 522, 529])
const PATH_ISSOM = new Set([401, 402, 403, 404, 405])

// Compute parametric intersection of segments P1-P2 and P3-P4.
// Returns [lng, lat] if they cross, null otherwise.
function segmentIntersect(p1, p2, p3, p4) {
  const dx12 = p2[0] - p1[0], dy12 = p2[1] - p1[1]
  const dx34 = p4[0] - p3[0], dy34 = p4[1] - p3[1]
  const denom = dy34 * dx12 - dx34 * dy12
  if (Math.abs(denom) < 1e-12) return null // parallel / collinear
  const dx13 = p1[0] - p3[0], dy13 = p1[1] - p3[1]
  const t = (dx34 * dy13 - dy34 * dx13) / denom
  const u = (dx12 * dy13 - dy12 * dx13) / denom
  if (t > 0 && t < 1 && u > 0 && u < 1) {
    return [p1[0] + t * dx12, p1[1] + t * dy12]
  }
  return null
}

// Find geometric intersections between pairs of path LineStrings (carrefours).
// Limited to maxFeatures to keep computation fast in the browser.
function findPathIntersections(lines, isom, maxFeatures = 200) {
  const pts = []
  const n = Math.min(lines.length, maxFeatures)
  for (let i = 0; i < n; i++) {
    const a = lines[i]
    for (let j = i + 1; j < n; j++) {
      const b = lines[j]
      for (let ai = 0; ai < a.length - 1; ai++) {
        for (let bi = 0; bi < b.length - 1; bi++) {
          const pt = segmentIntersect(a[ai], a[ai+1], b[bi], b[bi+1])
          if (pt) pts.push({ x: pt[0], y: pt[1], isom, _intersection: true })
        }
      }
    }
  }
  return pts
}

function extractCandidatePoints(geojson, max = 600, sprintMode = false) {
  const attractiveCodes = sprintMode ? ATTRACTIVE_ISSOM : ATTRACTIVE_ISOM
  const buildingCodes = sprintMode ? BUILDING_ISSOM : BUILDING_ISOM
  const pathCodes = sprintMode ? PATH_ISSOM : PATH_ISOM

  const pts = []
  const pathLines = [] // LineString coords collected for intersection computation

  for (const f of geojson.features) {
    const sym = f.properties?.sym
    if (!sym) continue
    const isom = Math.floor(sym / 1000)
    if (!attractiveCodes.has(isom)) continue
    const geom = f.geometry
    if (!geom) continue

    if (geom.type === 'Point') {
      pts.push({ x: geom.coordinates[0], y: geom.coordinates[1], isom })

    } else if (geom.type === 'Polygon' && buildingCodes.has(isom)) {
      // Building corners — all polygon vertices
      const ring = geom.coordinates[0]
      for (let i = 0; i < ring.length - 1; i++) {
        pts.push({ x: ring[i][0], y: ring[i][1], isom })
      }

    } else if (geom.type === 'LineString' && pathCodes.has(isom)) {
      const coords = geom.coordinates
      pathLines.push({ coords, isom })

      // Direction-change vertices (sharp turn)
      for (let i = 1; i < coords.length - 1; i++) {
        const angle = computeAngleDeg(coords[i-1], coords[i], coords[i+1])
        if (angle < 150) {
          pts.push({ x: coords[i][0], y: coords[i][1], isom })
        }
      }
      // Endpoints (potential T-junctions, dead-ends)
      pts.push({ x: coords[0][0], y: coords[0][1], isom })
      pts.push({ x: coords[coords.length-1][0], y: coords[coords.length-1][1], isom })

    } else {
      const c = computeGeoCentroid(geom)
      if (c) pts.push({ x: c[0], y: c[1], isom })
    }
  }

  // Compute geometric intersections between path pairs (true carrefours)
  // Intersections go first — highest-priority sprint controls
  if (pathLines.length >= 2) {
    const intersectionIsom = pathLines[0]?.isom || (sprintMode ? 401 : 501)
    const lineCoords = pathLines.map(l => l.coords)
    const crossings = findPathIntersections(lineCoords, intersectionIsom)
    // Prepend so intersections survive the final slice(0, max)
    pts.unshift(...crossings)
    console.log(`[extractCandidatePoints] ${crossings.length} intersections géométriques trouvées sur ${pathLines.length} lignes`)
  }

  // Deduplicate (15m threshold) then shuffle non-intersection points
  const intersections = pts.filter(p => p._intersection)
  const rest = pts.filter(p => !p._intersection)
  const dedupRest = deduplicatePoints(rest)
  for (let i = dedupRest.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [dedupRest[i], dedupRest[j]] = [dedupRest[j], dedupRest[i]]
  }
  const dedupAll = deduplicatePoints([...intersections, ...dedupRest])
  return dedupAll.slice(0, max)
}

const tools = [
  { id: 'view', icon: '🖐️', label: 'Déplacer' },
  { id: 'start', icon: '🔺', label: 'Départ' },
  { id: 'control', icon: '⭕', label: 'Poste' },
  { id: 'finish', icon: '🎯', label: 'Arrivée' },
  { id: 'forbidden', icon: '🛑', label: 'Zone Interdite' },
]

const STEPS = ['Carte', 'Circuit', 'Traçage', 'Export']

function App() {
  const [ocadData, setOcadData] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeTool, setActiveTool] = useState('view')
  const [imageData, setImageData] = useState(null)
  const [mapMode, setMapMode] = useState('osm') // 'osm' | 'ocad'
  const [ocadAnalysis, setOcadAnalysis] = useState(null)
  const [renderLoading, setRenderLoading] = useState(false)
  const [terrainData, setTerrainData] = useState(null)
  const [showRunnability, setShowRunnability] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationError, setGenerationError] = useState(null)
  const [dialogue, setDialogue] = useState([])
  const [controleurReport, setControleurReport] = useState(null)
  const [progressLabel, setProgressLabel] = useState('')
  const [routeDisplay, setRouteDisplay] = useState(null) // { legIdx, routes }
  const [lastBbox, setLastBbox] = useState(null) // bbox du dernier appel de génération

  // Leaflet map ref — used for viewport bbox when no OCAD loaded
  const mapRef = useRef(null)

  // Multi-circuit state
  const [circuits, setCircuits] = useState([])
  const [activeCircuitId, setActiveCircuitId] = useState(null)
  const [showCreationForm, setShowCreationForm] = useState(false)

  // Competition mode
  const [competitionMode, setCompetitionMode] = useState(false)
  const [competitionName, setCompetitionName] = useState('')

  const getAllExistingControls = () =>
    circuits
      .filter(c => c.id !== activeCircuitId)
      .flatMap(c => (c.controls || []).map(ctrl => ({ ...ctrl, circuitName: c.name })))

  // Derived active circuit
  const activeCircuit = circuits.find(c => c.id === activeCircuitId) ?? null

  // Helper: update only the active circuit
  const updateActiveCircuit = (updater) => {
    setCircuits(prev => prev.map(c =>
      c.id === activeCircuitId
        ? { ...c, ...(typeof updater === 'function' ? updater(c) : updater) }
        : c
    ))
  }

  // ── Map loading ──────────────────────────────────────────────────────────────

  const handleOcadLoaded = (data) => {
    setOcadData(data)
    setError(null)
    setCircuits([])
    setActiveCircuitId(null)
    setImageData(null)
    setMapMode('osm')
    setOcadAnalysis(null)

    if (data.rawFile) {
      setRenderLoading(true)
      uploadOcdForRender(data.rawFile)
        .then((res) => {
          const { imageUrl, bounds } = res.data
          if (imageUrl && bounds?.southWest && bounds?.northEast) {
            setImageData({
              url: `${TILE_SERVICE_URL}${imageUrl}`,
              bounds: [
                [bounds.southWest[0], bounds.southWest[1]],
                [bounds.northEast[0], bounds.northEast[1]],
              ],
            })
            setMapMode('ocad')
          }
        })
        .catch(err => console.warn('[Render] Service unavailable:', err.message))
        .finally(() => setRenderLoading(false))
    }

    // Analyse OCAD côté backend (13c)
    if (data.geojson) {
      analyzeOcadGeojson(data.geojson)
        .then(res => setOcadAnalysis(res.data))
        .catch(err => console.warn('[OCAD analyze]', err.message))
    }
  }

  const handleError = (errMsg) => {
    setError(errMsg)
    setIsLoading(false)
  }

  // ── Circuit management ───────────────────────────────────────────────────────

  const handleCreateCircuit = (def) => {
    const circuit = {
      id: crypto.randomUUID(),
      ...def,
      controls: [],
      forbiddenZones: [],
      status: 'setup',
      aiSuggestions: [],
      suggestionIdx: 0,
    }
    setCircuits(prev => [...prev, circuit])
    setActiveCircuitId(circuit.id)
    setShowCreationForm(false)
    setActiveTool('start')
  }

  const handleDeleteCircuit = (id) => {
    setCircuits(prev => {
      const remaining = prev.filter(c => c.id !== id)
      if (id === activeCircuitId) {
        setActiveCircuitId(remaining[remaining.length - 1]?.id ?? null)
      }
      return remaining
    })
  }

  // ── Controls placement ───────────────────────────────────────────────────────

  const handleMapClick = (latlng) => {
    if (activeTool === 'view' || activeTool === 'forbidden' || !activeCircuit) return
    if (activeCircuit.status === 'ai_suggesting') return

    updateActiveCircuit(c => {
      const controls = [
        ...c.controls,
        {
          id: Date.now().toString(),
          type: activeTool,
          lat: latlng.lat,
          lng: latlng.lng,
          order: c.controls.length + 1,
        },
      ]
      return { controls }
    })
    if (activeTool === 'start') setActiveTool('control')
  }

  const handleDeleteControl = (controlId) => {
    updateActiveCircuit(c => {
      const filtered = c.controls.filter(ctrl => ctrl.id !== controlId)
      return { controls: filtered.map((ctrl, i) => ({ ...ctrl, order: i + 1 })) }
    })
  }

  // ── Forbidden zones ──────────────────────────────────────────────────────────

  const handleAddForbiddenZone = (polygon) => {
    if (!activeCircuit || polygon.length < 3) return
    updateActiveCircuit(c => ({ forbiddenZones: [...c.forbiddenZones, polygon] }))
  }

  // ── AI suggestion workflow ───────────────────────────────────────────────────

  const handleAiGenerate = async () => {
    if (isGenerating || !activeCircuit) return
    setIsGenerating(true)
    setGenerationError(null)
    setDialogue([])
    setControleurReport(null)
    setProgressLabel('Génération initiale…')
    try {
      // Priority: tile service bounds > OCAD GeoJSON bounds > Leaflet viewport
      let bbox
      if (imageData?.bounds) {
        const [[southLat, westLng], [northLat, eastLng]] = imageData.bounds
        bbox = { min_x: westLng, min_y: southLat, max_x: eastLng, max_y: northLat }
      } else if (ocadData?.geojson) {
        bbox = extractBoundingBox(ocadData.geojson)
        if (Math.abs(bbox.min_x) > 180 || Math.abs(bbox.max_x) > 180 ||
            Math.abs(bbox.min_y) > 90  || Math.abs(bbox.max_y) > 90) {
          throw new Error(
            'La carte n\'est pas géoréférencée en WGS84. ' +
            'Démarrez le service de tuiles (port 8089) et rechargez la carte.'
          )
        }
      } else {
        // No OCAD — use current Leaflet viewport
        const bounds = mapRef.current?.getBounds()
        if (!bounds) throw new Error('Zoomez sur la zone à tracer avant de générer.')
        bbox = { min_x: bounds.getWest(), min_y: bounds.getSouth(),
                 max_x: bounds.getEast(), max_y: bounds.getNorth() }
      }
      console.log('[AI Generate] bbox WGS84:', bbox)
      setLastBbox(bbox)
      const circuitParams = getCircuitParams(activeCircuit)
      const startControl = activeCircuit.controls.find(c => c.type === 'start')
      const mapContext = ocadData?.geojson ? buildMapContext(ocadData.geojson) : null
      const isSprintCircuit = activeCircuit.type === 'sprint'

      // OOB zones first — needed to filter candidates
      const ocadOobZones = ocadData?.geojson ? extractOobZones(ocadData.geojson) : []
      const oobZones = [...activeCircuit.forbiddenZones, ...ocadOobZones]

      // Candidats OCAD si disponibles, sinon vide (OSM auto-enrichment côté serveur)
      let candidatePoints = ocadData?.geojson
        ? extractCandidatePoints(ocadData.geojson, 600, isSprintCircuit)
        : []
      if (ocadData?.geojson) {
        const margin = 0.02
        const beforeFilter = candidatePoints.length
        candidatePoints = candidatePoints.filter(cp => {
          // Exclude candidates outside bbox
          if (cp.x < bbox.min_x - margin || cp.x > bbox.max_x + margin ||
              cp.y < bbox.min_y - margin || cp.y > bbox.max_y + margin) return false
          // Exclude candidates inside OOB zones (propriété privée, hors-limites)
          if (oobZones.some(ring => pointInPolygon(cp.x, cp.y, ring))) return false
          return true
        })
        console.log(`[AI Generate] Candidats: ${beforeFilter} → ${candidatePoints.length} après filtrage OOB (${oobZones.length} zones)`)
      }

      // Sprint avec peu de candidats : pré-charger OSM (le serveur le fait aussi si <50)
      if (isSprintCircuit && candidatePoints.length < 30) {
        try {
          const sprintRes = await getSprintCandidates(bbox)
          const osmData = sprintRes.data
          const osmCandidates = (osmData.candidates || []).filter(
            cp => !oobZones.some(ring => pointInPolygon(cp.x, cp.y, ring))
          )
          candidatePoints = [...candidatePoints, ...osmCandidates]
          // Les bâtiments OSM = OOB supplémentaires
          for (const poly of (osmData.oob_polygons || [])) oobZones.push(poly)
          console.log(`[AI Generate] Sprint OSM: ${osmData.candidates?.length} candidats OSM (${osmData.candidates?.length - osmCandidates.length} exclus OOB)`)
        } catch (err) {
          console.warn('[AI Generate] Sprint OSM candidates failed (non bloquant):', err.message)
        }
      }

      console.log(`[AI Generate] ${isSprintCircuit ? 'SPRINT' : 'FORET'} — ${candidatePoints.length} candidats, bbox:`, bbox)

      const params = {
        bounding_box: bbox,
        method: 'genetic',
        num_variants: 1,
        circuit_type: activeCircuit.type,
        ...circuitParams,
        target_controls: Math.ceil((circuitParams.target_controls ?? 12) * 1.5),
        ...(mapContext && { map_context: mapContext }),
        ...(startControl && { start_position: [startControl.lng, startControl.lat] }),
        // Forbidden zones: user-drawn + OCAD OOB + bâtiments OSM (sprint)
        forbidden_zones_polygons: oobZones,
        // Pass already-placed mandatory controls
        required_controls: activeCircuit.controls
          .filter(c => c.type === 'control')
          .map(c => ({ lat: c.lat, lng: c.lng })),
        // OCAD/OSM feature candidates for terrain-aware placement
        candidate_points: candidatePoints.slice(0, 600),
      }

      let controls
      if (isSprintCircuit) {
        setProgressLabel('Dialogue traceur↔contrôleur…')
        const sprintParams = {
          bounding_box: bbox,
          ...circuitParams,
          ...(startControl && { start_position: [startControl.lng, startControl.lat] }),
          forbidden_zones_polygons: oobZones,
          candidate_points: candidatePoints.slice(0, 600),
          existing_controls: competitionMode
            ? getAllExistingControls().map(c => ({ lat: c.lat, lng: c.lng, circuitName: c.circuitName }))
            : [],
        }
        const res = await generateSprint(sprintParams)
        const data = res.data
        console.log('[Generate Sprint] response:', data)
        if (data.dialogue?.length) setDialogue(data.dialogue)
        if (data.controleur_report) setControleurReport(data.controleur_report)
        if (!data.controls?.length) throw new Error('Aucun circuit généré')
        controls = data.controls
      } else {
        const res = await generateCircuit(params)
        console.log('[AI Generate] response:', res.data)
        const best = res.data?.circuits?.[0]
        console.log('[AI Generate] best circuit:', best)
        if (!best?.controls?.length) throw new Error('Aucun circuit généré')
        controls = best.controls
      }

      const hasStart = activeCircuit.controls.some(c => c.type === 'start')
      const hasFinish = activeCircuit.controls.some(c => c.type === 'finish')

      const inBbox = (s) => {
        if (!bbox) return true
        return s.lat >= bbox.min_y && s.lat <= bbox.max_y &&
               s.lng >= bbox.min_x && s.lng <= bbox.max_x
      }
      // Build OCAD vertex list once for coverage check (zones blanches filter)
      const ocadVertices = ocadData?.geojson ? buildOcadVertices(ocadData.geojson) : null

      const suggestions = controls
        .map((c, idx) => ({
          id: `ai_${Date.now()}_${idx}`,
          type: c.type || (idx === 0 ? 'start' : 'control'),
          lat: c.y ?? c.lat,
          lng: c.x ?? c.lng,
          order: c.order ?? idx + 1,
          description: c.description || '',
          reused: c.reused ?? false,
        }))
        .filter(s => !(s.type === 'start' && hasStart) && !(s.type === 'finish' && hasFinish))
        .filter(s => s.type === 'start' || s.type === 'finish' || inBbox(s))
        .filter(s => s.type === 'start' || s.type === 'finish' || isOnOcadMap(s.lat, s.lng, ocadVertices))

      console.log('[AI Generate] suggestions:', suggestions)
      updateActiveCircuit({ aiSuggestions: suggestions, suggestionIdx: 0, status: 'ai_suggesting' })
    } catch (err) {
      const detail = err.response?.data?.detail
      setGenerationError(
        typeof detail === 'string' ? detail :
        Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join(' | ') :
        err.message || 'Erreur génération IA'
      )
    } finally {
      setIsGenerating(false)
    }
  }

  const handleValidateSuggestion = () => {
    updateActiveCircuit(c => {
      const suggestion = c.aiSuggestions[c.suggestionIdx]
      if (!suggestion) return { status: 'complete' }
      const newControl = { ...suggestion, order: c.controls.length + 1 }
      const controls = [...c.controls, newControl].map((ctrl, i) => ({ ...ctrl, order: i + 1 }))
      const newIdx = c.suggestionIdx + 1
      const targetLength = getCircuitParams(c).target_length_m
      // Projeter la distance avec l'arrivée (déjà posée ou dans les suggestions restantes)
      const hasFinish = controls.some(ctrl => ctrl.type === 'finish')
      let projected = controls
      if (!hasFinish) {
        const finishAhead = c.aiSuggestions.slice(newIdx).find(s => s.type === 'finish')
        if (finishAhead) projected = [...controls, { ...finishAhead, order: controls.length + 1 }]
      }
      const distOk = computeCourseDistance(projected) >= targetLength * 0.9
      const exhausted = newIdx >= c.aiSuggestions.length
      const status = distOk ? 'complete' : exhausted ? 'needs_completion' : 'ai_suggesting'
      // Auto-ajouter le finish aux controls quand le circuit est complet
      let finalControls = controls
      if (status === 'complete' && !hasFinish) {
        const finishToAdd = c.aiSuggestions.slice(newIdx).find(s => s.type === 'finish')
        if (finishToAdd) {
          finalControls = [...controls, { ...finishToAdd, order: controls.length + 1 }]
            .map((ctrl, i) => ({ ...ctrl, order: i + 1 }))
        }
      }
      return { controls: finalControls, suggestionIdx: newIdx, status }
    })
  }

  const handleSkipSuggestion = () => {
    updateActiveCircuit(c => {
      const newIdx = c.suggestionIdx + 1
      const targetLength = getCircuitParams(c).target_length_m
      const exhausted = newIdx >= c.aiSuggestions.length
      if (!exhausted) return { suggestionIdx: newIdx, status: 'ai_suggesting' }
      const distOk = computeCourseDistance(c.controls) >= targetLength * 0.9
      const status = distOk ? 'complete' : 'needs_completion'
      // Auto-ajouter le finish si circuit complet
      let finalControls = c.controls
      if (status === 'complete' && !c.controls.some(ctrl => ctrl.type === 'finish')) {
        const finishToAdd = c.aiSuggestions.slice(newIdx).find(s => s.type === 'finish')
        if (finishToAdd) {
          finalControls = [...c.controls, { ...finishToAdd, order: c.controls.length + 1 }]
            .map((ctrl, i) => ({ ...ctrl, order: i + 1 }))
        }
      }
      return { controls: finalControls, suggestionIdx: newIdx, status }
    })
  }

  const handleCompleteCircuit = async () => {
    if (!activeCircuit || isGenerating) return
    const circuitParams = getCircuitParams(activeCircuit)
    const placed = activeCircuit.controls.filter(c => c.type === 'control')
    const missing = Math.max(2, circuitParams.target_controls - placed.length)
    const isSprintCircuit = activeCircuit.type === 'sprint'
    const bbox = lastBbox
    setIsGenerating(true)
    setProgressLabel('Complétion du circuit…')
    try {
      let newControls
      if (isSprintCircuit) {
        const res = await generateSprint({
          bounding_box: bbox,
          ...circuitParams,
          target_controls: Math.ceil(missing * 1.5),
          existing_controls: activeCircuit.controls.map(c => ({ lat: c.lat, lng: c.lng, circuitName: 'current' })),
          forbidden_zones_polygons: activeCircuit.forbiddenZones ?? [],
        })
        newControls = res.data?.controls ?? []
      } else {
        const res = await generateCircuit({
          bounding_box: bbox,
          ...circuitParams,
          target_controls: Math.ceil(missing * 1.5),
          required_controls: placed.map(c => ({ lat: c.lat, lng: c.lng })),
        })
        newControls = res.data?.circuits?.[0]?.controls ?? []
      }
      const hasFinish = activeCircuit.controls.some(c => c.type === 'finish')
      const inBbox = (s) => !bbox || (s.lat >= bbox.min_y && s.lat <= bbox.max_y && s.lng >= bbox.min_x && s.lng <= bbox.max_x)
      const newSuggestions = newControls
        .map((c, idx) => ({
          id: `ai_${Date.now()}_${idx}`,
          type: c.type || 'control',
          lat: c.y ?? c.lat,
          lng: c.x ?? c.lng,
          order: idx + 1,
          description: c.description || '',
        }))
        .filter(s => s.type !== 'start')
        .filter(s => !(s.type === 'finish' && hasFinish))
        .filter(s => s.type === 'finish' || inBbox(s))
      updateActiveCircuit(c => ({
        aiSuggestions: [...(c.aiSuggestions || []), ...newSuggestions],
        suggestionIdx: c.aiSuggestions?.length ?? 0,
        status: newSuggestions.length > 0 ? 'ai_suggesting' : 'complete',
      }))
    } catch (err) {
      console.error('[Complétion] Erreur:', err.message)
    } finally {
      setIsGenerating(false)
    }
  }

  const handleUpdateSuggestion = ({ lat, lng }) => {
    updateActiveCircuit(c => {
      const suggestions = [...c.aiSuggestions]
      suggestions[c.suggestionIdx] = { ...suggestions[c.suggestionIdx], lat, lng }
      return { aiSuggestions: suggestions }
    })
  }

  // ── Route Analyzer (Étape 10f) ───────────────────────────────────────────────

  const handleShowRoutes = async (legIdx, controlA, controlB) => {
    // Toggle off if same leg
    if (routeDisplay?.legIdx === legIdx) {
      setRouteDisplay(null)
      return
    }
    try {
      const res = await getRoutesBetweenControls({
        from: { lat: controlA.lat, lng: controlA.lng },
        to: { lat: controlB.lat, lng: controlB.lng },
        k: 3,
      })
      setRouteDisplay({ legIdx, routes: res.data.routes, diversityScore: res.data.diversity_score })
    } catch (e) {
      console.error('[RouteAnalyzer]', e)
    }
  }

  // ── IOF XML export ───────────────────────────────────────────────────────────

  const handleExportIOF = () => {
    if (!activeCircuit?.controls?.length) return
    const ordered = [...activeCircuit.controls]
      .filter(c => ['start', 'control', 'finish'].includes(c.type))
      .sort((a, b) => a.order - b.order)

    const now = new Date().toISOString()
    const date = now.split('T')[0]
    const courseName = activeCircuit.name

    let xml = `<?xml version="1.0" encoding="UTF-8"?>\n`
    xml += `<CourseData xmlns="http://www.orienteering.org/datastandard/3.0" iofVersion="3.0" createTime="${now}" creator="AItraceur">\n`
    xml += `  <Event><Name>${ocadData?.fileName || 'AItraceur'}</Name><StartTime><Date>${date}</Date></StartTime></Event>\n`
    xml += `  <RaceCourseData>\n`
    ordered.forEach((c, i) => {
      const ctrlId = c.type === 'start' ? 'S' : c.type === 'finish' ? 'F' : String(30 + i)
      xml += `    <Control><Id>${ctrlId}</Id><Position lat="${c.lat}" lng="${c.lng}"/></Control>\n`
    })
    xml += `    <Course>\n`
    xml += `      <Name>${courseName}</Name>\n`
    xml += `      <Length>${computeCourseDistance(activeCircuit.controls)}</Length>\n`
    xml += `      <Climb>0</Climb>\n`
    ordered.forEach((c, i) => {
      const ctrlId = c.type === 'start' ? 'S' : c.type === 'finish' ? 'F' : String(30 + i)
      const type = c.type === 'start' ? 'Start' : c.type === 'finish' ? 'Finish' : 'Control'
      xml += `      <CourseControl type="${type}"><Control>${ctrlId}</Control></CourseControl>\n`
    })
    xml += `    </Course>\n`
    xml += `  </RaceCourseData>\n`
    xml += `</CourseData>\n`

    const blob = new Blob([xml], { type: 'application/xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${courseName.replace(/\s+/g, '_')}_IOF3.xml`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ── Derived values for active circuit ────────────────────────────────────────

  const controls = activeCircuit?.controls ?? []
  const controlCount = controls.filter(c => c.type === 'control').length
  const currentStep = circuits.length === 0 ? 1 : activeCircuit?.status === 'complete' ? 3 : 2
  const currentSuggestion =
    activeCircuit?.status === 'ai_suggesting'
      ? activeCircuit.aiSuggestions[activeCircuit.suggestionIdx] ?? null
      : null

  const courseDistance = computeCourseDistance(controls)

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-screen bg-gray-900 text-white overflow-hidden font-sans">

      {/* SIDEBAR */}
      <aside className="w-80 flex-shrink-0 bg-gray-800 border-r border-gray-700 flex flex-col z-20 shadow-xl">

        {/* Header */}
        <div className="p-4 border-b border-gray-700 bg-gray-800">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-500 rounded-md flex items-center justify-center shadow-lg shadow-blue-500/20">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-bold text-white tracking-tight">AItraceur</h1>
              <p className="text-[10px] text-blue-400 font-medium uppercase tracking-wider">Éditeur de parcours</p>
            </div>
          </div>
        </div>

        {/* Competition mode toggle */}
        <div className="px-4 py-2 border-b border-gray-700 bg-gray-800/60">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-gray-300">Mode Compétition</span>
            <button
              onClick={() => setCompetitionMode(v => !v)}
              className={`relative w-9 h-5 rounded-full transition-colors ${competitionMode ? 'bg-blue-500' : 'bg-gray-600'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${competitionMode ? 'translate-x-4' : ''}`} />
            </button>
          </div>
          {competitionMode && (
            <input
              type="text"
              value={competitionName}
              onChange={e => setCompetitionName(e.target.value)}
              placeholder="Nom de la compétition"
              className="mt-2 w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white placeholder-gray-400 focus:outline-none focus:border-blue-400"
            />
          )}
        </div>

        {/* Circuit selector — always visible */}
        <CircuitSelector
          circuits={circuits}
          activeCircuitId={activeCircuitId}
          onSelect={setActiveCircuitId}
          onDelete={handleDeleteCircuit}
          onAddNew={() => setShowCreationForm(true)}
        />

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">

          {/* Stepper */}
          <div className="flex items-start mb-4">
            {STEPS.map((label, i) => (
              <div key={i} className="flex items-center flex-1 min-w-0">
                <div className="flex flex-col items-center">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${
                    i < currentStep ? 'bg-green-500 text-white' :
                    i === currentStep ? 'bg-blue-500 text-white shadow-md shadow-blue-500/40' :
                    'bg-gray-700 text-gray-600'
                  }`}>
                    {i < currentStep ? '✓' : i + 1}
                  </div>
                  <span className={`text-[9px] mt-1 font-medium text-center leading-tight ${
                    i === currentStep ? 'text-blue-300' : i < currentStep ? 'text-green-400' : 'text-gray-600'
                  }`}>{label}</span>
                </div>
                {i < STEPS.length - 1 && (
                  <div className={`flex-1 h-px mx-1 mb-3 ${i < currentStep ? 'bg-green-500/60' : 'bg-gray-700'}`} />
                )}
              </div>
            ))}
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-900/50 border border-red-500/50 rounded-lg text-sm text-red-200">
              {error}
            </div>
          )}

          <div className="space-y-4">

              {/* OCAD map uploader — optional enhancement */}
              <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
                <h2 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
                  <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                  Carte OCAD {!ocadData && <span className="text-gray-500 font-normal">(optionnel)</span>}
                </h2>
                <OcadUploader onOcadLoaded={handleOcadLoaded} onLoading={setIsLoading} onError={handleError} />
                {!ocadData && (
                  <p className="text-xs text-gray-500 mt-2 text-center">
                    Sans carte : génération sprint depuis OSM
                  </p>
                )}
              </div>

              {/* Map info — only when OCAD loaded */}
              {ocadData && (
              <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
                <div className="flex justify-between items-start mb-2">
                  <h2 className="text-sm font-semibold text-gray-200">Carte Active</h2>
                  <div className="flex items-center gap-2">
                    {imageData && (
                      <button
                        onClick={() => setMapMode(m => m === 'ocad' ? 'osm' : 'ocad')}
                        title={mapMode === 'ocad' ? 'Afficher OSM en fond' : 'Afficher carte OCAD seule'}
                        className={`text-xs px-1.5 py-0.5 rounded transition-colors ${mapMode === 'ocad' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-blue-400 bg-gray-600'}`}
                      >
                        {mapMode === 'ocad' ? 'OCAD' : 'OSM'}
                      </button>
                    )}
                    <button
                      onClick={() => { setOcadData(null); setCircuits([]); setActiveCircuitId(null); setImageData(null); setMapMode('osm') }}
                      className="text-xs text-gray-400 hover:text-red-400 transition-colors"
                    >
                      Fermer
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-sm text-blue-300 bg-blue-900/20 p-2 rounded truncate">
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="truncate">{ocadData.fileName}</span>
                </div>
                <div className="mt-2 text-xs text-gray-500 flex justify-between">
                  <span>OCAD v{ocadData.version}</span>
                  <span>{ocadData.geojson?.features?.length || 0} objets</span>
                </div>
                <div className="mt-2 text-xs flex items-center gap-1.5">
                  {renderLoading ? (
                    <>
                      <span className="w-3 h-3 border-2 border-blue-400/30 border-t-blue-400 rounded-full animate-spin inline-block" />
                      <span className="text-blue-400">Rendu ISOM en cours…</span>
                    </>
                  ) : imageData ? (
                    <>
                      <span className="w-2 h-2 rounded-full bg-green-500" />
                      <span className="text-green-400">Rendu raster ISOM actif</span>
                    </>
                  ) : (
                    <>
                      <span className="w-2 h-2 rounded-full bg-yellow-500" />
                      <span className="text-yellow-400">Service de rendu indisponible</span>
                    </>
                  )}
                </div>
              </div>
              )}

              {/* OCAD Analysis Panel (13c) */}
              {ocadAnalysis && <OcadAnalysisPanel analysis={ocadAnalysis} />}

              {/* Active circuit panel — always visible */}
              {activeCircuit ? (
                <>
                  {/* Circuit info */}
                  <div className="bg-blue-900/20 border border-blue-700/30 rounded-xl p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <p className="text-xs text-blue-400 uppercase tracking-wider font-medium">Circuit actif</p>
                        <p className="text-lg font-bold text-white">{activeCircuit.name}</p>
                      </div>
                      <div className="text-right text-xs text-gray-400">
                        {activeCircuit.status === 'complete' && <span className="text-green-400 font-medium">✓ Complet</span>}
                        {activeCircuit.status === 'ai_suggesting' && <span className="text-purple-400 animate-pulse">Suggestion IA…</span>}
                        {activeCircuit.status === 'setup' && <span className="text-gray-500">En cours</span>}
                      </div>
                    </div>
                    {/* Paramètres IOF du circuit */}
                    {(() => {
                      const p = getCircuitParams(activeCircuit)
                      return (
                        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] pt-2 border-t border-blue-700/20">
                          <span className="text-gray-500">Distance cible</span>
                          <span className="text-gray-200 font-medium text-right">
                            {p.target_length_m >= 1000 ? `${(p.target_length_m / 1000).toFixed(1)} km` : `${p.target_length_m} m`}
                          </span>
                          <span className="text-gray-500">Temps vainqueur</span>
                          <span className="text-gray-200 font-medium text-right">~{p.winning_time_minutes} min</span>
                          <span className="text-gray-500">Niveau tech.</span>
                          <span className="text-yellow-400 font-medium text-right">{p.technical_level}</span>
                          <span className="text-gray-500">Postes cibles</span>
                          <span className="text-gray-200 font-medium text-right">{p.target_controls}</span>
                        </div>
                      )
                    })()}
                  </div>

                  {/* Tools */}
                  {activeCircuit.status !== 'ai_suggesting' && (
                    <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
                      <h2 className="text-sm font-semibold text-gray-200 mb-3">Outils de tracé</h2>
                      <div className="grid grid-cols-2 gap-2">
                        {tools.map(tool => (
                          <button
                            key={tool.id}
                            onClick={() => setActiveTool(tool.id)}
                            className={`flex flex-col items-center justify-center p-3 rounded-lg border transition-all ${
                              activeTool === tool.id
                                ? 'bg-blue-600 border-blue-500 shadow-inner'
                                : 'bg-gray-800 border-gray-700 hover:border-gray-500 hover:bg-gray-700 text-gray-400'
                            }`}
                          >
                            <span className="text-xl mb-1">{tool.icon}</span>
                            <span className={`text-[10px] font-medium ${activeTool === tool.id ? 'text-white' : ''}`}>
                              {tool.label}
                            </span>
                          </button>
                        ))}
                      </div>
                      {activeTool === 'forbidden' && (
                        <p className="text-xs text-gray-500 text-center mt-2">
                          Cliquez pour ajouter des sommets · Bouton "✓" sur la carte pour fermer
                        </p>
                      )}
                    </div>
                  )}

                  {/* AI suggestion panel */}
                  <AISuggestionPanel
                    activeCircuit={activeCircuit}
                    onValidate={handleValidateSuggestion}
                    onSkip={handleSkipSuggestion}
                  />

                  {/* Controls list */}
                  {controls.length > 0 && (
                    <ControlsList
                      controls={controls}
                      onDelete={handleDeleteControl}
                      totalDistance={courseDistance}
                      controlCount={controlCount}
                      onShowRoutes={handleShowRoutes}
                      activeRouteLegIdx={routeDisplay?.legIdx ?? null}
                    />
                  )}

                  {/* Complétion automatique — suggestions épuisées avant cible */}
                  {activeCircuit.status === 'needs_completion' && controls.length > 0 && (() => {
                    const p = getCircuitParams(activeCircuit)
                    const missing = Math.max(1, p.target_controls - controlCount)
                    return (
                      <div className="rounded-xl border border-orange-700/40 bg-orange-900/20 p-3 text-xs">
                        <p className="font-semibold text-orange-400 mb-1">Suggestions épuisées</p>
                        <p className="text-gray-400 mb-2">
                          {courseDistance}m / {p.target_length_m}m · {controlCount} / {p.target_controls} postes
                        </p>
                        <button
                          onClick={handleCompleteCircuit}
                          disabled={isGenerating}
                          className="w-full py-1.5 px-3 bg-orange-600 hover:bg-orange-500 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-colors"
                        >
                          {isGenerating ? 'Génération…' : `Compléter (${missing} poste${missing > 1 ? 's' : ''} manquant${missing > 1 ? 's' : ''})`}
                        </button>
                      </div>
                    )
                  })()}

                  {/* Badge conformité IOF (visible quand circuit complet) */}
                  {activeCircuit.status === 'complete' && controls.length > 0 && (() => {
                    const p = getCircuitParams(activeCircuit)
                    const distRatio = courseDistance / p.target_length_m
                    const distOk = distRatio >= 0.75 && distRatio <= 1.25
                    const ctrlOk = Math.abs(controlCount - p.target_controls) <= 3
                    const allOk = distOk && ctrlOk
                    return (
                      <div className={`rounded-xl border p-3 text-xs ${
                        allOk ? 'bg-green-900/20 border-green-700/30' : 'bg-yellow-900/20 border-yellow-700/30'
                      }`}>
                        <p className={`font-semibold mb-2 ${allOk ? 'text-green-400' : 'text-yellow-400'}`}>
                          {allOk ? '✓ Conforme IOF' : '⚠ Hors normes IOF'}
                        </p>
                        <div className="space-y-1 text-gray-400">
                          <div className="flex justify-between">
                            <span>Distance</span>
                            <span className={`font-medium ${distOk ? 'text-green-400' : 'text-yellow-400'}`}>
                              {courseDistance >= 1000 ? `${(courseDistance / 1000).toFixed(1)} km` : `${courseDistance} m`}
                              {' '}/ cible {p.target_length_m >= 1000 ? `${(p.target_length_m / 1000).toFixed(1)} km` : `${p.target_length_m} m`}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span>Postes</span>
                            <span className={`font-medium ${ctrlOk ? 'text-green-400' : 'text-yellow-400'}`}>
                              {controlCount} / cible {p.target_controls}
                            </span>
                          </div>
                          {(activeCircuit.skippedCount ?? 0) > 0 && !distOk && (
                            <div className="mt-2 pt-2 border-t border-yellow-700/30 text-yellow-300">
                              {activeCircuit.skippedCount} poste{activeCircuit.skippedCount > 1 ? 's' : ''} refusé{activeCircuit.skippedCount > 1 ? 's' : ''} → distance réduite. Relancez la génération IA pour compléter.
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })()}

                  {/* Terrain */}
                  <TerrainPanel
                    ocadData={ocadData}
                    onTerrainLoaded={(data) => { setTerrainData(data); setShowRunnability(true) }}
                    showRunnability={showRunnability}
                    onToggleRunnability={() => setShowRunnability(v => !v)}
                  />

                  {/* Actions */}
                  <div className="bg-gray-700/50 p-4 rounded-xl border border-gray-700">
                    <h2 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
                      <span className="text-purple-400">✨</span> Actions IA
                    </h2>

                    <button
                      onClick={handleAiGenerate}
                      disabled={isGenerating || activeCircuit.status === 'ai_suggesting'}
                      className="w-full mb-2 py-2.5 px-4 bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2 shadow-lg shadow-purple-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isGenerating ? (
                        <>
                          <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin inline-block" />
                          Génération…
                        </>
                      ) : (
                        <>
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                          Générer avec l'IA
                        </>
                      )}
                    </button>

                    {generationError && (
                      <p className="text-xs text-red-400 mt-1 mb-2">{generationError}</p>
                    )}

                    <DialogueLog
                      dialogue={dialogue}
                      controleurReport={controleurReport}
                      isGenerating={isGenerating && activeCircuit?.type === 'sprint'}
                      progressLabel={progressLabel}
                    />

                    <button
                      onClick={handleExportIOF}
                      disabled={controls.length === 0}
                      className="w-full py-2.5 px-4 bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-600 text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                      Export IOF XML 3.0
                    </button>

                  </div>
                </>
              ) : (
                /* No active circuit — prompt to create one */
                <div className="text-center p-6 bg-gray-700/30 rounded-xl border border-dashed border-gray-600">
                  <p className="text-gray-400 text-sm mb-3">Créez votre premier circuit.</p>
                  <button
                    onClick={() => setShowCreationForm(true)}
                    className="py-2.5 px-5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
                  >
                    Créer un circuit
                  </button>
                </div>
              )}

          </div>
        </div>
      </aside>


      {/* MAIN MAP */}
      <main className="flex-1 relative z-10 bg-gray-950">
        {isLoading && (
          <div className="absolute inset-0 bg-gray-900/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center">
            <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mb-4" />
            <p className="text-blue-400 font-medium animate-pulse">Conversion OCAD en cours...</p>
          </div>
        )}

        {/* Top info bar */}
        {activeCircuit && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 bg-gray-800/90 backdrop-blur border border-gray-700 px-6 py-2 rounded-full shadow-lg pointer-events-none flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-sm font-medium text-gray-200">
                {activeCircuit
                  ? <>Circuit : <span className="text-blue-400 font-bold">{activeCircuit.name}</span></>
                  : <span className="text-gray-400">Aucun circuit actif</span>
                }
              </span>
            </div>
            {activeCircuit && (
              <>
                <div className="w-px h-4 bg-gray-600" />
                <div className="text-sm text-gray-400">
                  Mode: <span className="text-blue-400">{tools.find(t => t.id === activeTool)?.label}</span>
                </div>
                <div className="w-px h-4 bg-gray-600" />
                <div className="text-sm text-gray-400">{controls.length} point(s)</div>
              </>
            )}
          </div>
        )}

        <MapViewer
          ocadData={ocadData}
          onMapClick={handleMapClick}
          controls={controls}
          forbiddenZones={activeCircuit?.forbiddenZones ?? []}
          currentSuggestion={currentSuggestion}
          activeTool={activeTool}
          terrainData={showRunnability ? terrainData : null}
          imageData={imageData}
          onAddForbiddenZone={handleAddForbiddenZone}
          onUpdateSuggestion={handleUpdateSuggestion}
          onMapReady={(map) => { mapRef.current = map }}
          routeDisplay={routeDisplay}
          ocadMode={mapMode === 'ocad' && !!imageData}
          backgroundControls={competitionMode ? getAllExistingControls() : []}
        />
      </main>

      {/* Circuit creation modal */}
      <CircuitCreationModal
        isOpen={showCreationForm}
        onClose={() => setShowCreationForm(false)}
        onCreateCircuit={handleCreateCircuit}
        competitionMode={competitionMode}
        existingCircuitCount={circuits.length}
      />
    </div>
  )
}

export default App
