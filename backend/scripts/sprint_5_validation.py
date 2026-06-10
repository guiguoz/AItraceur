#!/usr/bin/env python3
"""
sprint_5_validation.py — Sprint 5 : Validation humaine des variantes A/B/C

Pour les 30 cartes Atlas, génère A/B/C et mesure :
  - cosinus inter-variantes (diversité automatique)
  - fitness A/B/C (régression vs baseline Sprint 3)
  - labels Couche 1 (A choix, Exploratoire, Rythme, ...)
  - zone_coverage / zone_diversity (Couche 0)
  - scenario (Couche 2 : standard / concentré / traversée / traversée_contrastée)

Sorties dans output/sprint_5/ :
  - sprint_5_metrics.csv     : métriques quantitatives par carte et variante
  - sprint_5_report.txt      : rapport textuel avec verdicts techniques
  - sprint_5_review_grid.csv : grille vierge pour évaluation par les traceurs

Usage :
    python backend/scripts/sprint_5_validation.py [--n N] [--seed S] [--rebuild]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import pathlib
import sys
import tempfile
import time
from collections import Counter
from typing import List, Optional

import numpy as np

# ── Chemins ───────────────────────────────────────────────────────────────────
_HERE = pathlib.Path(__file__).parent
BACKEND = _HERE.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

ATLAS_CSV = ROOT / "output" / "atlas" / "atlas_results.csv"
VIZ_INDEX = ROOT / "vikazimut" / "index.json"
OUTPUT_DIR = ROOT / "output" / "sprint_5"

# ── Paramètres ────────────────────────────────────────────────────────────────
GA_SEED = 42
N_RUNS = 3
TOP_K = 10

# Paramètres GA selon le terrain
_GEN_PARAMS = {
    "urbano": dict(
        circuit_type="sprint",
        target_length_m=3000,
        target_controls=15,
        map_scale=4000,
    ),
    "foresto": dict(
        circuit_type="md",
        target_length_m=5000,
        target_controls=14,
        map_scale=10000,
    ),
}

log = logging.getLogger("sprint5")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)


# ── Chargement des données ────────────────────────────────────────────────────

def load_atlas_ids() -> list[int]:
    """Retourne les bbox_ids uniques présents dans atlas_results.csv."""
    ids: set[int] = set()
    with open(ATLAS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ids.add(int(row["bbox_id"]))
    return sorted(ids)


def load_vikazimut_index(atlas_ids: list[int]) -> dict[int, dict]:
    """Retourne {id: entry} pour les entrées foot-o présentes dans atlas_ids."""
    with open(VIZ_INDEX, encoding="utf-8") as f:
        entries = json.load(f)
    atlas_set = set(atlas_ids)
    result = {}
    for e in entries:
        mid = int(e.get("id", -1))
        if mid in atlas_set and e.get("is_foot_o", False):
            bounds = e.get("bounds") or {}
            if bounds.get("north") is not None:
                result[mid] = e
    return result


def _bbox_dict(entry: dict) -> dict:
    b = entry["bounds"]
    return {
        "min_x": float(b["west"]),
        "min_y": float(b["south"]),
        "max_x": float(b["east"]),
        "max_y": float(b["north"]),
    }


# ── Construction des caches ───────────────────────────────────────────────────

def build_caches(bb: dict, bbox_tuple: tuple, force_rebuild: bool = False) -> dict:
    from src.services.terrain.osm_fetcher import extract_sprint_features
    from src.services.optimization.route_analyzer import RouteAnalyzer
    from src.services.terrain.lidar_manager import build_elevation_cache
    from src.services.learning.ocad_patch_scorer import HeatmapCache, OcadPatchScorer

    t0 = time.time()
    osm = extract_sprint_features(bb)
    candidates = osm.get("candidates", [])
    log.info("  OSM: %.1fs (%d candidats)", time.time() - t0, len(candidates))

    ra = RouteAnalyzer(osm.get("highway_ways", []))

    t0 = time.time()
    ec = build_elevation_cache(bb)
    log.info("  ElevationCache: %.1fs", time.time() - t0)

    hmc = None
    _key = hashlib.md5(f"sprint5|{bbox_tuple}|cnn".encode()).hexdigest()[:12]
    _path = pathlib.Path(tempfile.gettempdir()) / f"aitraceur_hmc_{_key}"

    if not force_rebuild and _path.with_suffix(".npz").exists():
        hmc = HeatmapCache.load(_path)
        log.info("  HeatmapCache: disk hit (n_zones=%d is_flat=%s)", hmc.n_zones, hmc.is_flat_signal)
    else:
        try:
            from scripts.atlas_generation import _fetch_mapant_image
            t0 = time.time()
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
                        candidate_points=candidates,
                    )
                    hmc.save(_path)
                    log.info("  HeatmapCache: %.1fs (n_zones=%d is_flat=%s)",
                             time.time() - t0, hmc.n_zones, hmc.is_flat_signal)
            else:
                log.warning("  HeatmapCache: MapAnt indisponible — fallback ISOM")
        except Exception as ex:
            log.debug("  HeatmapCache: erreur — %s", ex)

    return {"heatmap_cache": hmc, "elevation_cache": ec, "route_analyzer": ra}


# ── Génération ────────────────────────────────────────────────────────────────

def generate_abc(bb: dict, discipline: str, caches: dict) -> Optional[List]:
    from src.services.generation.ai_generator import AIGenerator, GenerationRequest

    params = _GEN_PARAMS.get(discipline, _GEN_PARAMS["urbano"])
    req = GenerationRequest(
        bounding_box=bb,
        category="H21E",
        technical_level="TD3",
        n_runs=N_RUNS,
        top_k_per_run=TOP_K,
        ga_seed=GA_SEED,
        heatmap_cache=caches.get("heatmap_cache"),
        elevation_cache=caches.get("elevation_cache"),
        route_analyzer=caches.get("route_analyzer"),
        **params,
    )
    try:
        return AIGenerator().generate(req, num_variants=3)
    except Exception as e:
        log.error("  Génération échouée : %s", e)
        return None


# ── Extraction des métriques ──────────────────────────────────────────────────

def compute_metrics(circuits: List, bb_info: dict, caches: dict) -> dict:
    from src.services.generation.profiling.course_profile import compute_course_profile
    from src.services.generation.profiling.profile_distance import course_profile_vector, cosine_distance
    from src.services.generation.genetic_algo import _haversine_batch

    bbox_tuple = (bb_info["min_x"], bb_info["min_y"], bb_info["max_x"], bb_info["max_y"])
    hmc = caches.get("heatmap_cache")

    profiles: list[np.ndarray] = []
    per_variant: list[dict] = []

    for c in circuits:
        pts = [(ctrl["x"], ctrl["y"]) for ctrl in c.controls]
        arr = np.array(pts)
        legs_m = _haversine_batch(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])
        cp = compute_course_profile(
            controls=pts, legs_m=legs_m, bbox=bbox_tuple,
            heatmap_cache=hmc,
        )
        pv = course_profile_vector(cp)
        profiles.append(pv)
        per_variant.append({
            "fitness": float(c.score),
            "length_m": float(c.total_length_m),
            "map_coverage": float(cp.map_coverage),
            "rcd": float(cp.route_choice_density),
            "geo_spread_x": float(cp.geo_spread_x),
            "geo_spread_y": float(cp.geo_spread_y),
            "geo_spread": float((cp.geo_spread_x + cp.geo_spread_y) / 2.0),
            "zone_coverage": float(cp.zone_coverage),
            "zone_diversity": float(cp.zone_diversity),
            "labels": "|".join(c.label) if c.label else "Standard",
            "profile_title": c.profile_title or "Standard",
            "scenario": c.scenario or "standard",
        })

    # Distances cosinus pairwise
    n = len(profiles)
    if n == 2:
        log.warning("  Seulement 2 variantes — cos_AC et cos_BC seront NaN")
    cos_pairs: dict[str, float] = {}
    pair_labels = ["AB", "AC", "BC"]
    pairs = [(0, 1), (0, 2), (1, 2)]
    for lbl, (i, j) in zip(pair_labels, pairs):
        if i < n and j < n:
            cos_pairs[lbl] = cosine_distance(profiles[i], profiles[j])
        else:
            cos_pairs[lbl] = float("nan")

    valid_cos = [v for v in cos_pairs.values() if not np.isnan(v)]
    mean_cos = float(np.mean(valid_cos)) if valid_cos else 0.0

    # Nombre de labels distincts entre A/B/C
    distinct_labels = len({pv["labels"] for pv in per_variant})

    return {
        "mean_cosine": mean_cos,
        "cos_AB": cos_pairs.get("AB", float("nan")),
        "cos_AC": cos_pairs.get("AC", float("nan")),
        "cos_BC": cos_pairs.get("BC", float("nan")),
        "distinct_labels": distinct_labels,
        "n_zones": hmc.n_zones if hmc else 0,
        "variants": per_variant,
    }


# ── Traitement d'une carte ────────────────────────────────────────────────────

def process_map(map_id: int, entry: dict, force_rebuild: bool = False) -> Optional[dict]:
    log.info("[%s] démarrage (discipline=%s)", map_id, entry.get("discipline", "?"))

    bb = _bbox_dict(entry)
    bbox_tuple = (bb["min_x"], bb["min_y"], bb["max_x"], bb["max_y"])
    discipline = entry.get("discipline", "urbano")

    t_start = time.time()
    caches = build_caches(bb, bbox_tuple, force_rebuild=force_rebuild)

    t0 = time.time()
    circuits = generate_abc(bb, discipline, caches)
    log.info("  Génération: %.1fs", time.time() - t0)

    if not circuits or len(circuits) < 2:
        log.warning("  [%s] insuffisant (%d variante(s)) — ignoré", map_id, len(circuits) if circuits else 0)
        return None

    metrics = compute_metrics(circuits, bb, caches)
    total = time.time() - t_start

    log.info("  [%s] done %.0fs — mean_cos=%.4f distinct_labels=%d",
             map_id, total, metrics["mean_cosine"], metrics["distinct_labels"])

    row: dict = {
        "bbox_id": map_id,
        "terrain": discipline,
        "n_zones": metrics["n_zones"],
        "mean_cosine": metrics["mean_cosine"],
        "cos_AB": metrics["cos_AB"],
        "cos_AC": metrics["cos_AC"],
        "cos_BC": metrics["cos_BC"],
        "distinct_labels": metrics["distinct_labels"],
    }
    for i, label in enumerate("ABC"):
        if i < len(metrics["variants"]):
            v = metrics["variants"][i]
            for field in ("fitness", "length_m", "map_coverage", "rcd",
                          "geo_spread_x", "geo_spread_y", "geo_spread",
                          "zone_coverage", "zone_diversity",
                          "labels", "profile_title", "scenario"):
                row[f"{field}_{label}"] = v[field]

    return row


# ── Sorties ───────────────────────────────────────────────────────────────────

_METRIC_FIELDS = [
    "bbox_id", "terrain", "n_zones",
    "mean_cosine", "cos_AB", "cos_AC", "cos_BC", "distinct_labels",
    "fitness_A", "fitness_B", "fitness_C",
    "length_m_A", "length_m_B", "length_m_C",
    "map_coverage_A", "map_coverage_B", "map_coverage_C",
    "rcd_A", "rcd_B", "rcd_C",
    "geo_spread_x_A", "geo_spread_x_B", "geo_spread_x_C",
    "geo_spread_y_A", "geo_spread_y_B", "geo_spread_y_C",
    "geo_spread_A", "geo_spread_B", "geo_spread_C",
    "zone_coverage_A", "zone_coverage_B", "zone_coverage_C",
    "zone_diversity_A", "zone_diversity_B", "zone_diversity_C",
    "labels_A", "labels_B", "labels_C",
    "profile_title_A", "profile_title_B", "profile_title_C",
    "scenario_A", "scenario_B", "scenario_C",
]


def write_metrics_csv(results: list[dict]) -> pathlib.Path:
    path = OUTPUT_DIR / "sprint_5_metrics.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_METRIC_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    return path


def write_review_grid(results: list[dict]) -> pathlib.Path:
    """Grille vierge pour 2-3 traceurs — colonnes EVAL_ à remplir manuellement."""
    path = OUTPUT_DIR / "sprint_5_review_grid.csv"
    review_fields = [
        "bbox_id", "terrain",
        # Métriques auto (informatives)
        "mean_cosine", "distinct_labels",
        "labels_A", "labels_B", "labels_C",
        "profile_title_A", "profile_title_B", "profile_title_C",
        "scenario_A",
        # Colonnes à remplir par le traceur
        "EVAL_difference_percue_1_5",
        "EVAL_interet_sportif_A_1_5",
        "EVAL_interet_sportif_B_1_5",
        "EVAL_interet_sportif_C_1_5",
        "EVAL_qualite_globale_A_1_5",
        "EVAL_qualite_globale_B_1_5",
        "EVAL_qualite_globale_C_1_5",
        "EVAL_variante_choisie_ABC",
        "EVAL_labels_corrects_Oui_Partiellement_Non",
        "EVAL_commentaire",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=review_fields, extrasaction="ignore")
        w.writeheader()
        for r in results:
            row = {k: r.get(k, "") for k in review_fields}
            if "mean_cosine" in row:
                row["mean_cosine"] = f"{float(r.get('mean_cosine', 0)):.4f}"
            w.writerow(row)
    return path


def generate_report(results: list[dict]) -> str:
    n = len(results)
    if n == 0:
        return "Aucun résultat."

    mean_cos = float(np.mean([r["mean_cosine"] for r in results]))
    std_cos  = float(np.std([r["mean_cosine"] for r in results]))

    # Taux de cartes avec ≥ 2 labels distincts entre A/B/C
    n_diff_labels = sum(1 for r in results if r.get("distinct_labels", 0) >= 2)
    pct_diff = n_diff_labels / n * 100

    # Fitness moyen A
    f_a = [r.get("fitness_A", 0) for r in results if "fitness_A" in r]
    mean_fitness_a = float(np.mean(f_a)) if f_a else 0.0

    # Distribution des scénarios
    scenarios = [r.get("scenario_A", "standard") for r in results]
    scen_count = Counter(scenarios)

    lines = [
        "=" * 75,
        f"SPRINT 5 — Validation humaine des variantes A/B/C ({n} cartes)",
        "=" * 75,
        "",
        "DIVERSITÉ AUTOMATIQUE",
        f"  mean_cosine inter-variantes : {mean_cos:.4f} ± {std_cos:.4f}",
        f"  Cartes avec ≥ 2 labels distincts A/B/C : {n_diff_labels}/{n} ({pct_diff:.0f}%)",
        "",
        "FITNESS",
        f"  mean fitness_A : {mean_fitness_a:.3f}",
        "",
        "SCÉNARIOS COUCHE 2 (variante A)",
    ] + [f"  {k:<25}: {v:>3}" for k, v in sorted(scen_count.items())] + [
        "",
        "DÉTAIL PAR CARTE",
        f"  {'id':>6}  {'terr':>6}  {'cos':>6}  {'nz':>3}  "
        f"{'labels_A':<22}  {'labels_B':<22}  {'labels_C':<22}",
        "  " + "-" * 95,
    ]

    for r in sorted(results, key=lambda x: x["bbox_id"]):
        lines.append(
            f"  {r['bbox_id']:>6}  {r['terrain']:>6}  "
            f"{r['mean_cosine']:>6.4f}  {r.get('n_zones', 0):>3}  "
            f"{r.get('labels_A', 'Standard'):<22}  "
            f"{r.get('labels_B', 'Standard'):<22}  "
            f"{r.get('labels_C', 'Standard'):<22}"
        )

    verdict_cos   = "✓" if mean_cos >= 0.010 else "✗"
    verdict_label = "✓" if pct_diff >= 50.0 else "✗"

    lines += [
        "",
        "VERDICTS TECHNIQUES",
        f"  {verdict_cos} mean_cosine ≥ 0.010 (Sprint 4.1 baseline)  → {mean_cos:.4f}",
        f"  {verdict_label} ≥ 50% cartes avec labels distincts           → {pct_diff:.0f}%",
        "",
        "VERDICT FINAL : HUMAIN",
        "  → Remplir sprint_5_review_grid.csv (2-3 traceurs, 10-15 cartes chacun)",
        "  Critère de réversion H4 + W_SCENARIO :",
        "    moyenne EVAL_difference_percue < 3.0  OU  EVAL_labels_corrects < 50% Non/Partiellement",
        "=" * 75,
    ]

    return "\n".join(lines)


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Sprint 5 — Validation humaine A/B/C")
    parser.add_argument("--n", type=int, default=30, help="Nombre de cartes à traiter (défaut: 30)")
    parser.add_argument("--seed", type=int, default=0, help="Graine de sélection des cartes")
    parser.add_argument("--rebuild", action="store_true", help="Force le recalcul des HeatmapCache")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    t_global = time.time()

    log.info("Chargement Atlas IDs…")
    atlas_ids = load_atlas_ids()
    log.info("  %d IDs Atlas", len(atlas_ids))

    log.info("Chargement Vikazimut index…")
    viz_map = load_vikazimut_index(atlas_ids)
    log.info("  %d cartes matchées", len(viz_map))

    # Sélection et tri
    import random
    rng = random.Random(args.seed)
    available = sorted(viz_map.keys())
    selected = available[:args.n] if len(available) <= args.n else rng.sample(available, args.n)
    selected.sort()
    log.info("Traitement de %d cartes", len(selected))

    results: list[dict] = []
    for i, mid in enumerate(selected, 1):
        log.info("[%d/%d] carte %d", i, len(selected), mid)
        result = process_map(mid, viz_map[mid], force_rebuild=args.rebuild)
        if result is not None:
            results.append(result)

    log.info("%d/%d cartes valides", len(results), len(selected))

    if results:
        csv_path   = write_metrics_csv(results)
        grid_path  = write_review_grid(results)
        report_txt = generate_report(results)
        report_path = OUTPUT_DIR / "sprint_5_report.txt"
        report_path.write_text(report_txt + "\n", encoding="utf-8")

        print("\n" + report_txt)
        log.info("Terminé en %.0fs", time.time() - t_global)
        log.info("Sorties :")
        log.info("  %s", csv_path)
        log.info("  %s", grid_path)
        log.info("  %s", report_path)
    else:
        log.error("Aucun résultat valide.")


if __name__ == "__main__":
    main()
