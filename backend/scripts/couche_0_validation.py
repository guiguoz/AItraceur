#!/usr/bin/env python3
"""
couche_0_validation.py -- Validation Couche 0 (segmentation zones carte)

Pour 5 cartes (mix urbain/foret), genere :
  - Visualisation zone_labels (0=pauvre/rouge, 1=modere/jaune, 2=riche/vert)
  - Circuit A/B/C superpose avec zone_coverage et zone_diversity
  - Rapport texte avec critere de succes Couche 1

Critere de succes (readiness Couche 1) :
  >= 2/3 variantes ont zone_coverage OU zone_diversity differents (delta > 0.10)

Usage :
    python backend/scripts/couche_0_validation.py
"""

from __future__ import annotations

import logging
import pathlib
import sys
from typing import List, Optional

import numpy as np

_HERE = pathlib.Path(__file__).parent
BACKEND = _HERE.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

OUTPUT_DIR = ROOT / "output" / "couche_0"

# Memes cartes que Sprint 3.5b
TEST_MAP_IDS = [10799, 10723, 10905, 10055, 11067]

N_RUNS = 3
TOP_K = 10
GA_SEED = 42

# Force la reconstruction des caches HeatmapCache (purge les fichiers stales XGBoost)
# Mettre False pour re-utiliser les caches existants si deja rebuildes avec CNN
FORCE_REBUILD = False

ZONE_COLORS = ["#d62728", "#ff7f0e", "#2ca02c"]  # rouge/orange/vert = pauvre/modere/riche
VARIANT_COLORS = {"A": "#1f77b4", "B": "#9b2cae", "C": "#8c564b"}
LABELS_FULL = {"A": "A -- Fitness max", "B": "B -- Diversite max vs A", "C": "C -- Diversite globale"}

log = logging.getLogger("couche_0")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Reuse infrastructure depuis sprint_3_5b_visual
# ---------------------------------------------------------------------------

def _import_infra():
    """Import lazy pour eviter un import au chargement du module."""
    from scripts.sprint_3_5b_visual import load_bbox, generate_abc
    return load_bbox, generate_abc


def build_caches_fresh(bb_dict: dict, bbox_tuple: tuple) -> dict:
    """Comme sprint_3_5b.build_caches, mais purge le cache disque si FORCE_REBUILD=True."""
    import hashlib, tempfile as _tmp
    from src.services.terrain.osm_fetcher import extract_sprint_features
    from src.services.optimization.route_analyzer import RouteAnalyzer
    from src.services.terrain.lidar_manager import build_elevation_cache
    from src.services.learning.ocad_patch_scorer import HeatmapCache, OcadPatchScorer

    step_px = 20
    _key = hashlib.md5(f"atlas|{bbox_tuple}|{step_px}|cnn".encode()).hexdigest()[:12]
    _hmc_path = pathlib.Path(_tmp.gettempdir()) / f"aitraceur_hmc_{_key}"
    _hmc_npz = _hmc_path.with_suffix(".npz")

    if FORCE_REBUILD and _hmc_npz.exists():
        _hmc_npz.unlink()
        log.info("  Cache disque purgé : %s", _hmc_npz.name)

    import time as _time
    t0 = _time.perf_counter()
    osm = extract_sprint_features(bb_dict)
    ra = RouteAnalyzer(osm.get("highway_ways", []))
    log.info("  OSM + RouteAnalyzer: %.2fs (%d ways)", _time.perf_counter() - t0,
             len(osm.get("highway_ways", [])))

    t0 = _time.perf_counter()
    ec = build_elevation_cache(bb_dict)
    log.info("  ElevationCache: %.2fs", _time.perf_counter() - t0)

    hmc = None
    if _hmc_npz.exists():
        t0 = _time.perf_counter()
        hmc = HeatmapCache.load(_hmc_path)
        log.info("  HeatmapCache: %.2fs (disk hit, n_zones=%d)", _time.perf_counter() - t0, hmc.n_zones)
    else:
        try:
            from scripts.atlas_generation import _fetch_mapant_image
        except ImportError:
            _fetch_mapant_image = None

        if _fetch_mapant_image:
            t0 = _time.perf_counter()
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
                    # candidate_points ISOM : active la branche densite si signal CNN plat
                    cand_pts = osm.get("candidates", [])
                    hmc = scorer.build_heatmap_cache(
                        map_img=img, bbox=bbox_img, mpp=mpp,
                        step_px=step_px, cnn_scorer=cnn,
                        candidate_points=cand_pts,
                    )
                    hmc.save(_hmc_path)
                    log.info("  HeatmapCache: %.2fs (rebuild MapAnt, n_zones=%d)",
                             _time.perf_counter() - t0, hmc.n_zones)
            else:
                log.warning("  HeatmapCache: MapAnt indisponible")

    return {"heatmap_cache": hmc, "elevation_cache": ec, "route_analyzer": ra}


# ---------------------------------------------------------------------------
# Calcul metriques zone Couche 0
# ---------------------------------------------------------------------------

def compute_zone_metrics(circuits: list, heatmap_cache, bbox_tuple: tuple) -> List[dict]:
    """Calcule zone_coverage, zone_diversity et labels Couche 1 pour chaque variante."""
    from src.services.generation.profiling.course_profile import compute_course_profile
    from src.services.generation.genetic_algo import _haversine_batch
    from src.services.generation.ai_generator import LABEL_THRESHOLDS

    results = []
    for i, c in enumerate(circuits):
        pts = [(ctrl["x"], ctrl["y"]) for ctrl in c.controls]
        try:
            arr = np.array(pts)
            legs_m = _haversine_batch(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])
            cp = compute_course_profile(
                controls=pts, legs_m=legs_m, bbox=bbox_tuple,
                heatmap_cache=heatmap_cache,
            )
            labels, title = cp.describe(LABEL_THRESHOLDS)
            results.append({
                "label": "ABC"[i] if i < 3 else str(i),
                "fitness": c.score,
                "length_m": c.total_length_m,
                "zone_coverage": cp.zone_coverage,
                "zone_diversity": cp.zone_diversity,
                "n_zones": heatmap_cache.n_zones if heatmap_cache else 0,
                "couche1_labels": labels,
                "couche1_title": title,
            })
        except Exception as exc:
            log.warning("  profile %d echoue : %s", i, exc)
            results.append({
                "label": "ABC"[i] if i < 3 else str(i),
                "fitness": c.score,
                "length_m": c.total_length_m,
                "zone_coverage": 0.0,
                "zone_diversity": 0.0,
                "n_zones": 0,
                "couche1_labels": [],
                "couche1_title": "Standard",
            })
    return results


def criterion_pass(metrics: List[dict]) -> bool:
    """True si >= 2/3 variantes ont zone_coverage OU zone_diversity differents (delta > 0.10)."""
    if len(metrics) < 2:
        return False
    covs = [m["zone_coverage"] for m in metrics]
    divs = [m["zone_diversity"] for m in metrics]
    distinct_cov = len(set(round(v, 1) for v in covs)) >= 2
    distinct_div = len(set(round(v, 1) for v in divs)) >= 2
    return distinct_cov or distinct_div


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def _to_meters(pts, c_lng: float, c_lat: float):
    cos_lat = np.cos(np.radians(c_lat))
    return [(( lng - c_lng) * cos_lat * 111320,
             (lat - c_lat) * 111320)
            for lng, lat in pts]


def plot_carte(map_id: int, discipline: str, circuits: list,
               metrics: List[dict], heatmap_cache, out_path: pathlib.Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    import matplotlib.patches as mpatches

    fig, axes = plt.subplots(1, 3, figsize=(18, 7))
    n_zones = heatmap_cache.n_zones if heatmap_cache else 0
    fig.suptitle(
        f"Carte {map_id}  ({discipline})  -- Couche 0 : segmentation zones (n_zones={n_zones})\n"
        f"n_runs={N_RUNS}, top_k={TOP_K}, seed={GA_SEED}",
        fontsize=12, fontweight="bold",
    )

    # Bounds globaux (metres)
    all_pts = [(ctrl["x"], ctrl["y"]) for c in circuits for ctrl in c.controls]
    c_lng = sum(p[0] for p in all_pts) / len(all_pts)
    c_lat = sum(p[1] for p in all_pts) / len(all_pts)
    all_m = _to_meters(all_pts, c_lng, c_lat)
    margin = 150
    x_lo = min(p[0] for p in all_m) - margin
    x_hi = max(p[0] for p in all_m) + margin
    y_lo = min(p[1] for p in all_m) - margin
    y_hi = max(p[1] for p in all_m) + margin

    # Zone overlay en metres
    zone_img = None
    zone_extent_m = None
    if heatmap_cache is not None and heatmap_cache.zone_labels is not None and n_zones == 3:
        zl = heatmap_cache.zone_labels  # (H, W) uint8
        min_lng, min_lat, max_lng, max_lat = heatmap_cache.bbox
        # Coins en metres
        tl = _to_meters([(min_lng, max_lat)], c_lng, c_lat)[0]
        br = _to_meters([(max_lng, min_lat)], c_lng, c_lat)[0]
        zone_extent_m = (tl[0], br[0], br[1], tl[1])  # left, right, bottom, top
        zone_img = zl.astype(float)

    cmap_z = ListedColormap(ZONE_COLORS)
    norm_z = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], ncolors=3)

    for ax, circuit, m in zip(axes, circuits, metrics):
        # Zone overlay
        if zone_img is not None:
            ax.imshow(zone_img, extent=zone_extent_m, origin="upper",
                      cmap=cmap_z, norm=norm_z, alpha=0.35, aspect="auto", zorder=1)

        # Circuit
        pts = [(ctrl["x"], ctrl["y"]) for ctrl in circuit.controls]
        pts_m = _to_meters(pts, c_lng, c_lat)
        xs = [p[0] for p in pts_m]
        ys = [p[1] for p in pts_m]
        col = VARIANT_COLORS[m["label"]]

        ax.plot(xs, ys, "-", color=col, linewidth=2.0, alpha=0.85, zorder=3)
        ax.scatter(xs[1:-1], ys[1:-1], s=55, color=col, zorder=4, edgecolors="white", linewidth=0.8)
        ax.scatter([xs[0]], [ys[0]], s=140, marker="^", color=col, zorder=5, edgecolors="black", linewidth=0.8)
        ax.scatter([xs[-1]], [ys[-1]], s=180, marker="*", color=col, zorder=5, edgecolors="black", linewidth=1.2)

        for k, (x, y) in enumerate(zip(xs[1:-1], ys[1:-1]), 1):
            ax.text(x + 10, y + 7, str(k), fontsize=6, color="black", zorder=6)

        ax.set_xlim(x_lo, x_hi)
        ax.set_ylim(y_lo, y_hi)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.25, linestyle="--")
        ax.set_xlabel("W / E (m)", fontsize=8)
        ax.set_ylabel("S / N (m)", fontsize=8)

        criterion = criterion_pass(metrics)
        title = (
            f"{LABELS_FULL[m['label']]}\n"
            f"fitness={m['fitness']:.2f}  |  {m['length_m']:.0f}m\n"
            f"zone_coverage={m['zone_coverage']:.3f}  zone_diversity={m['zone_diversity']:.3f}\n"
            f"critere={'PASS' if criterion else 'FAIL'}"
        )
        ax.set_title(title, fontsize=8, loc="left", pad=6)

    # Legende zones
    if zone_img is not None:
        patches = [mpatches.Patch(color=ZONE_COLORS[i], label=lbl, alpha=0.7)
                   for i, lbl in enumerate(["Pauvre (0)", "Moderee (1)", "Riche (2)"])]
        fig.legend(handles=patches, loc="lower center", ncol=3, fontsize=9,
                   bbox_to_anchor=(0.5, -0.01))

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("  PNG : %s", out_path)


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def write_report(results_per_map: list, out_path: pathlib.Path) -> None:
    lines = [
        "# Rapport validation Couche 0 -- segmentation zones carte",
        "",
        "## Critere de succes readiness Couche 1",
        "  >= 2/3 variantes avec zone_coverage OU zone_diversity differents (delta > 0.10)",
        "",
        "## Resultats par carte",
        "",
        "| Carte | terrain | n_zones | covA | covB | covC | divA | divB | divC | critere |",
        "|-------|---------|---------|------|------|------|------|------|------|---------|",
    ]

    pass_count = 0
    for r in results_per_map:
        mid = r["map_id"]
        disc = r.get("discipline", "?")
        mets = r.get("metrics", [])
        nz = mets[0]["n_zones"] if mets else 0
        covs = [m["zone_coverage"] for m in mets] + [None] * (3 - len(mets))
        divs = [m["zone_diversity"] for m in mets] + [None] * (3 - len(mets))
        ok = criterion_pass(mets) if mets else False
        if ok:
            pass_count += 1
        cov_str = " | ".join(f"{v:.3f}" if v is not None else "?" for v in covs)
        div_str = " | ".join(f"{v:.3f}" if v is not None else "?" for v in divs)
        lines.append(f"| {mid} | {disc} | {nz} | {cov_str} | {div_str} | {'PASS' if ok else 'FAIL'} |")

    n = len(results_per_map)
    lines += [
        "",
        f"## Bilan : {pass_count}/{n} cartes PASS",
        "",
        f"Couche 1 readiness : {'OUI' if pass_count >= 5 else 'NON (%d/5 requis)' % pass_count}",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Rapport : %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        load_bbox, generate_abc = _import_infra()
    except ImportError as exc:
        log.error("Import sprint_3_5b_visual echoue : %s", exc)
        sys.exit(1)
    build_caches = build_caches_fresh

    results_per_map = []

    for map_id in TEST_MAP_IDS:
        log.info("=" * 60)
        log.info("Carte %d", map_id)

        bb_info = load_bbox(map_id)
        if bb_info is None:
            log.warning("  bbox introuvable — ignoree")
            results_per_map.append({"map_id": map_id, "discipline": "?", "metrics": []})
            continue

        log.info("  discipline=%s  scale=%s", bb_info["discipline"], bb_info["scale"])
        bb = {k: bb_info[k] for k in ("min_x", "min_y", "max_x", "max_y")}
        bbox_tuple = (bb["min_x"], bb["min_y"], bb["max_x"], bb["max_y"])

        try:
            caches = build_caches(bb, bbox_tuple)
        except Exception as exc:
            log.error("  build_caches : %s", exc)
            caches = {"heatmap_cache": None, "elevation_cache": None, "route_analyzer": None}

        hmc = caches.get("heatmap_cache")
        if hmc is None:
            log.warning("  HeatmapCache None -- zones inaccessibles")
        else:
            log.info("  n_zones=%d  is_flat=%s  scores_std=%.4f",
                     hmc.n_zones, hmc.is_flat_signal, hmc.scores_std)

        circuits = generate_abc(bb_info, caches)
        if not circuits:
            log.warning("  Aucun circuit -- carte ignoree")
            results_per_map.append({"map_id": map_id, "discipline": bb_info["discipline"], "metrics": []})
            continue

        while len(circuits) < 3:
            circuits.append(circuits[-1])

        metrics = compute_zone_metrics(circuits[:3], hmc, bbox_tuple)
        ok = criterion_pass(metrics)

        log.info("  zone_coverage  A=%.3f B=%.3f C=%.3f",
                 *[m["zone_coverage"] for m in metrics[:3]])
        log.info("  zone_diversity A=%.3f B=%.3f C=%.3f",
                 *[m["zone_diversity"] for m in metrics[:3]])
        for m in metrics[:3]:
            log.info("  [%s] %s  →  %s",
                     m["label"], m.get("couche1_title", "?"), m.get("couche1_labels", []))
        log.info("  critere Couche 1 : %s", "PASS" if ok else "FAIL")

        out_png = OUTPUT_DIR / f"carte_{map_id}.png"
        try:
            plot_carte(map_id, bb_info["discipline"], circuits[:3], metrics[:3], hmc, out_png)
        except Exception as exc:
            log.error("  plot_carte : %s", exc)

        results_per_map.append({
            "map_id": map_id,
            "discipline": bb_info["discipline"],
            "metrics": metrics,
        })

    write_report(results_per_map, OUTPUT_DIR / "rapport.txt")
    log.info("=" * 60)
    log.info("Termine. Fichiers dans %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
