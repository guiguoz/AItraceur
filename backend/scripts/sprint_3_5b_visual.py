#!/usr/bin/env python3
"""
sprint_3_5b_visual.py — Sprint 3.5b
Validation humaine de la diversification inter-runs.

Pour 5 cartes sélectionnées (mix urban/forêt/sprint), génère les variantes A/B/C :
  A = meilleur fitness (baseline)
  B = le plus différent de A (diversité pure)
  C = le plus différent de {A, B} (diversité globale, greedy step 2)

Sortie : output/sprint_3_5b/carte_XXXXX.png (1 figure par carte, 3 subplots)

Usage :
    python backend/scripts/sprint_3_5b_visual.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import sys
import tempfile
import time
from typing import List, Optional, Tuple

import numpy as np

# ── Chemins ──────────────────────────────────────────────────────────────────
_HERE = pathlib.Path(__file__).parent
BACKEND = _HERE.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

VIKAZIMUT_INDEX = ROOT / "vikazimut" / "index.json"
OUTPUT_DIR = ROOT / "output" / "sprint_3_5b"

# ── Configuration ─────────────────────────────────────────────────────────────
# 2 urban (10799 scale=4000, 10055 scale=5000)
# 2 forêt (10723 scale=10000, 10905 scale=10000)
# 1 sprint-like / mixte (11067 scale=2500)
TEST_MAP_IDS = [10799, 10723, 10905, 10055, 11067]

N_RUNS = 3
TOP_K = 10
GA_SEED = 42

log = logging.getLogger("sprint_3_5b")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ── Chargement index Vikazimut ────────────────────────────────────────────────

def load_bbox(map_id: int) -> Optional[dict]:
    """Retourne {min_x, min_y, max_x, max_y, scale, discipline} pour un map_id."""
    with open(VIKAZIMUT_INDEX, encoding="utf-8") as f:
        entries = json.load(f)
    for e in entries:
        if int(e.get("id", -1)) == map_id:
            b = e.get("bounds") or {}
            if not b or b.get("north") is None:
                return None
            return {
                "min_x": float(b["west"]),
                "min_y": float(b["south"]),
                "max_x": float(b["east"]),
                "max_y": float(b["north"]),
                "scale": e.get("scale") or 10000,
                "discipline": e.get("discipline") or "?",
                "course_type": e.get("course_type") or "?",
            }
    return None


# ── Construction des caches (identique à atlas_generation.py) ────────────────

def build_caches(bb_dict: dict, bbox_tuple: tuple) -> dict:
    from src.services.terrain.osm_fetcher import extract_sprint_features
    from src.services.optimization.route_analyzer import RouteAnalyzer
    from src.services.terrain.lidar_manager import build_elevation_cache
    from src.services.learning.ocad_patch_scorer import HeatmapCache, OcadPatchScorer

    t0 = time.perf_counter()
    osm = extract_sprint_features(bb_dict)
    ra = RouteAnalyzer(osm.get("highway_ways", []))
    log.info("  OSM + RouteAnalyzer: %.2fs (%d ways)", time.perf_counter() - t0,
             len(osm.get("highway_ways", [])))

    t0 = time.perf_counter()
    ec = build_elevation_cache(bb_dict)
    log.info("  ElevationCache: %.2fs", time.perf_counter() - t0)

    hmc = None
    step_px = 20
    _key = hashlib.md5(f"atlas|{bbox_tuple}|{step_px}|cnn".encode()).hexdigest()[:12]
    _hmc_path = pathlib.Path(tempfile.gettempdir()) / f"aitraceur_hmc_{_key}"
    _hmc_npz = _hmc_path.with_suffix(".npz")

    if _hmc_npz.exists():
        t0 = time.perf_counter()
        hmc = HeatmapCache.load(_hmc_path)
        log.info("  HeatmapCache: %.2fs (disk hit)", time.perf_counter() - t0)
    else:
        try:
            from scripts.atlas_generation import _fetch_mapant_image
        except ImportError:
            _fetch_mapant_image = None

        if _fetch_mapant_image:
            t0 = time.perf_counter()
            result = _fetch_mapant_image(bb_dict)
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
                        step_px=step_px, cnn_scorer=cnn,
                    )
                    hmc.save(_hmc_path)
                    log.info("  HeatmapCache: %.2fs (MapAnt)", time.perf_counter() - t0)
            else:
                log.info("  HeatmapCache: MapAnt indisponible → None")
        else:
            log.info("  HeatmapCache: import atlas_generation échoué → None")

    return {"heatmap_cache": hmc, "elevation_cache": ec, "route_analyzer": ra}


# ── Génération A/B/C ──────────────────────────────────────────────────────────

def generate_abc(bb_info: dict, caches: dict) -> Optional[List]:
    """Retourne [circuit_A, circuit_B, circuit_C] ou None si échec."""
    from src.services.generation.ai_generator import AIGenerator, GenerationRequest

    bb = {k: bb_info[k] for k in ("min_x", "min_y", "max_x", "max_y")}
    scale = bb_info.get("scale", 10000)
    discipline = (bb_info.get("discipline") or "").lower()
    ctype = "sprint" if ("sprint" in discipline or scale <= 5000) else "md"
    td = "TD1" if ctype == "sprint" else "TD3"

    req = GenerationRequest(
        bounding_box=bb,
        category="H21E",
        technical_level=td,
        target_length_m=3000 if ctype == "sprint" else 5000,
        target_controls=12 if ctype == "sprint" else 14,
        circuit_type=ctype,
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
        circuits = gen.generate(req, num_variants=3)
    except Exception as e:
        log.error("  Génération échouée : %s", e)
        return None

    if len(circuits) < 2:
        log.warning("  Seulement %d circuit(s) générés", len(circuits))
        return circuits if circuits else None

    return circuits  # [A, B, C] — ordre garanti par select_diverse_circuits


# ── Calcul métriques pour affichage ──────────────────────────────────────────

def compute_display_metrics(circuits: List, heatmap_cache=None, route_analyzer=None) -> List[dict]:
    """Calcule fitness, map_coverage, rcd, cosine_from_A pour chaque variante."""
    from src.services.generation.profiling.course_profile import compute_course_profile
    from src.services.generation.profiling.profile_distance import (
        course_profile_vector, cosine_distance
    )
    from src.services.generation.genetic_algo import _haversine_batch

    profiles = []
    for c in circuits:
        pts = [(ctrl["x"], ctrl["y"]) for ctrl in c.controls]
        arr = np.array(pts)
        try:
            legs_m = _haversine_batch(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])
            bb_tuple = (
                min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts),
            )
            cp = compute_course_profile(
                controls=pts, legs_m=legs_m, bbox=bb_tuple,
                heatmap_cache=heatmap_cache, route_analyzer=route_analyzer,
            )
            profiles.append(course_profile_vector(cp))
        except Exception as e:
            log.debug("  Profile failed: %s", e)
            profiles.append(None)

    v_a = profiles[0]
    results = []
    labels = ["A", "B", "C"]
    for i, (c, pv) in enumerate(zip(circuits, profiles)):
        cos_from_a = 0.0
        if i > 0 and v_a is not None and pv is not None:
            from src.services.generation.profiling.profile_distance import cosine_distance
            cos_from_a = cosine_distance(v_a, pv)

        cp_obj = None
        try:
            pts = [(ctrl["x"], ctrl["y"]) for ctrl in c.controls]
            arr = np.array(pts)
            legs_m = _haversine_batch(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])
            bb_tuple = (
                min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts),
            )
            from src.services.generation.profiling.course_profile import compute_course_profile
            cp_obj = compute_course_profile(
                controls=pts, legs_m=legs_m, bbox=bb_tuple,
                heatmap_cache=heatmap_cache, route_analyzer=route_analyzer,
            )
        except Exception:
            pass

        results.append({
            "label": labels[i],
            "fitness": c.score,
            "length_m": c.total_length_m,
            "cosine_from_a": cos_from_a,
            "map_coverage": cp_obj.map_coverage if cp_obj else 0.0,
            "rcd": cp_obj.route_choice_density if cp_obj else 0.0,
            "alternation": cp_obj.alternation if cp_obj else 0.0,
        })
    return results


# ── Tracé matplotlib ──────────────────────────────────────────────────────────

COLORS = {"A": "#1f77b4", "B": "#d62728", "C": "#2ca02c"}
LABELS_FULL = {
    "A": "A — Fitness max",
    "B": "B — Diversité max vs A",
    "C": "C — Diversité globale",
}


def _to_meters(pts: List[Tuple], center_lng: float, center_lat: float):
    """Convertit [(lng, lat)] en [(x_m, y_m)] relatifs au centre."""
    cos_lat = np.cos(np.radians(center_lat))
    xs = [(lng - center_lng) * cos_lat * 111320 for lng, lat in pts]
    ys = [(lat - center_lat) * 111320 for lng, lat in pts]
    return list(zip(xs, ys))


def plot_map(map_id: int, discipline: str, circuits: List, metrics: List[dict],
             out_path: pathlib.Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    fig, axes = plt.subplots(1, 3, figsize=(18, 7))
    fig.suptitle(
        f"Carte {map_id}  ({discipline})  — Variantes A / B / C\n"
        f"n_runs={N_RUNS}, top_k={TOP_K}, seed={GA_SEED}",
        fontsize=13, fontweight="bold",
    )

    # Compute global bounds for uniform scale
    all_pts = []
    for c in circuits:
        all_pts += [(ctrl["x"], ctrl["y"]) for ctrl in c.controls]
    if not all_pts:
        log.warning("  Aucun point à tracer pour %d", map_id)
        plt.close(fig)
        return
    c_lng = sum(p[0] for p in all_pts) / len(all_pts)
    c_lat = sum(p[1] for p in all_pts) / len(all_pts)

    all_m = _to_meters(all_pts, c_lng, c_lat)
    margin = 150  # m
    x_lo = min(p[0] for p in all_m) - margin
    x_hi = max(p[0] for p in all_m) + margin
    y_lo = min(p[1] for p in all_m) - margin
    y_hi = max(p[1] for p in all_m) + margin

    for ax, circuit, m in zip(axes, circuits, metrics):
        pts = [(ctrl["x"], ctrl["y"]) for ctrl in circuit.controls]
        pts_m = _to_meters(pts, c_lng, c_lat)
        xs = [p[0] for p in pts_m]
        ys = [p[1] for p in pts_m]
        col = COLORS[m["label"]]

        # Course line
        ax.plot(xs, ys, "-", color=col, linewidth=2.0, alpha=0.8, zorder=2)

        # Controls
        ax.scatter(xs[1:-1], ys[1:-1], s=60, color=col, zorder=3, edgecolors="white", linewidth=0.8)

        # Start (triangle) + Finish (double circle proxy)
        ax.scatter([xs[0]], [ys[0]], s=150, marker="^", color=col, zorder=4,
                   edgecolors="black", linewidth=0.8)
        ax.scatter([xs[-1]], [ys[-1]], s=200, color=col, zorder=4,
                   edgecolors="black", linewidth=1.2, marker="*")

        # Control numbers
        for i, (x, y) in enumerate(zip(xs[1:-1], ys[1:-1]), 1):
            ax.text(x + 12, y + 8, str(i), fontsize=6, color="black", zorder=5)

        # Uniform axes
        ax.set_xlim(x_lo, x_hi)
        ax.set_ylim(y_lo, y_hi)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.25, linestyle="--")
        ax.set_xlabel("← W / E →  (m)", fontsize=8)
        ax.set_ylabel("← S / N →  (m)", fontsize=8)

        # Subtitle with metrics
        cos_str = f"cos_A={m['cosine_from_a']:.4f}" if m["label"] != "A" else "référence"
        subtitle = (
            f"{LABELS_FULL[m['label']]}\n"
            f"fitness={m['fitness']:.2f}  |  {m['length_m']:.0f}m\n"
            f"coverage={m['map_coverage']:.3f}  rcd={m['rcd']:.3f}  alt={m['alternation']:.0f}\n"
            f"{cos_str}"
        )
        ax.set_title(subtitle, fontsize=9, loc="left", pad=8)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("  PNG sauvegardé : %s", out_path)


# ── Grille de validation (Markdown) ──────────────────────────────────────────

def write_validation_grid(map_id: int, metrics: List[dict], out_path: pathlib.Path) -> None:
    lines = [
        f"# Grille de validation — Carte {map_id}",
        "",
        "## Métriques générées",
        "",
        "| Métrique | A | B | C |",
        "|----------|---|---|---|",
    ]
    keys = [("fitness", "Fitness"), ("length_m", "Longueur (m)"), ("map_coverage", "Coverage"),
            ("rcd", "Route choice density"), ("alternation", "Alternation")]
    for k, label in keys:
        row = [f"{m[k]:.3f}" for m in metrics]
        lines.append(f"| {label} | {row[0]} | {row[1] if len(row) > 1 else '—'} | {row[2] if len(row) > 2 else '—'} |")

    lines += [
        "",
        "## Grille d'évaluation humaine",
        "",
        "| Critère | A | B | C |",
        "|---------|---|---|---|",
        "| Lisibilité parcours | | | |",
        "| Stratégie (choix visibles) | | | |",
        "| Rythme (alternance perçue) | | | |",
        "| Identité terrain cohérente | | | |",
        "| Redondance avec autres variantes | | | |",
        "",
        "## Verdict",
        "",
        "- [ ] **Cas 1 — Diversité réelle** : A, B, C vendables ensemble → Sprint 3 validé fort",
        "- [ ] **Cas 2 — Diversité partielle** : A + C ok, B superflu → cosinus à simplifier",
        "- [ ] **Cas 3 — Diversité faible** : A ≈ B ≈ C → métriques trop corrélées",
        "",
        "**Question clé** : Ces 3 circuits sont-ils interchangeables ou complémentaires pour un même événement ?",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("  Grille MD : %s", out_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for map_id in TEST_MAP_IDS:
        log.info("=" * 60)
        log.info("Carte %d", map_id)

        bb_info = load_bbox(map_id)
        if bb_info is None:
            log.warning("  bbox introuvable pour %d — ignorée", map_id)
            continue

        log.info("  discipline=%s  scale=%s  bbox=(%s,%s)->(%s,%s)",
                 bb_info["discipline"], bb_info["scale"],
                 bb_info["min_x"], bb_info["min_y"],
                 bb_info["max_x"], bb_info["max_y"])

        bb = {k: bb_info[k] for k in ("min_x", "min_y", "max_x", "max_y")}
        bbox_tuple = (bb["min_x"], bb["min_y"], bb["max_x"], bb["max_y"])

        log.info("  Construction caches...")
        try:
            caches = build_caches(bb, bbox_tuple)
        except Exception as e:
            log.error("  build_caches échoué : %s — caches vides", e)
            caches = {"heatmap_cache": None, "elevation_cache": None, "route_analyzer": None}

        log.info("  Génération A/B/C (n_runs=%d, top_k=%d)...", N_RUNS, TOP_K)
        circuits = generate_abc(bb_info, caches)
        if not circuits:
            log.warning("  Aucun circuit généré pour %d", map_id)
            continue

        # Pad si moins de 3 circuits
        while len(circuits) < 3:
            circuits.append(circuits[-1])

        log.info("  Calcul métriques d'affichage...")
        metrics = compute_display_metrics(
            circuits,
            heatmap_cache=caches.get("heatmap_cache"),
            route_analyzer=caches.get("route_analyzer"),
        )

        label_str = "  ".join(
            f"{m['label']}: fit={m['fitness']:.2f} cos={m['cosine_from_a']:.4f}"
            for m in metrics
        )
        log.info("  %s", label_str)

        out_png = OUTPUT_DIR / f"carte_{map_id}.png"
        out_md = OUTPUT_DIR / f"carte_{map_id}_grille.md"

        plot_map(map_id, bb_info["discipline"], circuits[:3], metrics[:3], out_png)
        write_validation_grid(map_id, metrics[:3], out_md)

    log.info("=" * 60)
    log.info("Terminé. Fichiers dans %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
