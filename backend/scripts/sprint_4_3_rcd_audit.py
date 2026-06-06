#!/usr/bin/env python3
"""
sprint_4_3_rcd_audit.py — Sprint 4.3
Validation du signal route_choice_density (RCD) sur 3 terrains.

Questions clés :
  1. RCD > 0 en urbain après fix injection route_analyzer ?
  2. RCD ≈ 0 en forêt (attendu — pas de réseau OSM) ?
  3. Corrélation RCD / fitness < 0.7 ? (sinon redondant)
  4. Corrélation RCD / cosine_distance (proxy term E) ?

Sélection :
  Urbain  — discipline="urbano", 3 cartes
  Mixte   — discipline="foresto", scale < 7500, 2 cartes
  Forêt   — discipline="foresto", scale >= 7500, 2 cartes

Usage :
    python backend/scripts/sprint_4_3_rcd_audit.py [--seed S]
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import pathlib
import random
import sys
import tempfile
import time
from typing import List, Optional, Tuple

import numpy as np

_HERE = pathlib.Path(__file__).parent
BACKEND = _HERE.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

VIKAZIMUT_INDEX = ROOT / "vikazimut" / "index.json"
OUTPUT_DIR = ROOT / "output" / "sprint_4_3"

GA_SEED = 42
N_RUNS = 3
TOP_K = 10
N_VARIANTS = 3

PLAN = {
    "urbain": {"discipline": "urbano",  "scale_min": 0,    "scale_max": 99999,
               "circuit_type": "sprint", "target_length_m": 2500, "target_controls": 10, "n": 3},
    "mixte":  {"discipline": "foresto", "scale_min": 0,    "scale_max": 7499,
               "circuit_type": "md",     "target_length_m": 3500, "target_controls": 12, "n": 2},
    "foret":  {"discipline": "foresto", "scale_min": 7500, "scale_max": 99999,
               "circuit_type": "md",     "target_length_m": 5000, "target_controls": 14, "n": 2},
}

log = logging.getLogger("sprint_4_3")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)


# ── Sélection cartes ──────────────────────────────────────────────────────────

def select_maps(seed: int = 0) -> dict[str, List[dict]]:
    with open(VIKAZIMUT_INDEX, encoding="utf-8") as f:
        entries = json.load(f)

    selected: dict[str, List[dict]] = {}
    rng = random.Random(seed)

    for terrain, spec in PLAN.items():
        pool = [
            e for e in entries
            if e.get("is_foot_o", False)
            and e.get("discipline", "") == spec["discipline"]
            and spec["scale_min"] <= e.get("scale", 0) <= spec["scale_max"]
            and (e.get("bounds") or {}).get("north") is not None
        ]
        rng.shuffle(pool)
        selected[terrain] = pool[: spec["n"]]
        log.info("Terrain %-8s : %d cartes disponibles, %d sélectionnées",
                 terrain, len(pool), len(selected[terrain]))

    return selected


# ── Caches ────────────────────────────────────────────────────────────────────

def _bbox_dict(entry: dict, spec: dict) -> dict:
    b = entry["bounds"]
    return {
        "min_x": float(b["west"]), "min_y": float(b["south"]),
        "max_x": float(b["east"]), "max_y": float(b["north"]),
        "scale": entry.get("scale", 10000),
        "discipline": entry.get("discipline", "?"),
        "circuit_type": spec["circuit_type"],
        "target_length_m": spec["target_length_m"],
        "target_controls": spec["target_controls"],
    }


def build_caches(bb: dict, bbox_tuple: tuple) -> dict:
    from src.services.terrain.osm_fetcher import extract_sprint_features
    from src.services.optimization.route_analyzer import RouteAnalyzer
    from src.services.terrain.lidar_manager import build_elevation_cache
    from src.services.learning.ocad_patch_scorer import HeatmapCache, OcadPatchScorer

    osm = extract_sprint_features(bb)
    ra = RouteAnalyzer(osm.get("highway_ways", []))
    ec = build_elevation_cache(bb)

    hmc = None
    _key = hashlib.md5(f"rcd43|{bbox_tuple}".encode()).hexdigest()[:12]
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
                        map_img=img, bbox=bbox_img, mpp=mpp, step_px=20, cnn_scorer=cnn)
                    hmc.save(_path)
        except Exception as ex:
            log.debug("HeatmapCache indisponible : %s", ex)

    n_edges = ra.graph.number_of_edges() if ra else 0
    log.info("  RouteAnalyzer: %d arêtes OSM | heatmap=%s flat=%s",
             n_edges,
             "OK" if hmc else "None",
             getattr(hmc, "is_flat_signal", "?"))

    return {"heatmap_cache": hmc, "elevation_cache": ec, "route_analyzer": ra}


# ── Génération ────────────────────────────────────────────────────────────────

def generate_circuits(bb_info: dict, caches: dict) -> Optional[List]:
    from src.services.generation.ai_generator import AIGenerator, GenerationRequest

    bb = {k: bb_info[k] for k in ("min_x", "min_y", "max_x", "max_y")}
    scale = bb_info.get("scale", 10000)
    req = GenerationRequest(
        bounding_box=bb,
        category="H21E",
        technical_level="TD3",
        target_length_m=bb_info.get("target_length_m", 5000),
        target_controls=bb_info.get("target_controls", 14),
        circuit_type=bb_info.get("circuit_type", "md"),
        map_scale=scale,
        n_runs=N_RUNS,
        top_k_per_run=TOP_K,
        ga_seed=GA_SEED,
        heatmap_cache=caches.get("heatmap_cache"),
        elevation_cache=caches.get("elevation_cache"),
        route_analyzer=caches.get("route_analyzer"),
    )
    try:
        return AIGenerator().generate(req, num_variants=N_VARIANTS)
    except Exception as e:
        log.error("  Génération échouée : %s", e)
        return None


# ── Métriques ─────────────────────────────────────────────────────────────────

def compute_metrics(circuits: List, bb_info: dict, caches: dict) -> Optional[dict]:
    from src.services.generation.profiling.course_profile import compute_course_profile
    from src.services.generation.profiling.profile_distance import (
        course_profile_vector, cosine_distance,
    )
    from src.services.generation.genetic_algo import _haversine_batch

    ra = caches.get("route_analyzer")
    hmc = caches.get("heatmap_cache")
    bb_tuple = (bb_info["min_x"], bb_info["min_y"], bb_info["max_x"], bb_info["max_y"])

    # ── Diagnostic per-variant : snapping + longueur jambes ───────────────────
    if ra is not None:
        for vi, c in enumerate(circuits[:3]):
            pts_v = [(ctrl["x"], ctrl["y"]) for ctrl in c.controls]
            arr_v = np.array(pts_v)
            legs_v = _haversine_batch(arr_v[:-1, 0], arr_v[:-1, 1], arr_v[1:, 0], arr_v[1:, 1])
            n_same = sum(
                1 for p0, p1 in zip(pts_v[:-1], pts_v[1:])
                if ra._nearest_node(p0[0], p0[1]) == ra._nearest_node(p1[0], p1[1])
            )
            log.info("  [diag] V%s: n_legs=%d mean_leg_m=%.0f n_same_node=%d",
                     "ABC"[vi] if vi < 3 else str(vi), len(pts_v) - 1,
                     float(np.mean(legs_v)), n_same)

    rcds, fitnesses, vectors = [], [], []

    for c in circuits:
        pts = [(ctrl["x"], ctrl["y"]) for ctrl in c.controls]
        arr = np.array(pts)
        try:
            legs_m = _haversine_batch(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])
            cp = compute_course_profile(
                controls=pts, legs_m=legs_m, bbox=bb_tuple,
                heatmap_cache=hmc, route_analyzer=ra,
            )
            rcds.append(cp.route_choice_density)
            fitnesses.append(float(c.score))
            vectors.append(course_profile_vector(cp))
        except Exception as e:
            log.warning("  Profile error: %s", e)

    if not rcds:
        return None

    # Distances cosinus pairwise entre variantes
    n = len(vectors)
    cos_dists = [
        cosine_distance(vectors[i], vectors[j])
        for i in range(n) for j in range(i + 1, n)
    ]
    mean_cosine = float(np.mean(cos_dists)) if cos_dists else 0.0

    return {
        "rcds": rcds,
        "fitnesses": fitnesses,
        "mean_rcd": float(np.mean(rcds)),
        "std_rcd": float(np.std(rcds)),
        "mean_cosine": mean_cosine,
        "n_circuits": len(rcds),
        "n_osm_edges": ra.graph.number_of_edges() if ra else 0,
    }


# ── Corrélations ──────────────────────────────────────────────────────────────

def _pearson(xs: List[float], ys: List[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    x, y = np.array(xs), np.array(ys)
    sx, sy = x.std(), y.std()
    if sx < 1e-9 or sy < 1e-9:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


# ── Rapport ───────────────────────────────────────────────────────────────────

def generate_report(results: List[dict]) -> str:
    valid = [r for r in results if r.get("metrics")]
    if not valid:
        return "Aucun résultat valide."

    lines = [
        "=" * 70,
        "SPRINT 4.3 — Validation RCD (route_choice_density)",
        "=" * 70,
        "",
    ]

    # ── Par terrain ──────────────────────────────────────────────────────────
    by_terrain: dict[str, list] = {}
    for r in valid:
        by_terrain.setdefault(r["terrain"], []).append(r)

    lines.append(f"  {'terrain':<8}  {'n':>2}  {'mean_rcd':>9}  {'std_rcd':>8}  {'mean_cos':>9}  {'osm_edges':>9}")
    lines.append("  " + "-" * 55)
    for terrain in ("urbain", "mixte", "foret"):
        rows = by_terrain.get(terrain, [])
        if not rows:
            continue
        all_rcd = [v for r in rows for v in r["metrics"]["rcds"]]
        all_cos = [r["metrics"]["mean_cosine"] for r in rows]
        all_edges = [r["metrics"]["n_osm_edges"] for r in rows]
        lines.append(
            f"  {terrain:<8}  {len(rows):>2}  "
            f"{np.mean(all_rcd):>9.4f}  {np.std(all_rcd):>8.4f}  "
            f"{np.mean(all_cos):>9.4f}  {int(np.mean(all_edges)):>9}"
        )

    # ── Corrélations globales ─────────────────────────────────────────────────
    all_rcd_flat = [v for r in valid for v in r["metrics"]["rcds"]]
    all_fit_flat = [v for r in valid for v in r["metrics"]["fitnesses"]]
    corr_rcd_fit = _pearson(all_rcd_flat, all_fit_flat)

    lines += [
        "",
        "CORRELATIONS (tous terrains)",
        f"  RCD / fitness     : r = {corr_rcd_fit:+.3f}",
        f"  N circuits total  : {len(all_rcd_flat)}",
        "",
    ]

    # ── Diagnostic ────────────────────────────────────────────────────────────
    urb = by_terrain.get("urbain", [])
    urb_rcd = [v for r in urb for v in r["metrics"]["rcds"]] if urb else []
    for_rows = by_terrain.get("foret", [])
    for_rcd = [v for r in for_rows for v in r["metrics"]["rcds"]] if for_rows else []

    lines.append("DIAGNOSTIC")
    if urb_rcd and np.mean(urb_rcd) > 0.02 and np.std(urb_rcd) > 0.005:
        lines.append("  → CAS A : RCD urbain > 0, variance > 0 — signal valide en urbain")
        if for_rcd and np.mean(for_rcd) < 0.01:
            lines.append("  → RCD forêt ≈ 0 — comportement attendu (pas de réseau OSM)")
        if not math.isnan(corr_rcd_fit) and abs(corr_rcd_fit) < 0.7:
            lines.append(f"  → Corrélation RCD/fitness = {corr_rcd_fit:+.3f} < 0.7 — signal non redondant ✓")
        elif not math.isnan(corr_rcd_fit):
            lines.append(f"  ⚠ Corrélation RCD/fitness = {corr_rcd_fit:+.3f} — signal potentiellement redondant")
    elif urb_rcd and np.mean(urb_rcd) > 0.02:
        lines.append("  → CAS B partiel : RCD > 0 mais variance faible — signal stable mais peu discriminant")
    else:
        lines.append("  → CAS C : RCD ≈ 0 partout — algo inadapté aux circuits produits ou OSM insuffisant")

    # ── Détail par carte ──────────────────────────────────────────────────────
    lines += ["", "DÉTAIL PAR CARTE",
              f"  {'id':>6}  {'terrain':<8}  {'scale':>6}  {'rcd_A':>6}  {'rcd_B':>6}  {'rcd_C':>6}  {'fitness_A':>9}",
              "  " + "-" * 60]
    for r in valid:
        m = r["metrics"]
        fits_s = f"{m['fitnesses'][0]:.2f}" if m["fitnesses"] else "?"
        n_real = len(m["rcds"])
        rcd_vals = m["rcds"] + [None] * (3 - n_real)
        lines.append(
            f"  {r['id']:>6}  {r['terrain']:<8}  {r['scale']:>6}"
            f"  {rcd_vals[0]:.4f}  "
            f"{'?' if rcd_vals[1] is None else f'{rcd_vals[1]:.4f}'}  "
            f"{'?' if rcd_vals[2] is None else f'{rcd_vals[2]:.4f}'}  {fits_s:>9}"
        )

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(seed: int = 0) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    maps_by_terrain = select_maps(seed)

    results = []
    for terrain, maps in maps_by_terrain.items():
        for entry in maps:
            map_id = entry["id"]
            scale = entry.get("scale", "?")
            log.info("[%s] Carte %d (scale %s)", terrain.upper(), map_id, scale)

            bb_info = _bbox_dict(entry, PLAN[terrain])
            bbox_tuple = (bb_info["min_x"], bb_info["min_y"], bb_info["max_x"], bb_info["max_y"])

            t0 = time.perf_counter()
            caches = build_caches(bb_info, bbox_tuple)
            log.info("  Caches: %.1fs", time.perf_counter() - t0)

            circuits = generate_circuits(bb_info, caches)
            if not circuits or len(circuits) < 2:
                log.warning("  Skipped (circuits insuffisants)")
                results.append({"id": map_id, "scale": scale, "terrain": terrain, "metrics": None})
                continue

            metrics = compute_metrics(circuits, bb_info, caches)
            if metrics:
                log.info("  mean_rcd=%.4f std_rcd=%.4f mean_cos=%.4f",
                         metrics["mean_rcd"], metrics["std_rcd"], metrics["mean_cosine"])
            results.append({"id": map_id, "scale": scale, "terrain": terrain, "metrics": metrics})

    report = generate_report(results)
    print("\n" + report)

    out_path = OUTPUT_DIR / "rcd_audit_report.txt"
    out_path.write_text(report + "\n", encoding="utf-8")
    log.info("Rapport : %s", out_path)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    main(args.seed)
