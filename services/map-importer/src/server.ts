import express from 'express';
import cors from 'cors';
import multer from 'multer';
import path from 'path';
import fs from 'fs/promises';
import { execFile } from 'child_process';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);

const PORT = Number(process.env.PORT || 8788);
const OCAD2GEOJSON_BIN = process.env.OCAD2GEOJSON_BIN || 'ocad2geojson'; // must exist in PATH
const TMP_DIR = process.env.IMPORT_TMP_DIR || path.join(process.cwd(), 'tmp');

const app = express();
app.use(cors());
app.use(express.json());

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 200 * 1024 * 1024 }, // 200MB
});

type ImportResult = {
  bbox: [number, number, number, number] | null;
  crs?: string | null;
  scale?: number | null;
  layers: Array<{ name: string; featureCount: number; file?: string }>;
  merged: {
    forbidden?: any | null;
    water?: any | null;
    cliffs?: any | null;
    vegetation?: any | null;
    roads_tracks?: any | null;
    all?: any | null;
  };
  summary: {
    message: string;
    stats: Record<string, unknown>;
  };
};

function isGeoJSON(obj: any): boolean {
  return obj && typeof obj === 'object' && (obj.type === 'FeatureCollection' || obj.type === 'Feature' || obj.type === 'GeometryCollection');
}

async function readJsonSafe(filePath: string) {
  try {
    const buf = await fs.readFile(filePath, 'utf-8');
    return JSON.parse(buf);
  } catch {
    return null;
  }
}

function mergeCollections(collections: Array<any | null>) {
  const features = collections.flatMap(c => (c?.features ?? []) as any[]);
  return {
    type: 'FeatureCollection',
    features,
  };
}

// Simple heuristics to group layers by filename
function classifyLayerByFilename(filename: string) {
  const base = path.basename(filename).toLowerCase();
  return {
    forbidden: /forbid|private|interdit|no[-_ ]pass|outofbounds|impass/.test(base),
    water: /water|lake|river|pond|marsh|wet|eau|mare|bassin/.test(base),
    cliffs: /cliff|rock|falaise|roc|escarp/.test(base),
    vegetation: /forest|wood|veg|bush|green|vegetation|bois|foret|sous[-_ ]bois/.test(base),
    roads_tracks: /road|path|track|trail|chemin|route|sentier|piste|voie|ruelle/.test(base),
  };
}

app.get('/health', async (_req, res) => {
  try {
    const { stdout } = await execFileAsync(OCAD2GEOJSON_BIN, ['--help'], { maxBuffer: 1024 * 1024 });
    res.json({ ok: true, bin: OCAD2GEOJSON_BIN, help: !!stdout, tmp: TMP_DIR });
  } catch {
    res.json({ ok: true, bin: OCAD2GEOJSON_BIN, help: false, tmp: TMP_DIR, note: 'Verify ocad2geojson installation or set OCAD2GEOJSON_BIN.' });
  }
});

app.post('/import/ocad', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'Missing file in form-data field "file"' });
    }

    await fs.mkdir(TMP_DIR, { recursive: true });
    const jobId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const jobDir = path.join(TMP_DIR, jobId);
    await fs.mkdir(jobDir, { recursive: true });

    const ocadPath = path.join(jobDir, req.file.originalname.replace(/\s+/g, '_'));
    await fs.writeFile(ocadPath, req.file.buffer);

    const outDir = path.join(jobDir, 'out');
    await fs.mkdir(outDir, { recursive: true });

    // Run ocad2geojson CLI: ocad2geojson input.ocd -o outDir
    const { stderr } = await execFileAsync(OCAD2GEOJSON_BIN, [ocadPath, '-o', outDir], {
      cwd: jobDir,
      maxBuffer: 1024 * 1024 * 50,
    });
    if (stderr && process.env.NODE_ENV !== 'production') {
      // Non-fatal: some tools log to stderr
      // console.warn('ocad2geojson stderr:', stderr);
    }

    const files = await fs.readdir(outDir);
    const geojsonFiles = files.filter(f => f.toLowerCase().endsWith('.geojson'));

    if (geojsonFiles.length === 0) {
      return res.status(422).json({
        error: 'No GeoJSON produced by ocad2geojson',
        detail: 'Check the OCAD file and ocad2geojson installation.',
      });
    }

    const layerEntries: Array<{ name: string; featureCount: number; file: string; data: any | null }> = [];
    for (const f of geojsonFiles) {
      const p = path.join(outDir, f);
      const data = await readJsonSafe(p);
      let featureCount = 0;
      if (isGeoJSON(data)) {
        if (data.type === 'FeatureCollection') {
          featureCount = Array.isArray(data.features) ? data.features.length : 0;
        } else if (data.type === 'Feature') {
          featureCount = 1;
        }
      }
      layerEntries.push({ name: f, featureCount, file: f, data });
    }

    // Aggregations
    const forb = mergeCollections(layerEntries.filter(e => classifyLayerByFilename(e.name).forbidden).map(e => e.data));
    const water = mergeCollections(layerEntries.filter(e => classifyLayerByFilename(e.name).water).map(e => e.data));
    const cliffs = mergeCollections(layerEntries.filter(e => classifyLayerByFilename(e.name).cliffs).map(e => e.data));
    const vegetation = mergeCollections(layerEntries.filter(e => classifyLayerByFilename(e.name).vegetation).map(e => e.data));
    const roads_tracks = mergeCollections(layerEntries.filter(e => classifyLayerByFilename(e.name).roads_tracks).map(e => e.data));
    const all = mergeCollections(layerEntries.map(e => e.data));

    // Compute bbox from merged "all"
    function computeBBox(fc: any): [number, number, number, number] | null {
      try {
        const coords: [number, number][] = [];
        for (const f of fc.features || []) {
          const geom = f.geometry;
          const add = (xy: any) => {
            if (!Array.isArray(xy)) return;
            if (typeof xy[0] === 'number' && typeof xy[1] === 'number') coords.push([xy[0], xy[1]]);
            else xy.forEach(add);
          };
          add(geom?.coordinates);
        }
        if (!coords.length) return null;
        const xs = coords.map(c => c[0]);
        const ys = coords.map(c => c[1]);
        return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
      } catch {
        return null;
      }
    }
    const bbox = computeBBox(all);

    const result: ImportResult = {
      bbox: bbox ?? null,
      crs: null, // CRS rarely explicit from OCAD
      scale: null, // Fill if you can extract from metadata
      layers: layerEntries.map(e => ({ name: e.name, featureCount: e.featureCount, file: e.file })),
      merged: { forbidden: forb, water, cliffs, vegetation, roads_tracks, all },
      summary: {
        message: 'OCAD converted to GeoJSON. Key layers aggregated and stats available.',
        stats: {
          totalLayers: layerEntries.length,
          totalFeatures: (all.features || []).length,
        },
      },
    };

    res.json(result);
  } catch (e: any) {
    res.status(500).json({ error: 'Import failed', detail: e?.message || String(e) });
  }
});

app.listen(PORT, () => {
  console.log(`Map Importer listening on http://localhost:${PORT}`);
  console.log(`Using ocad2geojson binary: ${OCAD2GEOJSON_BIN}`);
});