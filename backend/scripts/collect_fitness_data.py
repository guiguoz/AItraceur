#!/usr/bin/env python3
"""
A.8b v2 — One-shot pipeline collection dataset stabilisé.

Prérequis backend :
  cd backend && INTENT_DEBUG_CSV=1 uvicorn src.main:app --host 0.0.0.0 --port 8000

4 groupes séquentiels, parallèle intra-groupe (MAX_PARALLEL=4) :
  stanne_td3 : 10 circuits, Ste Anne TD3
  crohot_td3 : 12 circuits, Grand-Crohot TD3
  crohot_td4 : 12 circuits, Grand-Crohot TD4
  crohot_td5 : 12 circuits, Grand-Crohot TD5

Sortie : backend/debug/intent_legs_a8b_v2.csv (jamais append au global)
"""

import argparse
import asyncio
import csv
import json
import os
import pathlib
import subprocess
import sys
import time

try:
    import aiohttp
except ImportError:
    print("pip install aiohttp"); sys.exit(1)


# ─── Config ──────────────────────────────────────────────────────────────────

OCD_PATHS = {
    "stanne": r"E:\RunningRaid\2024-2025\entrainement 020325\La Route de Ste Anne II_v4.ocd",
    "crohot": r"E:\RunningRaid\Cartographie\fichiers OCAD et jpg\O12_2019-05-25_Grand-Crohot-Nord_ech-15000.ocd10.ocd",
}

DATASETS = [
    {"name": "stanne_td3", "map": "stanne", "td": 3, "n_each": 10},
    {"name": "crohot_td3", "map": "crohot", "td": 3, "n_each": 12},
    {"name": "crohot_td4", "map": "crohot", "td": 4, "n_each": 12},
    {"name": "crohot_td5", "map": "crohot", "td": 5, "n_each": 12},
]

DISTANCES    = {3: 4000, 4: 6000,  5: 9000}
CONTROLS     = {3: 11,   4: 15,    5: 20}
CT_TYPE      = {3: "md", 4: "ld",  5: "ld"}

BASE_URL      = "http://localhost:8000"
MAX_PARALLEL  = 4
POLL_INTERVAL = 6    # seconds between polls
POLL_TIMEOUT  = 240  # max wait per circuit (LD circuits longer)

GLOBAL_CSV = pathlib.Path("backend/debug/intent_legs.csv")
OUTPUT_CSV = pathlib.Path("backend/debug/intent_legs_a8b_v2.csv")

_GLOBAL_FIELDS = [
    "circuit_id", "td", "course_type", "leg_index", "leg_m",
    "fitness_total",
    "parallel_affordance", "crossing_density", "exit_clarity", "contour_crossing_guidance",
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
    "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
    "score_a", "penalty_b", "score_d", "score_h",
    "n_unique_tags",
]
V2_FIELDS = ["map_name"] + _GLOBAL_FIELDS

# ─── OCD parsing ─────────────────────────────────────────────────────────────

# Uses ocadToGeoJson (same pipeline as frontend) + 1%/99% percentile bbox.
# Outputs { bbox: [minLon, minLat, maxLon, maxLat], features: [...LineString only] }
_NODE_EXTRACT = r"""
const proj4 = require('proj4');
const { readOcad, ocadToGeoJson } = require('ocad2geojson');
proj4.defs('EPSG:2154', '+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=44 +lat_2=49 +x_0=700000 +y_0=6600000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs');
(async () => {
    const ocadFile = await readOcad(process.argv[2]);
    const crs = ocadFile.getCrs();
    const code = crs && crs.code;
    let converter = null;
    if (code && code !== 4326) {
        const ep = 'EPSG:' + code;
        if (proj4.defs(ep)) {
            const fwd = proj4(ep, 'WGS84');
            converter = (xy) => fwd.forward(xy);
        }
    }
    const xs = [], ys = [];
    function reproj(coords) {
        if (typeof coords[0] === 'number') {
            const pt = converter ? converter([coords[0], coords[1]]) : [coords[0], coords[1]];
            xs.push(pt[0]); ys.push(pt[1]);
            return pt;
        }
        return coords.map(reproj);
    }
    const geojson = ocadToGeoJson(ocadFile);
    const allFeatures = geojson.features.map(f => {
        if (!f.geometry || !f.geometry.coordinates) return f;
        return { ...f, geometry: { ...f.geometry, coordinates: reproj(f.geometry.coordinates) } };
    });
    if (xs.length === 0) { process.stderr.write('No coords extracted\n'); process.exit(1); }
    xs.sort((a, b) => a - b); ys.sort((a, b) => a - b);
    const p = (arr, q) => arr[Math.max(0, Math.min(arr.length - 1, Math.floor(arr.length * q)))];
    const bbox = [p(xs, 0.01), p(ys, 0.01), p(xs, 0.99), p(ys, 0.99)];
    const lineFeats = allFeatures.filter(f =>
        f.geometry && (f.geometry.type === 'LineString' || f.geometry.type === 'MultiLineString')
    );
    console.log(JSON.stringify({ bbox, features: lineFeats }));
})().catch(e => { process.stderr.write(e.message + '\n'); process.exit(1); });
"""


def parse_ocd_data(ocd_path: str) -> tuple[dict, list]:
    """OCD → WGS84 bbox + LineString features via Node/ocad2geojson."""
    tile_dir = pathlib.Path(__file__).parent.parent / "tile-service"
    tmp = tile_dir / "_ocd_parse_tmp.js"
    tmp.write_text(_NODE_EXTRACT, encoding="utf-8")
    try:
        r = subprocess.run(
            ["node", str(tmp), ocd_path],
            capture_output=True, text=True, cwd=str(tile_dir), timeout=60
        )
    finally:
        tmp.unlink(missing_ok=True)

    if r.returncode != 0:
        raise RuntimeError(f"node parse failed: {r.stderr[:400]}")

    result = json.loads(r.stdout.strip())
    raw_bbox = result["bbox"]
    if not raw_bbox or len(raw_bbox) != 4:
        raise ValueError(f"Bounds invalides depuis {ocd_path}: {raw_bbox}")

    min_lon, min_lat, max_lon, max_lat = raw_bbox
    margin = 0.001
    bbox = {
        "min_x": min_lon - margin,
        "max_x": max_lon + margin,
        "min_y": min_lat - margin,
        "max_y": max_lat + margin,
    }
    return bbox, result.get("features", [])


# ─── Preprocess OCAD (build SegmentSpatialIndex on backend) ──────────────────

async def _preprocess_map(
    session: aiohttp.ClientSession, features: list, bbox: dict
) -> str | None:
    """POST /preprocess-ocad → segment_cache_id. Returns None on failure."""
    center_lat = (bbox["min_y"] + bbox["max_y"]) / 2
    try:
        async with session.post(
            f"{BASE_URL}/api/v1/generation/preprocess-ocad",
            json={"ocad_geojson_features": features, "center_lat": center_lat},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                print(f"  [preprocess HTTP {resp.status}]")
                return None
            data = await resp.json()
            cache_id = data.get("segment_cache_id", "")
            seg_count = data.get("segment_count", 0)
            print(f"  preprocess OK — {seg_count} segments, cache_id={cache_id[:8]}")
            return cache_id
    except Exception as e:
        print(f"  [preprocess err] {e}")
        return None


# ─── Circuit generation ───────────────────────────────────────────────────────

def _job_seed(map_name: str, td: int, local_idx: int) -> int:
    """Seed déterministe par job — garantit la reproductibilité inter-runs W_DIST."""
    return abs(hash((map_name, td, local_idx))) % (2 ** 31)


def _body(
    bbox: dict,
    td: int,
    map_name: str,
    local_idx: int,
    segment_cache_id: str | None = None,
    w_dist: float | None = None,
    w_diversity_mult: float = 1.0,
) -> dict:
    body: dict = {
        "bounding_box":    bbox,
        "technical_level": f"TD{td}",
        "circuit_type":    CT_TYPE[td],
        "target_length_m": DISTANCES[td],
        "target_controls": CONTROLS[td],
        "method":          "hybrid",
        "num_variants":    1,
        "force_mode":      "forest",
        "ga_seed":         _job_seed(map_name, td, local_idx),
        "w_diversity_mult": w_diversity_mult,
    }
    if segment_cache_id:
        body["segment_cache_id"] = segment_cache_id
    if w_dist is not None:
        body["w_dist_override"] = w_dist
    return body


async def _poll(session: aiohttp.ClientSession, task_id: str) -> bool:
    url = f"{BASE_URL}/api/v1/generation/circuit-status/{task_id}"
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status")
                    if status == "completed":
                        return True
                    if status == "error":
                        print(f"    [ERR] {task_id[:8]}: {data.get('error', '?')[:80]}")
                        return False
        except Exception as e:
            print(f"    [poll err] {task_id[:8]}: {e}")
        await asyncio.sleep(POLL_INTERVAL)
    print(f"    [TIMEOUT] {task_id[:8]}")
    return False


async def _one(
    session: aiohttp.ClientSession,
    bbox: dict,
    td: int,
    idx: int,
    map_name: str,
    segment_cache_id: str | None = None,
    w_dist: float | None = None,
    w_diversity_mult: float = 1.0,
) -> bool:
    try:
        async with session.post(
            f"{BASE_URL}/api/v1/generation/generate-circuit",
            json=_body(bbox, td, map_name, idx, segment_cache_id, w_dist, w_diversity_mult),
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 202:
                print(f"    [HTTP {resp.status}] TD{td} idx={idx}")
                return False
            data = await resp.json()
            task_id = data.get("task_id", "")
    except Exception as e:
        print(f"    [POST] TD{td} idx={idx}: {e}")
        return False

    print(f"    task {task_id[:8]}  TD{td}/{idx}")
    return await _poll(session, task_id)


async def _wait_csv_quiescent(
    csv_path: pathlib.Path, stable_secs: float = 3, timeout_secs: float = 30
) -> None:
    """Attend que le fichier CSV cesse d'être modifié (mtime + taille stables)."""
    deadline = time.time() + timeout_secs
    last_mtime = 0.0
    last_size  = -1
    stable_since = time.time()
    while time.time() < deadline:
        if csv_path.exists():
            st = csv_path.stat()
            if st.st_mtime != last_mtime or st.st_size != last_size:
                last_mtime  = st.st_mtime
                last_size   = st.st_size
                stable_since = time.time()
        if time.time() - stable_since >= stable_secs:
            return
        await asyncio.sleep(1)


def _snapshot(csv_path: pathlib.Path) -> set:
    if not csv_path.exists():
        return set()
    ids: set = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row.get("circuit_id", "")
            if cid:
                ids.add(cid)
    return ids


async def _run_group(
    group: dict,
    bbox: dict,
    session: aiohttp.ClientSession,
    segment_cache_id: str | None = None,
    w_dist: float | None = None,
    w_diversity_mult: float = 1.0,
) -> set:
    name, td, n, map_name = group["name"], group["td"], group["n_each"], group["map"]
    w_tag = f"  W_DIST={w_dist}" if w_dist is not None else ""
    wdiv_tag = f"  W_DIV_MULT={w_diversity_mult}" if w_diversity_mult != 1.0 else ""
    print(f"\n{'=' * 50}")
    print(f"Groupe {name} : {n} circuits TD{td}"
          + (f" (cache {segment_cache_id[:8]})" if segment_cache_id else " [no OCAD cache]")
          + w_tag + wdiv_tag)

    before = _snapshot(GLOBAL_CSV)
    sem = asyncio.Semaphore(MAX_PARALLEL)

    async def bounded(idx: int) -> bool:
        async with sem:
            return await _one(session, bbox, td, idx, map_name, segment_cache_id, w_dist, w_diversity_mult)

    results = await asyncio.gather(*[bounded(i) for i in range(n)])
    ok = sum(results)
    print(f"  → {ok}/{n} OK")

    # Attendre quiescence CSV : taille stable pendant 3s consécutives
    await _wait_csv_quiescent(GLOBAL_CSV, stable_secs=3, timeout_secs=30)
    after = _snapshot(GLOBAL_CSV)
    new_ids = after - before
    print(f"  → {len(new_ids)} circuit_ids nouveaux")
    return new_ids


# ─── Output CSV ───────────────────────────────────────────────────────────────

def write_v2(circuit_map: dict, output_csv: pathlib.Path = OUTPUT_CSV) -> int:
    """Lit le global CSV, filtre + enrichit, écrit v2. Retourne nb lignes."""
    if not GLOBAL_CSV.exists():
        print(f"WARN: {GLOBAL_CSV} introuvable — INTENT_DEBUG_CSV=1 actif ?")
        return 0

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(GLOBAL_CSV, newline="", encoding="utf-8") as fin, \
         open(output_csv, "w", newline="", encoding="utf-8") as fout:

        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=V2_FIELDS)
        writer.writeheader()

        for row in reader:
            cid = row.get("circuit_id", "")
            if cid not in circuit_map:
                continue
            out = {"map_name": circuit_map[cid]}
            for f in _GLOBAL_FIELDS:
                out[f] = row.get(f, "")
            writer.writerow(out)
            written += 1

    return written


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only",   default=None, help="nom du groupe à collecter (ex: crohot_td5)")
    parser.add_argument("--output", default=None, help="chemin CSV de sortie")
    parser.add_argument("--w_dist", type=float, default=None,
                        help="override W_DIST (défaut: 40.0). Ex: --w_dist 20")
    parser.add_argument("--w_diversity_mult", type=float, default=1.0,
                        help="multiplicateur W_LEG_DIVERSITY (défaut=1.0). Ex: --w_diversity_mult 0.5")
    args = parser.parse_args()

    datasets = [d for d in DATASETS if args.only is None or d["name"] == args.only]
    output_csv = pathlib.Path(args.output) if args.output else OUTPUT_CSV

    if not datasets:
        print(f"ERREUR: aucun groupe correspondant à --only '{args.only}'")
        print(f"Groupes disponibles: {[d['name'] for d in DATASETS]}")
        sys.exit(1)

    print("=== A.8b collect_fitness_data.py ===\n")
    if args.only:
        print(f"Mode --only : {args.only}  →  {output_csv}")
    if args.w_dist is not None:
        print(f"W_DIST override : {args.w_dist}  (défaut=40.0)")
    if args.w_diversity_mult != 1.0:
        print(f"W_DIVERSITY mult : {args.w_diversity_mult}  (défaut=1.0 → W_LEG_DIV={4.0 * args.w_diversity_mult:.1f})")

    # Healthcheck
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{BASE_URL}/docs", timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status >= 500:
                    raise RuntimeError(f"backend HTTP {r.status}")
    except Exception:
        print(f"ERREUR: backend inaccessible sur {BASE_URL}")
        print("Lancer: cd backend && INTENT_DEBUG_CSV=1 uvicorn src.main:app --host 0.0.0.0 --port 8000")
        sys.exit(1)

    print(f"Backend OK sur {BASE_URL}")
    print("  (démarré avec INTENT_DEBUG_CSV=1 ? vérifier le terminal backend)")

    # 1. Parse OCD → bbox + features (seulement les cartes nécessaires)
    needed_maps = {d["map"] for d in datasets}
    print("\n[1] Parse cartes OCD → WGS84 bbox + features")
    bboxes: dict[str, dict] = {}
    features_map: dict[str, list] = {}
    for map_name, ocd_path in OCD_PATHS.items():
        if map_name not in needed_maps:
            continue
        print(f"  {map_name}: {pathlib.Path(ocd_path).name}")
        try:
            bbox, features = parse_ocd_data(ocd_path)
            bboxes[map_name] = bbox
            features_map[map_name] = features
            print(f"      lon [{bbox['min_x']:.4f}, {bbox['max_x']:.4f}]  "
                  f"lat [{bbox['min_y']:.4f}, {bbox['max_y']:.4f}]  "
                  f"({len(features)} line features)")
        except Exception as e:
            print(f"  ERREUR: {e}")
            sys.exit(1)

    # 2. Preprocess maps → segment_cache_id (one per map)
    print("\n[2] Preprocess OCAD → SegmentSpatialIndex")
    cache_ids: dict[str, str | None] = {}
    async with aiohttp.ClientSession() as session:
        for map_name in needed_maps:
            print(f"  {map_name}:")
            cache_id = await _preprocess_map(session, features_map[map_name], bboxes[map_name])
            cache_ids[map_name] = cache_id

    # 3. Generate groups sequentially
    print("\n[3] Génération circuits")
    circuit_map: dict[str, str] = {}  # circuit_id → map_name

    async with aiohttp.ClientSession() as session:
        for group in datasets:
            map_name = group["map"]
            bbox = bboxes[map_name]
            seg_id = cache_ids.get(map_name)
            new_ids = await _run_group(group, bbox, session, seg_id, args.w_dist, args.w_diversity_mult)
            for cid in new_ids:
                circuit_map[cid] = map_name

    print(f"\nTotal circuit_ids trackés : {len(circuit_map)}")

    # 4. Write v2 CSV
    print(f"\n[4] Écriture {output_csv}")
    n_written = write_v2(circuit_map, output_csv)
    print(f"    {n_written} lignes écrites")

    if n_written == 0:
        print("\nWARN: 0 lignes. Vérifier INTENT_DEBUG_CSV=1 sur le backend.")
        return

    # 5. Distribution par groupe dans le v2
    print("\n[5] Distribution dans v2 CSV :")
    from collections import Counter
    counts: Counter = Counter()
    with open(output_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = f"{row.get('map_name','?')}_td{row.get('td','?')}"
            counts[key] += 1
    for k, v in sorted(counts.items()):
        print(f"    {k} : {v} legs")

    # 6. Run alignment analysis
    print(f"\n[6] Analyse fitness alignment → {OUTPUT_CSV}")
    subprocess.run([
        sys.executable,
        str(pathlib.Path(__file__).parent / "analyze_fitness_alignment.py"),
        str(OUTPUT_CSV),
    ])

    print(f"\nDone. Output : {output_csv}")


if __name__ == "__main__":
    asyncio.run(main())
