#!/usr/bin/env python3
"""
generate_intent_legs.py — STEP A
Génère output/intent_legs_<map>.csv pour les 5 cartes benchmark.
Produit ~45 jambes/carte (3 conditions × ~15 jambes) avec features LRI + PC1.

Sorties :
  output/intent_legs_airelles.csv
  output/intent_legs_llose.csv
  output/intent_legs_caen.csv
  output/intent_legs_langrune.csv
  output/intent_legs_bayeux.csv

Usage :
  python backend/scripts/generate_intent_legs.py
  python backend/scripts/generate_intent_legs.py --maps airelles llose
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

try:
    from shapely.geometry import Point, shape
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


def _point_in_polygon(lng: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _build_oob_checker(oob_features: list):
    if not oob_features:
        return lambda lng, lat: False
    if _HAS_SHAPELY:
        from shapely.validation import make_valid
        polys = []
        for f in oob_features:
            try:
                g = make_valid(shape(f["geometry"]))
                if not g.is_empty:
                    polys.append(g)
            except Exception:
                pass
        if not polys:
            return lambda lng, lat: False
        combined = unary_union(polys)
        return lambda lng, lat: combined.contains(Point(lng, lat))
    else:
        rings = []
        for f in oob_features:
            geom = f.get("geometry", {})
            if geom.get("type") == "Polygon":
                rings.append(geom["coordinates"][0])
            elif geom.get("type") == "MultiPolygon":
                for poly in geom["coordinates"]:
                    rings.append(poly[0])
        if not rings:
            return lambda lng, lat: False
        return lambda lng, lat: any(_point_in_polygon(lng, lat, r) for r in rings)

_SCRIPT  = pathlib.Path(__file__).parent
_BACKEND = _SCRIPT.parent
_ROOT    = _BACKEND.parent

sys.path.insert(0, str(_BACKEND / "src"))

from services.generation.genetic_algo import GeneticAlgorithm, GenerationConfig
from services.generation.lri_model import get_lri_model
from services.generation.perceptual_model import build_segment_index
from services.ocad.geojson_extractor import extract_line_segments

# ── Constantes GA (identiques à benchmark_lri.py) ────────────────────────────

POP_SIZE = 30
GENS     = 40
SEED     = 0

TD_FOREST   = 4
DIST_FOREST = 6000
CTRL_FOREST = 15
CT_FOREST   = "ld"

TD_SPRINT   = 2
DIST_SPRINT = 2500
CTRL_SPRINT = 20
CT_SPRINT   = "sprint"

LRI_WEIGHT_B = 5.0

CONDITIONS = [
    ("A",          None,         0.0),
    ("B-open",     "open",       LRI_WEIGHT_B),
    ("B-handrail", "handrail",   LRI_WEIGHT_B),
]

# ── Cartes ────────────────────────────────────────────────────────────────────

MAPS: dict[str, dict] = {
    "airelles": {
        "ocd":    r"E:\RunningRaid\Cartographie\fichiers OCAD et jpg\O18_PPOAirelles 2019_2.ocd",
        "sprint": False,
    },
    "llose": {
        "ocd":    r"E:\RunningRaid\Cartographie\fichiers OCAD et jpg\La Llose 28-07-17.ocd",
        "sprint": False,
    },
    "caen": {
        "ocd":    r"E:\Vikazim\AItraceur\xml\CLsprint\14-Caen-FolieCouvrechef-4000-MASTER-2024-07-31-c.ocd",
        "sprint": True,
    },
    "langrune": {
        "ocd":    r"E:\RunningRaid\Cartographie\carto Langrune\matinée CMJ\4000_langrune13_05_25.ocd",
        "sprint": True,
    },
    "bayeux": {
        "ocd":    r"E:\RunningRaid\Cartographie\entrainements Vikazim\Bayeux - Octobre 2025\O20_2023-bayeux-2203.ocd",
        "sprint": True,
    },
}

OUTPUT_DIR = _ROOT / "output"

# ── Node.js OCD parser (réplique exacte de benchmark_lri.py) ─────────────────

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
    const bbox = [p(xs, 0.05), p(ys, 0.05), p(xs, 0.95), p(ys, 0.95)];
    const lineFeats = allFeatures.filter(f =>
        f.geometry && (f.geometry.type === 'LineString' || f.geometry.type === 'MultiLineString')
    );
    const OOB_SYMS = new Set([709000, 709001, 709002, 520000, 520001, 520002]);
    const oobFeats = allFeatures.filter(f =>
        f.geometry &&
        (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') &&
        f.properties && OOB_SYMS.has(f.properties.sym)
    );
    console.log(JSON.stringify({ bbox, features: lineFeats, oob_polygons: oobFeats }));
})().catch(e => { process.stderr.write(e.message + '\n'); process.exit(1); });
"""


def _parse_ocd(ocd_path: str) -> tuple[dict, list, list]:
    tile_dir = _BACKEND / "tile-service"
    tmp = tile_dir / "_generate_intent_tmp.js"
    tmp.write_text(_NODE_EXTRACT, encoding="utf-8")
    try:
        r = subprocess.run(
            ["node", str(tmp), ocd_path],
            capture_output=True, text=True, cwd=str(tile_dir), timeout=60,
        )
    finally:
        tmp.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"node parse failed: {r.stderr[:400]}")
    result = json.loads(r.stdout.strip())
    raw_bbox = result["bbox"]
    min_lon, min_lat, max_lon, max_lat = raw_bbox
    bbox = {
        "min_x": min_lon,
        "max_x": max_lon,
        "min_y": min_lat,
        "max_y": max_lat,
    }
    return bbox, result.get("features", []), result.get("oob_polygons", [])


def _circuit_id(controls: list) -> str:
    return hashlib.md5(
        str([(round(c[0], 5), round(c[1], 5)) for c in controls]).encode()
    ).hexdigest()[:10]


FIELDS = [
    "map_name", "condition", "circuit_id", "leg_index", "leg_m",
    "start_lat", "start_lon", "end_lat", "end_lon",
    "pc1", "pc2", "decision_pressure",
    "parallel_affordance", "crossing_density", "exit_clarity", "contour_crossing_guidance",
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT", "DIRECT_RISK_RUN",
    "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
    "circuit_fitness",   # métrique circuit-niveau répétée par jambe — ne pas utiliser comme prédicteur per-leg
]


def process_map(map_name: str, cfg: dict, lri, seg_index, bbox: dict, center: tuple,
                oob_check=None) -> list[dict]:
    is_sprint = cfg["sprint"]
    td        = TD_SPRINT if is_sprint else TD_FOREST
    target_m  = DIST_SPRINT if is_sprint else DIST_FOREST
    n_ctrl    = CTRL_SPRINT if is_sprint else CTRL_FOREST
    ct_type   = CT_SPRINT if is_sprint else CT_FOREST

    rows: list[dict] = []

    for cond_label, latent_regime, lri_weight in CONDITIONS:
        print(f"    {cond_label}... ", end="", flush=True)

        ga_cfg = GenerationConfig(
            bounding_box=bbox,
            target_length_m=target_m,
            target_controls=n_ctrl,
            circuit_type=ct_type,
            technical_level=td,
            population_size=POP_SIZE,
            generations=GENS,
            heatmap_cache=None,
            elevation_cache=None,
            route_analyzer=None,
            segment_index=seg_index,
            ga_seed=SEED,
            latent_regime=latent_regime,
            latent_regime_weight=lri_weight,
            benchmark_mode=True,
            timeout_seconds=120.0,
        )

        ga = GeneticAlgorithm(ga_cfg)
        ga.generate(center, center)

        best = ga.best_solution
        if best is None:
            print("WARN: no best_solution")
            continue

        cid    = _circuit_id(best.controls)
        n_legs = len(best.controls) - 1
        print(f"{n_legs} jambes brutes  fitness={best.fitness:.1f}")

        oob_skipped = 0
        for i in range(n_legs):
            lng0, lat0 = best.controls[i]
            lng1, lat1 = best.controls[i + 1]

            if oob_check and (oob_check(lng0, lat0) or oob_check(lng1, lat1)):
                oob_skipped += 1
                continue

            m_per_lat = 111000.0
            cos_lat   = math.cos(math.radians((lat0 + lat1) / 2))
            m_per_lng = 111000.0 * cos_lat
            leg_m     = math.sqrt(
                ((lng1 - lng0) * m_per_lng) ** 2 + ((lat1 - lat0) * m_per_lat) ** 2
            )

            result = ga._build_leg_cognitive_profile(lng0, lat0, lng1, lat1, None)
            if not isinstance(result, tuple):
                continue   # _seg_index absent (ne devrait pas arriver si seg_index fourni)
            cog, _, _ = result
            nav = cog.navigation_evidence

            features_10 = np.array([
                cog.parallel_affordance,
                cog.crossing_density,
                cog.exit_clarity,
                cog.contour_crossing_guidance,
                nav["HANDRAIL_FOLLOW"],
                nav["LINE_CROSSING"],
                nav["ATTACK_POINT"],
                nav["DIRECT_RISK_RUN"],
                nav["RELIEF_CROSSING_GUIDANCE"],
                nav["SAFETY_RECOVERY"],
            ], dtype=float)

            pc1, pc2 = lri.project(features_10)
            dp = abs(nav["SAFETY_RECOVERY"]) + abs(nav["ATTACK_POINT"])

            rows.append({
                "map_name":   map_name,
                "condition":  cond_label,
                "circuit_id": cid,
                "leg_index":  i,
                "leg_m":      round(leg_m, 1),
                "start_lat":  round(lat0, 6),
                "start_lon":  round(lng0, 6),
                "end_lat":    round(lat1, 6),
                "end_lon":    round(lng1, 6),
                "pc1":        round(float(pc1), 4),
                "pc2":        round(float(pc2), 4),
                "decision_pressure": round(float(dp), 4),
                "parallel_affordance":       round(float(cog.parallel_affordance), 4),
                "crossing_density":          round(float(cog.crossing_density), 4),
                "exit_clarity":              round(float(cog.exit_clarity), 4),
                "contour_crossing_guidance": round(float(cog.contour_crossing_guidance), 4),
                "HANDRAIL_FOLLOW":           round(float(nav["HANDRAIL_FOLLOW"]), 4),
                "LINE_CROSSING":             round(float(nav["LINE_CROSSING"]), 4),
                "ATTACK_POINT":              round(float(nav["ATTACK_POINT"]), 4),
                "DIRECT_RISK_RUN":           round(float(nav["DIRECT_RISK_RUN"]), 4),
                "RELIEF_CROSSING_GUIDANCE":  round(float(nav["RELIEF_CROSSING_GUIDANCE"]), 4),
                "SAFETY_RECOVERY":           round(float(nav["SAFETY_RECOVERY"]), 4),
                "circuit_fitness":            round(float(best.fitness), 4),
            })
        if oob_skipped:
            print(f"    → {oob_skipped} jambes ignorées (OOB)")

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    MAPS_DEFAULT = [m for m in MAPS if m != "langrune"]  # langrune: 100% OOB en mode benchmark
    parser.add_argument("--maps", nargs="*", default=MAPS_DEFAULT, choices=list(MAPS),
                        help="Cartes à traiter (défaut: toutes sauf langrune)")
    args = parser.parse_args()

    lri = get_lri_model()
    if lri is None:
        sys.exit("[ERROR] LRI model introuvable (lri_baseline.json manquant)")

    isom_sem_path = _BACKEND / "src" / "services" / "knowledge_base" / "isom_semantics.json"
    isom_sem: dict = json.loads(isom_sem_path.read_text(encoding="utf-8")) if isom_sem_path.exists() else {}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for map_name in args.maps:
        cfg = MAPS[map_name]
        print(f"\n{'='*60}")
        print(f"  Carte : {map_name}  ({'sprint' if cfg['sprint'] else 'forêt'})")
        print(f"{'='*60}")

        print(f"  Parsing OCD... ", end="", flush=True)
        bbox, features, oob_polygons = _parse_ocd(cfg["ocd"])
        center_lat = (bbox["min_y"] + bbox["max_y"]) / 2
        center_lon = (bbox["min_x"] + bbox["max_x"]) / 2
        center     = (center_lon, center_lat)
        print(f"center=({center_lat:.4f}, {center_lon:.4f})")

        segments  = extract_line_segments(features, center_lat=center_lat)
        seg_index = build_segment_index(segments, isom_sem, center_lat)
        print(f"  seg_index : {seg_index.segment_count} segments")
        oob_check = _build_oob_checker(oob_polygons)
        if oob_polygons:
            print(f"  OOB zones : {len(oob_polygons)} polygones")

        rows = process_map(map_name, cfg, lri, seg_index, bbox, center, oob_check)

        if not rows:
            print(f"  [WARN] Aucune jambe générée")
            continue

        out_path = OUTPUT_DIR / f"intent_legs_{map_name}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        pc1_vals = [r["pc1"] for r in rows]
        print(f"  → {out_path}")
        print(f"     {len(rows)} jambes  PC1=[{min(pc1_vals):.2f}, {max(pc1_vals):.2f}]")

    print("\nDone.")


if __name__ == "__main__":
    main()
