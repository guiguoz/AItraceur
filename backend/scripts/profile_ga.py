"""
Profiling GA — identifie les vrais bottlenecks avant optimisation.

Modes :
  Mode A (défaut) : sans OCAD (KDTree absent, cognitive_calls=0)
  Mode B          : avec OCAD réel sauvegardé par _sprint_impl (ou fallback synthétique)
                    → active KDTree, _build_leg_cognitive_profile, _seg_index

Usage :
    cd backend
    python scripts/profile_ga.py          # Mode A
    python scripts/profile_ga.py --modeB  # Mode B

Prérequis Mode B : générer un sprint depuis le frontend (sauvegarde auto aitraceur_cpts_*.json).
Sortie : top 40 fonctions par cumtime + callers + stats RouteAnalyzer.
Dump   : backend/ga_profile.prof  (snakeviz ga_profile.prof pour UI)
"""
import cProfile
import pstats
import io
import sys
import os
import pathlib
import tempfile
import json
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np

from src.services.learning.ocad_patch_scorer import HeatmapCache
from src.services.generation.genetic_algo import GeneticAlgorithm, GenerationConfig


def load_heatmap_cache():
    tmp = pathlib.Path(tempfile.gettempdir())
    files = sorted(tmp.glob("aitraceur_hmc_*.npz"), key=lambda f: f.stat().st_mtime)
    if not files:
        print("[profile] WARN: aucun HeatmapCache disque — mock spatial utilisé (biais possible)")
        hmc, bbox = _make_mock_heatmap()
        return hmc, bbox
    path = files[-1]
    print(f"[profile] HeatmapCache : {path.name}")
    hmc = HeatmapCache.load(path)
    print(f"[profile] bbox={hmc.bbox}")
    return hmc, hmc.bbox


def _make_mock_heatmap():
    H, W = 60, 60
    scores = np.zeros((H, W), dtype=np.float32)
    for r in range(H):
        for c in range(W):
            scores[r, c] = 0.3 + 0.5 * (r / H) * (c / W)
    bbox = (-0.390, 49.175, -0.350, 49.200)
    return HeatmapCache(scores=scores, bbox=bbox, step_px=8, map_w=512, map_h=512), bbox


def load_route_analyzer(bbox):
    try:
        from src.services.optimization.route_analyzer import RouteAnalyzer
        from src.services.terrain.osm_fetcher import extract_sprint_features
        bb = {'min_x': bbox[0], 'min_y': bbox[1], 'max_x': bbox[2], 'max_y': bbox[3]}
        osm = extract_sprint_features(bb)
        ways = osm.get("highway_ways", [])
        if ways:
            print(f"[profile] RouteAnalyzer : {len(ways)} ways OSM (cache JSON)")
            return RouteAnalyzer(ways)
        print("[profile] RouteAnalyzer : aucun way OSM trouvé")
    except Exception as e:
        print(f"[profile] RouteAnalyzer non dispo ({e})")
    return None


def load_elevation_cache(bbox):
    try:
        import hashlib
        from src.services.terrain.lidar_manager import ElevationCache
        key = hashlib.md5(
            f"{bbox[0]:.5f},{bbox[1]:.5f},{bbox[2]:.5f},{bbox[3]:.5f},30,30".encode()
        ).hexdigest()[:12]
        cache_path = pathlib.Path(tempfile.gettempdir()) / "aitraceur_elev" / f"{key}.npz"
        if cache_path.exists():
            d = np.load(str(cache_path))
            print(f"[profile] ElevationCache : {key}")
            return ElevationCache(altitudes=d["altitudes"], bbox=bbox, n_rows=30, n_cols=30)
    except Exception:
        pass
    print("[profile] ElevationCache : terrain plat (fallback)")
    return None


def load_ocad_data(bbox):
    """Charge candidate_points + ocad_line_segments depuis le cache disque sprint.

    Priorité : fichier aitraceur_cpts_*.json le plus récent (sauvegardé par _sprint_impl).
    Fallback  : données synthétiques activant le KDTree (≥20 points ISOM).
    """
    tmp = pathlib.Path(tempfile.gettempdir())
    files = sorted(tmp.glob("aitraceur_cpts_*.json"), key=lambda f: f.stat().st_mtime)
    if files:
        path = files[-1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cpts = data.get("candidate_points", [])
            segs = data.get("ocad_line_segments", [])
            n_isom = sum(1 for cp in cpts if cp.get("isom"))
            print(f"[profile] OCAD data : {path.name} — {len(cpts)} pts ({n_isom} isom), {len(segs)} segs")
            return cpts, segs
        except Exception as e:
            print(f"[profile] WARN: lecture {path.name} échouée ({e})")

    print("[profile] WARN: aucun aitraceur_cpts_*.json — données synthétiques (active KDTree, biais partiel)")
    return _make_synthetic_ocad(bbox)


def _make_synthetic_ocad(bbox):
    """Génère candidate_points + ocad_line_segments synthétiques pour activer le KDTree."""
    min_lng, min_lat, max_lng, max_lat = bbox
    rng = random.Random(42)

    ISOM_ATTRACTIVE = [101, 106, 107, 108, 113, 115, 201, 304, 401, 402, 501, 502, 503, 521, 522]
    candidate_points = [
        {
            "x": min_lng + rng.random() * (max_lng - min_lng),
            "y": min_lat + rng.random() * (max_lat - min_lat),
            "isom": rng.choice(ISOM_ATTRACTIVE),
        }
        for _ in range(80)
    ]

    # Segments synthétiques : contours E-O + chemins N-S
    segs = []
    for i in range(6):
        lat = min_lat + (i + 1) * (max_lat - min_lat) / 7
        segs.append({"p0": [min_lng, lat], "p1": [max_lng, lat], "isom_code": 101})
    for i in range(4):
        lng = min_lng + (i + 1) * (max_lng - min_lng) / 5
        segs.append({"p0": [lng, min_lat], "p1": [lng, max_lat], "isom_code": 501})

    return candidate_points, segs


def make_config(bbox, hmc, ec, ra, candidate_points=None, ocad_line_segments=None):
    return GenerationConfig(
        circuit_type='sprint',
        bounding_box={'min_x': bbox[0], 'min_y': bbox[1], 'max_x': bbox[2], 'max_y': bbox[3]},
        target_length_m=2200,
        target_controls=12,
        winning_time_min=12,
        technical_level=3,
        heatmap_cache=hmc,
        elevation_cache=ec,
        route_analyzer=ra,
        candidate_points=candidate_points or [],
        ocad_line_segments=ocad_line_segments or [],
        population_size=50,
        generations=100,
    )


def run(mode_b: bool = False):
    hmc, bbox = load_heatmap_cache()
    ra = load_route_analyzer(bbox)
    ec = load_elevation_cache(bbox)

    candidate_points, ocad_line_segments = [], []
    if mode_b:
        candidate_points, ocad_line_segments = load_ocad_data(bbox)

    config = make_config(bbox, hmc, ec, ra, candidate_points, ocad_line_segments)

    mode_label = "B (OCAD)" if mode_b else "A (sans OCAD)"
    n_isom = sum(1 for cp in candidate_points if cp.get("isom"))
    print(f"[profile] Mode {mode_label} — {len(candidate_points)} candidats ({n_isom} isom), {len(ocad_line_segments)} segs")

    # Positions départ/arrivée dérivées de la bbox
    min_lng, min_lat, max_lng, max_lat = bbox
    center_lng = (min_lng + max_lng) / 2
    center_lat = (min_lat + max_lat) / 2
    start_pos = (center_lng - (max_lng - min_lng) * 0.2, center_lat)
    end_pos   = (center_lng + (max_lng - min_lng) * 0.2, center_lat)

    # Warm-up hors profiling
    print("[profile] Warm-up (pop=10, gen=5)...")
    try:
        import dataclasses
        warmup_cfg = dataclasses.replace(config, generations=5, population_size=10)
        GeneticAlgorithm(warmup_cfg).generate(start_pos, end_pos)
    except Exception as e:
        print(f"[profile] Warm-up échoué ({e}) — profiling sans warm-up")
    print("[profile] Warm-up terminé.")

    print("[profile] Démarrage GA profilé (pop=50, gen=100)...")
    pr = cProfile.Profile()
    pr.enable()

    ga = GeneticAlgorithm(config)
    result = ga.generate(start_pos, end_pos)

    pr.disable()
    n = len(result.circuits) if hasattr(result, 'circuits') else 1
    print(f"[profile] GA terminé — {n} circuit(s)")

    if ra is not None:
        s = ra.get_cache_stats()
        print(
            f"[profile] RouteAnalyzer  hit_rate={s.get('hit_rate', 0)*100:.1f}%  "
            f"total_calls={s.get('total_calls', 0)}  "
            f"avg_miss={s.get('avg_time_ms', 0):.1f}ms"
        )

    if hasattr(ga, '_cognitive_calls'):
        print(f"[profile] cognitive_calls={ga._cognitive_calls}")

    out = io.StringIO()
    ps = pstats.Stats(pr, stream=out).sort_stats('cumulative')
    ps.print_stats(40)
    print(out.getvalue())

    out2 = io.StringIO()
    ps2 = pstats.Stats(pr, stream=out2).sort_stats('cumulative')
    ps2.print_callers(20)
    print("-- CALLERS ------------------------------------------")
    print(out2.getvalue())

    dump_path = pathlib.Path(__file__).parent.parent / "ga_profile.prof"
    pr.dump_stats(str(dump_path))
    print(f"[profile] Dump : {dump_path}")
    print("[profile] Visualiser : pip install snakeviz && snakeviz ga_profile.prof")


if __name__ == '__main__':
    run(mode_b='--modeB' in sys.argv)
