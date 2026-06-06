#!/usr/bin/env python3
"""
sprint_4_1_forest_audit.py — Sprint 4.1
Mini Atlas forêt : classification A/B/C de la diversification inter-runs.

Pour 15 cartes forêt (scale >= 7500, foot-o), mesure :
  - mean_cosine inter-runs (avec vecteur 15D Sprint 4)
  - distance géographique entre centres A/B/C
  - déduplication : combien de circuits uniques

Classification :
  A : mean_cosine > 0.01  → diversité naturelle
  B : 0.005–0.01          → diversité partielle
  C : < 0.005             → convergence totale

Décision post-audit :
  < 10 % classe C → 10905 est un cas limite, arrêt du seeding géo
  30–50 % classe C → Sprint 4.2 : seeding géographique asymétrique

Usage :
    python backend/scripts/sprint_4_1_forest_audit.py [--n N] [--seed S]
"""

from __future__ import annotations

import json
import logging
import pathlib
import random
import sys
import time
from typing import List, Optional

import numpy as np

# ── Chemins ───────────────────────────────────────────────────────────────────
_HERE = pathlib.Path(__file__).parent
BACKEND = _HERE.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

VIKAZIMUT_INDEX = ROOT / "vikazimut" / "index.json"
OUTPUT_DIR = ROOT / "output" / "sprint_4_1"

N_SAMPLE = 15      # cartes à auditer
GA_SEED = 42
N_RUNS = 3
TOP_K = 10

THRESHOLDS = {"A": 0.010, "B": 0.005}  # mean_cosine seuils

log = logging.getLogger("sprint_4_1")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)


# ── Sélection cartes forêt ────────────────────────────────────────────────────

def select_forest_maps(n: int, seed: int = 0) -> List[dict]:
    """Retourne n cartes forêt (scale >= 7500, foot-o, bounds valides), spread par scale."""
    with open(VIKAZIMUT_INDEX, encoding="utf-8") as f:
        entries = json.load(f)

    forest = [
        e for e in entries
        if e.get("is_foot_o", False)
        and e.get("scale", 0) >= 7500
        and e.get("discipline") == "foresto"
        and (e.get("bounds") or {}).get("north") is not None
    ]

    # Spread par scale pour couvrir plusieurs types de forêt
    by_scale: dict = {}
    for e in forest:
        by_scale.setdefault(e["scale"], []).append(e)

    rng = random.Random(seed)
    selected = []
    scales_sorted = sorted(by_scale.keys())
    while len(selected) < n:
        for s in scales_sorted:
            pool = by_scale[s]
            if pool:
                selected.append(rng.choice(pool))
                if len(selected) >= n:
                    break
        else:
            break  # plus assez de cartes

    return selected[:n]


# ── Helpers réutilisés depuis sprint_3_5b_visual ─────────────────────────────

def _bbox_dict(entry: dict) -> dict:
    b = entry["bounds"]
    return {
        "min_x": float(b["west"]),
        "min_y": float(b["south"]),
        "max_x": float(b["east"]),
        "max_y": float(b["north"]),
        "scale": entry.get("scale", 10000),
        "discipline": entry.get("discipline", "?"),
    }


def build_caches(bb: dict, bbox_tuple: tuple) -> dict:
    import hashlib, tempfile
    from src.services.terrain.osm_fetcher import extract_sprint_features
    from src.services.optimization.route_analyzer import RouteAnalyzer
    from src.services.terrain.lidar_manager import build_elevation_cache
    from src.services.learning.ocad_patch_scorer import HeatmapCache, OcadPatchScorer

    osm = extract_sprint_features(bb)
    ra = RouteAnalyzer(osm.get("highway_ways", []))
    ec = build_elevation_cache(bb)

    hmc = None
    _key = hashlib.md5(f"audit|{bbox_tuple}|cnn".encode()).hexdigest()[:12]
    _path = pathlib.Path(tempfile.gettempdir()) / f"aitraceur_hmc_{_key}"
    if _path.with_suffix(".npz").exists():
        hmc = HeatmapCache.load(_path)
    else:
        try:
            from scripts.atlas_generation import _fetch_mapant_image
            result = _fetch_mapant_image(bb)
            if result is not None:
                img, bbox_img, mpp = result
                try:
                    from src.services.learning.ocad_patch_scorer import CnnPatchScorer
                    cnn = CnnPatchScorer.load()
                except Exception:
                    cnn = None
                scorer = OcadPatchScorer.load()
                if scorer:
                    hmc = scorer.build_heatmap_cache(
                        map_img=img, bbox=bbox_img, mpp=mpp,
                        step_px=20, cnn_scorer=cnn,
                    )
                    hmc.save(_path)
        except Exception as ex:
            log.debug("HeatmapCache indisponible : %s", ex)

    return {"heatmap_cache": hmc, "elevation_cache": ec, "route_analyzer": ra}


def generate_abc(bb_info: dict, caches: dict) -> Optional[List]:
    from src.services.generation.ai_generator import AIGenerator, GenerationRequest

    bb = {k: bb_info[k] for k in ("min_x", "min_y", "max_x", "max_y")}
    scale = bb_info.get("scale", 10000)
    req = GenerationRequest(
        bounding_box=bb,
        category="H21E",
        technical_level="TD3",
        target_length_m=5000,
        target_controls=14,
        circuit_type="md",
        map_scale=scale,
        n_runs=N_RUNS,
        top_k_per_run=TOP_K,
        ga_seed=GA_SEED,
        heatmap_cache=caches.get("heatmap_cache"),
        elevation_cache=caches.get("elevation_cache"),
        route_analyzer=caches.get("route_analyzer"),
    )
    gen = AIGenerator()
    try:
        return gen.generate(req, num_variants=3)
    except Exception as e:
        log.error("  Génération échouée : %s", e)
        return None


# ── Métriques ─────────────────────────────────────────────────────────────────

def compute_metrics(circuits: List, bb_info: dict, heatmap_cache=None) -> dict:
    """Retourne mean_cosine, geo_dist, n_unique, et détail par variante."""
    from src.services.generation.profiling.course_profile import compute_course_profile
    from src.services.generation.profiling.profile_distance import (
        course_profile_vector, cosine_distance,
    )
    from src.services.generation.genetic_algo import _haversine_batch

    bb_tuple = (
        bb_info["min_x"], bb_info["min_y"],
        bb_info["max_x"], bb_info["max_y"],
    )

    profiles = []
    centers = []
    for c in circuits:
        pts = [(ctrl["x"], ctrl["y"]) for ctrl in c.controls]
        arr = np.array(pts)
        legs_m = _haversine_batch(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])
        cp = compute_course_profile(
            controls=pts, legs_m=legs_m, bbox=bb_tuple,
            heatmap_cache=heatmap_cache,
        )
        profiles.append(course_profile_vector(cp))
        # Centre géographique des postes internes (hors départ/arrivée)
        inner = pts[1:-1] if len(pts) > 2 else pts
        centers.append((
            float(np.mean([p[0] for p in inner])),
            float(np.mean([p[1] for p in inner])),
        ))

    # Distances cosinus pairwise
    n = len(profiles)
    cos_dists = [
        cosine_distance(profiles[i], profiles[j])
        for i in range(n) for j in range(i + 1, n)
    ]
    mean_cosine = float(np.mean(cos_dists)) if cos_dists else 0.0

    # Distance géographique pairwise (degrés → km approximatif)
    geo_dists_km = []
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            dlng = (centers[i][0] - centers[j][0]) * 111.0 * np.cos(np.radians(centers[i][1]))
            dlat = (centers[i][1] - centers[j][1]) * 111.0
            geo_dists_km.append(float(np.sqrt(dlng**2 + dlat**2)))
    mean_geo_km = float(np.mean(geo_dists_km)) if geo_dists_km else 0.0

    # Nombre de circuits uniques (cosinus > seuil)
    n_unique = 1
    for i in range(1, n):
        if any(cosine_distance(profiles[i], profiles[j]) > 0.0002 for j in range(i)):
            n_unique += 1

    # Classe A/B/C
    if mean_cosine >= THRESHOLDS["A"]:
        cls = "A"
    elif mean_cosine >= THRESHOLDS["B"]:
        cls = "B"
    else:
        cls = "C"

    # geo_center des variantes (dims 11-12 du vecteur 15D)
    geo_cx = [float(p[11]) if len(p) > 11 else 0.5 for p in profiles]
    geo_cy = [float(p[12]) if len(p) > 12 else 0.5 for p in profiles]

    return {
        "mean_cosine": mean_cosine,
        "mean_geo_km": mean_geo_km,
        "n_unique": n_unique,
        "class": cls,
        "geo_cx": geo_cx,
        "geo_cy": geo_cy,
    }


# ── Rapport ────────────────────────────────────────────────────────────────────

def generate_report(results: List[dict]) -> str:
    valid = [r for r in results if r.get("metrics")]
    if not valid:
        return "Aucun résultat valide."

    counts = {"A": 0, "B": 0, "C": 0}
    for r in valid:
        counts[r["metrics"]["class"]] += 1

    pct = {k: v / len(valid) * 100 for k, v in counts.items()}

    lines = [
        "=" * 70,
        f"SPRINT 4.1 — Mini Atlas Forêt ({len(valid)}/{len(results)} cartes valides)",
        "=" * 70,
        "",
        "DISTRIBUTION DES CLASSES",
        f"  A (mean_cosine > 0.010) : {counts['A']:3d} cartes ({pct['A']:5.1f}%) — diversité naturelle",
        f"  B (0.005–0.010)          : {counts['B']:3d} cartes ({pct['B']:5.1f}%) — diversité partielle",
        f"  C (< 0.005)              : {counts['C']:3d} cartes ({pct['C']:5.1f}%) — convergence totale",
        "",
        "DECISION",
    ]

    if pct["C"] < 10.0:
        lines.append("  → < 10 % classe C : 10905 est un cas limite. ARRÊT du seeding géo.")
    elif pct["C"] >= 30.0:
        lines.append("  → >= 30 % classe C : Sprint 4.2 justifié — seeding géographique asymétrique.")
    else:
        lines.append("  → 10–30 % classe C : zone grise. Décision à faire selon criticité produit.")

    lines += [
        "",
        "DÉTAIL PAR CARTE",
        f"  {'id':>6}  {'scale':>6}  {'cos':>8}  {'geo_km':>7}  {'uniq':>5}  {'cls':>3}  {'geo_cx A/B/C'}",
        "  " + "-" * 65,
    ]
    for r in valid:
        m = r["metrics"]
        cx_str = "/".join(f"{x:.2f}" for x in m.get("geo_cx", []))
        lines.append(
            f"  {r['id']:>6}  {r['scale']:>6}  {m['mean_cosine']:>8.4f}  "
            f"{m['mean_geo_km']:>7.3f}  {m['n_unique']:>5}  {m['class']:>3}  {cx_str}"
        )

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main(n_sample: int = N_SAMPLE, seed: int = 0) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    maps = select_forest_maps(n_sample, seed=seed)
    log.info("Audit sur %d cartes forêt (scale >= 7500)", len(maps))

    results = []
    for i, entry in enumerate(maps):
        map_id = entry["id"]
        scale = entry.get("scale", "?")
        log.info("[%d/%d] Carte %d (scale %s)", i + 1, len(maps), map_id, scale)

        bb_info = _bbox_dict(entry)
        bbox_tuple = (bb_info["min_x"], bb_info["min_y"], bb_info["max_x"], bb_info["max_y"])

        t0 = time.perf_counter()
        caches = build_caches(bb_info, bbox_tuple)
        log.info("  Caches: %.1fs | heatmap=%s flat=%s",
                 time.perf_counter() - t0,
                 "OK" if caches.get("heatmap_cache") else "None",
                 getattr(caches.get("heatmap_cache"), "is_flat_signal", "?"))

        circuits = generate_abc(bb_info, caches)
        if not circuits or len(circuits) < 2:
            log.warning("  Skipped (pas assez de circuits)")
            results.append({"id": map_id, "scale": scale, "metrics": None})
            continue

        metrics = compute_metrics(circuits, bb_info, caches.get("heatmap_cache"))
        log.info("  mean_cosine=%.4f geo_km=%.3f unique=%d class=%s",
                 metrics["mean_cosine"], metrics["mean_geo_km"],
                 metrics["n_unique"], metrics["class"])
        results.append({"id": map_id, "scale": scale, "metrics": metrics})

    report = generate_report(results)
    print("\n" + report)

    out_path = OUTPUT_DIR / "forest_audit_report.txt"
    out_path.write_text(report + "\n", encoding="utf-8")
    log.info("Rapport : %s", out_path)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=N_SAMPLE)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    main(args.n, args.seed)
