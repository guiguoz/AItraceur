const express = require('express')
const cors = require('cors')
const multer = require('multer')
const path = require('path')
const fs = require('fs')
const { readOcad } = require('ocad2geojson')
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

    // Dynamic resolution: cap image at ~50Mpx to stay well under Sharp's 268Mpx limit.
    // R=1 → 5km map ~25Mpx (fine). R=2 → 10km map ~25Mpx. R=4 → 20km map ~25Mpx.
    const extentW = extent[2] - extent[0]
    const extentH = extent[3] - extent[1]
    const RESOLUTION = Math.max(1, Math.ceil(Math.sqrt(extentW * extentH / 50_000_000)))
    console.log(`[render] Extent ${Math.round(extentW)}×${Math.round(extentH)}m → resolution ${RESOLUTION}m/px`)

    // Use renderSvg directly (not render()) to avoid an oversized intermediate raster.
    // render() internally uses svgResolution = min(R, scale/15000) which at scale 1:5000
    // gives 0.333 m/px → ~300Mpx SVG, exceeding Sharp's pixel limit.
    const svg = renderSvg(tiler, extent, RESOLUTION, { fill: 'white' })
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
