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

import asyncio
import csv
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

try:
    import aiohttp
except ImportError:
    print("pip install aiohttp"); sys.exit(1)

try:
    from pyproj import Transformer
except ImportError:
    print("pip install pyproj"); sys.exit(1)

# ─── Config ──────────────────────────────────────────────────────────────────

OCD_PATHS = {
    "stanne": r"E:\RunningRaid\2024-2025\entrainement 020325\La Route de Ste Anne II_v4.ocd",
    "crohot": r"E:\RunningRaid\Cartographie\fichiers OCAD et jpg  ISOM2017 Grand-Crohot Sud 15000.ocd",
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
]
V2_FIELDS = ["map_name"] + _GLOBAL_FIELDS

# ─── OCD parsing ─────────────────────────────────────────────────────────────

_NODE_EXTRACT = r"""
const fs  = require('fs');
const ocd = require('ocad2geojson');
const buf = fs.readFileSync(process.argv[2]);
ocd.ocadToGeoJson(buf).then(gj => {
    const pts = [];
    function walk(g) {
        if (!g) return;
        if (g.type === 'Point') pts.push(g.coordinates);
        else if (g.type === 'LineString') g.coordinates.forEach(c => pts.push(c));
        else if (g.type === 'Polygon') g.coordinates.forEach(r => r.forEach(c => pts.push(c)));
        else if (g.type === 'MultiPolygon') g.coordinates.forEach(p => p.forEach(r => r.forEach(c => pts.push(c))));
    }
    (gj.features || []).forEach(f => walk(f.geometry));
    console.log(JSON.stringify(pts));
}).catch(e => { process.stderr.write(e.message + '\n'); process.exit(1); });
"""


def parse_ocd_bbox(ocd_path: str) -> dict:
    """OCD → Lambert-93 via Node/ocad2geojson → WGS84 bbox via pyproj."""
    tile_dir = pathlib.Path(__file__).parent.parent / "tile-service"
    import tempfile as _tf
    with _tf.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8") as _f:
        _f.write(_NODE_EXTRACT)
        tmp = pathlib.Path(_f.name)
    try:
        r = subprocess.run(
            ["node", str(tmp), ocd_path],
            capture_output=True, text=True, cwd=str(tile_dir), timeout=30
        )
    finally:
        tmp.unlink(missing_ok=True)

    if r.returncode != 0:
        raise RuntimeError(f"node parse failed: {r.stderr[:300]}")

    raw_coords = json.loads(r.stdout.strip())
    if not raw_coords:
        raise ValueError(f"Aucune coordonnée dans {ocd_path}")

    tr = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    lons, lats = [], []
    for x, y in raw_coords:
        lon, lat = tr.transform(x, y)
        if -180 < lon < 180 and -90 < lat < 90:
            lons.append(lon)
            lats.append(lat)

    if not lons:
        raise ValueError(f"Aucune coordonnée WGS84 valide depuis {ocd_path}")

    margin = 0.001
    return {
        "min_x": min(lons) - margin,
        "max_x": max(lons) + margin,
        "min_y": min(lats) - margin,
        "max_y": max(lats) + margin,
    }


# ─── Circuit generation ───────────────────────────────────────────────────────

def _body(bbox: dict, td: int) -> dict:
    return {
        "bounding_box":    bbox,
        "technical_level": f"TD{td}",
        "circuit_type":    CT_TYPE[td],
        "target_length_m": DISTANCES[td],
        "target_controls": CONTROLS[td],
        "method":          "hybrid",
        "num_variants":    1,
        "force_mode":      "forest",
    }


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


async def _one(session: aiohttp.ClientSession, bbox: dict, td: int, idx: int) -> bool:
    try:
        async with session.post(
            f"{BASE_URL}/api/v1/generation/generate-circuit",
            json=_body(bbox, td),
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
    group: dict, bbox: dict, session: aiohttp.ClientSession
) -> set:
    name, td, n = group["name"], group["td"], group["n_each"]
    print(f"\n{'=' * 50}")
    print(f"Groupe {name} : {n} circuits TD{td}")

    before = _snapshot(GLOBAL_CSV)
    sem = asyncio.Semaphore(MAX_PARALLEL)

    async def bounded(idx: int) -> bool:
        async with sem:
            return await _one(session, bbox, td, idx)

    results = await asyncio.gather(*[bounded(i) for i in range(n)])
    ok = sum(results)
    print(f"  → {ok}/{n} OK")

    # Laisser le temps aux workers backend de terminer les écritures CSV
    await asyncio.sleep(3)
    after = _snapshot(GLOBAL_CSV)
    new_ids = after - before
    print(f"  → {len(new_ids)} circuit_ids nouveaux")
    return new_ids


# ─── Output CSV ───────────────────────────────────────────────────────────────

def write_v2(circuit_map: dict) -> int:
    """Lit le global CSV, filtre + enrichit, écrit v2. Retourne nb lignes."""
    if not GLOBAL_CSV.exists():
        print(f"WARN: {GLOBAL_CSV} introuvable — INTENT_DEBUG_CSV=1 actif ?")
        return 0

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(GLOBAL_CSV, newline="", encoding="utf-8") as fin, \
         open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fout:

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
    print("=== A.8b collect_fitness_data.py ===\n")

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
    if not os.environ.get("INTENT_DEBUG_CSV"):
        print("WARN: INTENT_DEBUG_CSV non défini localement — vérifier que le backend a cette var.")

    # 1. Parse OCD bboxes
    print("\n[1] Parse cartes OCD → WGS84 bbox")
    bboxes: dict[str, dict] = {}
    for map_name, ocd_path in OCD_PATHS.items():
        print(f"  {map_name}: {pathlib.Path(ocd_path).name}")
        try:
            bbox = parse_ocd_bbox(ocd_path)
            bboxes[map_name] = bbox
            print(f"      lon [{bbox['min_x']:.4f}, {bbox['max_x']:.4f}]  "
                  f"lat [{bbox['min_y']:.4f}, {bbox['max_y']:.4f}]")
        except Exception as e:
            print(f"  ERREUR: {e}")
            sys.exit(1)

    # 2. Generate groups sequentially
    print("\n[2] Génération circuits")
    circuit_map: dict[str, str] = {}  # circuit_id → map_name

    async with aiohttp.ClientSession() as session:
        for group in DATASETS:
            bbox = bboxes[group["map"]]
            new_ids = await _run_group(group, bbox, session)
            for cid in new_ids:
                circuit_map[cid] = group["map"]

    print(f"\nTotal circuit_ids trackés : {len(circuit_map)}")

    # 3. Write v2 CSV
    print(f"\n[3] Écriture {OUTPUT_CSV}")
    n_written = write_v2(circuit_map)
    print(f"    {n_written} lignes écrites")

    if n_written == 0:
        print("\nWARN: 0 lignes. Vérifier INTENT_DEBUG_CSV=1 sur le backend.")
        return

    # 4. Distribution par groupe dans le v2
    print("\n[4] Distribution dans v2 CSV :")
    from collections import Counter
    counts: Counter = Counter()
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = f"{row.get('map_name','?')}_td{row.get('td','?')}"
            counts[key] += 1
    for k, v in sorted(counts.items()):
        print(f"    {k} : {v} legs")

    # 5. Run alignment analysis
    print(f"\n[5] Analyse fitness alignment → {OUTPUT_CSV}")
    subprocess.run([
        sys.executable,
        str(pathlib.Path(__file__).parent / "analyze_fitness_alignment.py"),
        str(OUTPUT_CSV),
    ])

    print(f"\nDone. Output : {OUTPUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
