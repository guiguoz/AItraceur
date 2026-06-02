"""
Mesure du pipeline sprint sur bbox déjà vue (tous caches chauds).

Usage :
    cd backend
    python scripts/timing_pipeline.py

Prérequis : avoir déjà généré un sprint depuis le frontend sur la même bbox
(aitraceur_hmc_*.npz, aitraceur_elev/*.npz, aitraceur_osm/*.json présents).
"""
import sys
import os
import pathlib
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np


def _t(label: str, t0: float) -> float:
    t1 = time.perf_counter()
    print(f"  {t1 - t0:.3f}s  {label}")
    return t1


def main():
    print("=== Timing pipeline sprint — caches chauds ===\n")

    # ── 1. HeatmapCache ───────────────────────────────────────────────────────
    t = time.perf_counter()
    from src.services.learning.ocad_patch_scorer import HeatmapCache
    tmp = pathlib.Path(tempfile.gettempdir())
    hmc_files = sorted(tmp.glob("aitraceur_hmc_*.npz"), key=lambda f: f.stat().st_mtime)
    if not hmc_files:
        print("SKIP HeatmapCache : aucun fichier cache")
        hmc, bbox = None, (-0.458, 49.043, -0.433, 49.068)
    else:
        hmc = HeatmapCache.load(hmc_files[-1])
        bbox = hmc.bbox
        t = _t(f"HeatmapCache (hit)  [{hmc_files[-1].name}]", t)

    bb = {'min_x': bbox[0], 'min_y': bbox[1], 'max_x': bbox[2], 'max_y': bbox[3]}

    # ── 2. OSM fetch ─────────────────────────────────────────────────────────
    from src.services.terrain.osm_fetcher import extract_sprint_features
    t = time.perf_counter()
    osm = extract_sprint_features(bb)
    t = _t(f"OSM extract (hit)   [{len(osm['candidates'])} cand, {len(osm['highway_ways'])} ways]", t)

    # ── 3. RouteAnalyzer build ────────────────────────────────────────────────
    from src.services.optimization.route_analyzer import RouteAnalyzer
    t = time.perf_counter()
    ra = RouteAnalyzer(osm['highway_ways'])
    t = _t(f"RouteAnalyzer build [{ra.node_count} nodes]", t)

    # ── 4. ElevationCache ────────────────────────────────────────────────────
    import hashlib
    from src.services.terrain.lidar_manager import ElevationCache
    key = hashlib.md5(
        f"{bbox[0]:.5f},{bbox[1]:.5f},{bbox[2]:.5f},{bbox[3]:.5f},30,30".encode()
    ).hexdigest()[:12]
    elev_path = tmp / "aitraceur_elev" / f"{key}.npz"
    t = time.perf_counter()
    if elev_path.exists():
        d = np.load(str(elev_path))
        ec = ElevationCache(altitudes=d["altitudes"], bbox=bbox, n_rows=30, n_cols=30)
        t = _t(f"ElevationCache (hit) [{key}]", t)
    else:
        ec = None
        t = _t("ElevationCache : ABSENT (terrain plat)", t)

    # ── 5. OCAD candidate_points ─────────────────────────────────────────────
    import json as _json
    cpts_files = sorted(tmp.glob("aitraceur_cpts_*.json"), key=lambda f: f.stat().st_mtime)
    t = time.perf_counter()
    if cpts_files:
        data = _json.loads(cpts_files[-1].read_text(encoding="utf-8"))
        candidate_points = data.get("candidate_points", [])
        ocad_line_segments = data.get("ocad_line_segments", [])
        n_isom = sum(1 for cp in candidate_points if cp.get("isom"))
        t = _t(f"OCAD cpts (hit)     [{len(candidate_points)} pts, {n_isom} isom, {len(ocad_line_segments)} segs]", t)
    else:
        candidate_points, ocad_line_segments = [], []
        t = _t("OCAD cpts : ABSENT (no KDTree)", t)

    # ── 6. GA ────────────────────────────────────────────────────────────────
    from src.services.generation.genetic_algo import GeneticAlgorithm, GenerationConfig

    config = GenerationConfig(
        circuit_type='sprint',
        bounding_box=bb,
        target_length_m=2200,
        target_controls=12,
        winning_time_min=12,
        technical_level=3,
        heatmap_cache=hmc,
        elevation_cache=ec,
        route_analyzer=ra,
        candidate_points=candidate_points,
        ocad_line_segments=ocad_line_segments,
        population_size=50,
        generations=100,
    )
    min_lng, min_lat, max_lng, max_lat = bbox
    cx = (min_lng + max_lng) / 2
    cy = (min_lat + max_lat) / 2
    start = (cx - (max_lng - min_lng) * 0.2, cy)
    end   = (cx + (max_lng - min_lng) * 0.2, cy)

    t = time.perf_counter()
    ga = GeneticAlgorithm(config)
    result = ga.generate(start, end)
    n_circuits = len(result.circuits) if hasattr(result, 'circuits') else 1
    t = _t(f"GA generate         [{n_circuits} circuits, cognitive_calls={getattr(ga, '_cognitive_calls', '?')}]", t)

    # ── 7. Contrôleur simulé (validate sans réseau) ───────────────────────────
    try:
        from src.services.controleur.controleur import ControleurSprint
        best = result.circuits[0] if hasattr(result, 'circuits') and result.circuits else None
        if best:
            n = len(best.controls)
            ctrl_dicts = [
                {
                    "lng": c[0], "lat": c[1],
                    "type": "start" if i == 0 else ("finish" if i == n - 1 else "control"),
                    "order": i,
                }
                for i, c in enumerate(best.controls)
            ]
            ctrl = ControleurSprint()
            t = time.perf_counter()
            report = ctrl.validate(
                ctrl_dicts,
                oob_polygons=[],
                circuit_config={"category": "sprint", "circuit_type": "sprint"},
                route_analyzer=ra,
            )
            errors = report.error_count if hasattr(report, 'error_count') else '?'
            t = _t(f"Contrôleur validate [{errors} erreurs, RouteAnalyzer actif]", t)
    except Exception as e:
        print(f"  SKIP contrôleur : {e}")

    print("\nDone.")


if __name__ == '__main__':
    main()
