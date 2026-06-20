const express = require('express')
const cors = require('cors')
const multer = require('multer')
const path = require('path')
const fs = require('fs')
const { readOcad, ocadToGeoJson } = require('ocad2geojson')
const OcadTiler = require('ocad-tiler')
const { renderSvg } = require('ocad2tiles')
const { XMLSerializer } = require('xmldom')
const sharp = require('sharp')
const proj4 = require('proj4')

const app = express()
app.use(cors())

const UPLOAD_DIR = path.join(__dirname, 'uploads')
const RENDER_DIR = path.join(__dirname, 'renders')
fs.mkdirSync(UPLOAD_DIR, { recursive: true })
fs.mkdirSync(RENDER_DIR, { recursive: true })

const upload = multer({ dest: UPLOAD_DIR })

app.post('/upload', upload.single('file'), async (req, res) => {
  try {
    const mapId = path.parse(req.file.filename).name
    const inputPath = req.file.path

    // Rename to .ocd (multer strips extension)
    const ocdPath = inputPath + '.ocd'
    fs.renameSync(inputPath, ocdPath)

    console.log(`[render] Reading OCAD file ${mapId}...`)
    const ocadFile = await readOcad(ocdPath)
    const tiler = new OcadTiler(ocadFile)
    const crs = ocadFile.getCrs()

    console.log(`[render] CRS:`, crs)
    console.log(`[render] Bounds (native):`, tiler.bounds)

    // Render full map as single PNG
    const outputPath = path.join(RENDER_DIR, `${mapId}.png`)
    const extent = tiler.bounds

    // Adaptive resolution: fine for small maps (sprint), coarser for large maps.
    // Keeps output under Sharp's 268Mpx hard limit (we target <50Mpx).
    // sprint 600×600m @ 0.1m/px → 36Mpx ✓  |  MD 2km² @ 0.5m/px → 16Mpx ✓  |  LD ≥1m/px
    const extentW = extent[2] - extent[0]
    const extentH = extent[3] - extent[1]
    const areaPx = extentW * extentH / 50_000_000
    const RAW = Math.sqrt(areaPx)
    const RESOLUTION = RAW < 0.3 ? 0.1 : RAW < 0.8 ? 0.5 : Math.ceil(RAW)
    console.log(`[render] Extent ${Math.round(extentW)}×${Math.round(extentH)}m → resolution ${RESOLUTION}m/px`)

    // Use renderSvg directly (not render()) to avoid an oversized intermediate raster.
    // render() internally uses svgResolution = min(R, scale/15000) which at scale 1:5000
    // gives 0.333 m/px → ~300Mpx SVG, exceeding Sharp's pixel limit.
    const svg = renderSvg(tiler, extent, RESOLUTION, { fill: 'white', applyGrivation: true })
    const xml = new XMLSerializer().serializeToString(svg)
    await sharp(Buffer.from(xml)).png().toFile(outputPath)
    console.log(`[render] Image saved: ${outputPath}`)

    // Convert bounds from native CRS to WGS84
    const boundsWgs84 = convertBoundsToWgs84(extent, crs)
    console.log(`[render] Bounds (WGS84):`, boundsWgs84)

    res.json({
      mapId,
      imageUrl: `/renders/${mapId}.png`,
      bounds: boundsWgs84,
      nativeBounds: extent,
      crs: crs,
      status: 'ok',
    })
  } catch (err) {
    console.error('[render] Error:', err)
    res.status(500).json({ error: err.message })
  }
})

// Serve rendered images
app.use('/renders', express.static(RENDER_DIR, {
  maxAge: '1d',
  immutable: true,
}))

app.get('/health', (req, res) => res.json({ status: 'ok' }))

// Vraies zones interdites (hors-limites, dangereuses, végétation impassable) — dilatées côté backend
// Les bâtiments (521/522/527/528/529) sont exclus : coins/angles = postes valides en sprint
// format ocad2geojson : symNum × 1000
const FORBIDDEN_SYMS = [
  520000, 520001, 520002,  // Out of bounds (ISOM/ISSprOM)
  526000, 526001, 526002,  // Out of bounds passage (ISOM)
  709000, 709001, 709002,  // Do-not-enter sprint (ISSprOM)
  714000, 714001, 714002,  // Dangerous area (ISSprOM)
  715000, 715001, 715002,  // Out of bounds variant
  406000, 406001, 406002,  // Rough open land (olive, lent — pas de postes)
  407000, 407001, 407002,  // Rough open land with trees (olive)
  410000, 410001, 410002,  // Vegetation: fight / impassable (ISOM/ISSprOM)
  411000, 411001, 411002,  // Vegetation: impassable (ISSprOM)
]
const BUILDING_SYMS = [    // pour diagnostic — exclus du masque dur
  521000, 521001, 521002,
  522000, 522001, 522002,
  527000, 527001, 527002,
  528000, 528001, 528002,
  529000, 529001, 529002,
]

app.get('/map/:mapId/forbidden-zones', async (req, res) => {
  const { mapId } = req.params
  const ocdPath = path.join(UPLOAD_DIR, `${mapId}.ocd`)
  if (!fs.existsSync(ocdPath)) {
    return res.status(404).json({ error: 'map not found' })
  }
  try {
    // Ensure Lambert-93 is defined for CRS conversion
    proj4.defs('EPSG:2154', '+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=49 +lat_2=44 +x_0=700000 +y_0=6600000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs +type=crs')
    const ocadFile = await readOcad(ocdPath)
    const geojson = ocadToGeoJson(ocadFile, {
      includeSymbols: FORBIDDEN_SYMS,
      applyCrs: true,
      generateSymbolElements: false,
    })
    // Diagnostic : compter OOB / végétation / bâtiments
    const allSyms = [...FORBIDDEN_SYMS, ...BUILDING_SYMS]
    const geojsonAll = ocadToGeoJson(ocadFile, { includeSymbols: allSyms, applyCrs: true, generateSymbolElements: false })
    const oobSymNums = new Set([520, 526, 709, 714, 715])
    const vegSymNums = new Set([406, 407, 410, 411])
    const buildingSymNums = new Set([521, 522, 527, 528, 529])
    const symOf = f => Math.floor((f.properties?.sym || 0) / 1000)
    const trueOob = geojsonAll.features.filter(f => oobSymNums.has(symOf(f))).length
    const vegForbidden = geojsonAll.features.filter(f => vegSymNums.has(symOf(f))).length
    const buildings = geojsonAll.features.filter(f => buildingSymNums.has(symOf(f))).length
    const polyCount = geojson.features.filter(f => f.geometry?.type === 'Polygon' || f.geometry?.type === 'MultiPolygon').length
    console.log(`[forbidden-zones] ${mapId}: returned=${geojson.features.length} (oob=${trueOob} veg=${vegForbidden} buildings=${buildings} excluded) polygones=${polyCount}`)

    // Convert all feature coordinates from native CRS (e.g. Lambert-93) to WGS84
    const crs = ocadFile.getCrs()
    const sourceCrs = (crs?.catalog === 'EPSG' || crs?.code) ? `EPSG:${crs.code}` : 'EPSG:2154'
    const geojsonWgs84 = transformGeoJsonCrs(geojson, sourceCrs)
    res.json(geojsonWgs84)
  } catch (err) {
    console.error('[forbidden-zones] Error:', err.message)
    res.status(500).json({ error: err.message })
  }
})

function transformGeoJsonCrs(geojson, sourceCrsCode) {
  const converter = proj4(sourceCrsCode, 'EPSG:4326')

  function transformCoord(coord) {
    return converter.forward(coord)
  }

  function transformRing(ring) {
    return ring.map(transformCoord)
  }

  function transformGeometry(geom) {
    if (!geom) return geom
    switch (geom.type) {
      case 'Point':
        return { ...geom, coordinates: transformCoord(geom.coordinates) }
      case 'LineString':
        return { ...geom, coordinates: transformRing(geom.coordinates) }
      case 'MultiLineString':
        return { ...geom, coordinates: geom.coordinates.map(transformRing) }
      case 'Polygon':
        return { ...geom, coordinates: geom.coordinates.map(transformRing) }
      case 'MultiPolygon':
        return { ...geom, coordinates: geom.coordinates.map(rings => rings.map(transformRing)) }
      default:
        return geom
    }
  }

  return {
    ...geojson,
    features: geojson.features.map(f => ({ ...f, geometry: transformGeometry(f.geometry) })),
  }
}

function convertBoundsToWgs84(extent, crs) {
  // extent = [minX, minY, maxX, maxY] in native CRS
  const [minX, minY, maxX, maxY] = extent

  // Build proj4 definition from OCAD CRS info
  let sourceCrs = null

  if (crs && crs.catalog === 'EPSG') {
    sourceCrs = `EPSG:${crs.code}`
  } else if (crs && crs.code) {
    sourceCrs = `EPSG:${crs.code}`
  }

  // Common French CRS fallback
  if (!sourceCrs) {
    // Heuristic: if coordinates look like Lambert-93 (France)
    const avgX = (minX + maxX) / 2
    const avgY = (minY + maxY) / 2
    if (avgX > 100000 && avgX < 1300000 && avgY > 6000000 && avgY < 7200000) {
      sourceCrs = 'EPSG:2154'
    }
  }

  if (!sourceCrs) {
    console.warn('[render] Unknown CRS, returning native bounds as-is')
    return { southWest: [minY, minX], northEast: [maxY, maxX] }
  }

  // Define proj4 projections
  // Lambert-93
  proj4.defs('EPSG:2154', '+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=49 +lat_2=44 +x_0=700000 +y_0=6600000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs +type=crs')

  try {
    const sw = proj4(sourceCrs, 'EPSG:4326', [minX, minY])
    const ne = proj4(sourceCrs, 'EPSG:4326', [maxX, maxY])

    return {
      southWest: [sw[1], sw[0]], // [lat, lng]
      northEast: [ne[1], ne[0]], // [lat, lng]
    }
  } catch (err) {
    console.error('[render] Proj4 conversion failed:', err.message)
    return { southWest: [minY, minX], northEast: [maxY, maxX] }
  }
}

const PORT = process.env.TILE_PORT || 8089
app.listen(PORT, () => {
  console.log(`[render] OCAD render service on http://localhost:${PORT}`)
})
