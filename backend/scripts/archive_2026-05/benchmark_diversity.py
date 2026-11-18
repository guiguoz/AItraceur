#!/usr/bin/env python3
"""
benchmark_diversity.py — Sprint 3.5a
Validation de la diversification inter-runs.

Utilise les données Atlas existantes (atlas_results.csv) pour mesurer :
  - Avant Sprint 3 : 3 circuits intra-run (run_id=0, rangs 0-2)
  - Après Sprint 3  : 3 circuits inter-runs (rank=0 de chaque run 0, 1, 2)

Usage :
    python backend/scripts/benchmark_diversity.py [--atlas output/atlas/atlas_results.csv]
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent.parent
ATLAS_CSV = ROOT / "output" / "atlas" / "atlas_results.csv"
REPORT_PATH = ROOT / "output" / "benchmark_diversity_report.txt"

# ---------------------------------------------------------------------------
# Critères de succès Sprint 3
# ---------------------------------------------------------------------------
CRITERIA: Dict[str, Tuple[str, float]] = {
    "mean_cosine_after":    (">", 0.05),   # diversité cosinus inter-runs
    "fitness_loss_pct":     ("<", 5.0),    # perte qualité variante 3 vs baseline
    "coverage_range_after": (">", 0.10),   # différence map_coverage entre variantes
    "rcd_range_after":      (">", 0.10),   # différence route_choice_density
}


# ---------------------------------------------------------------------------
# Vecteur de profil 6D (sous-ensemble disponible dans atlas_results.csv)
# ---------------------------------------------------------------------------
def _profile_vec(row: dict) -> np.ndarray:
    """6D : [alternation/100, map_coverage, zone_balance, rcd, transitions/10, t_strength]."""
    def _f(key: str, default: float = 0.0) -> float:
        val = row.get(key, "")
        try:
            return float(val) if val not in ("", "None", None) else default
        except (ValueError, TypeError):
            return default

    return np.array([
        _f("alternation") / 100.0,
        _f("map_coverage"),
        _f("zone_balance"),
        _f("route_choice_density"),
        min(1.0, _f("transition_count") / 10.0),
        _f("transition_strength"),
    ], dtype=np.float64)


def _cosine_distance(v1: np.ndarray, v2: np.ndarray) -> float:
    mask = np.isfinite(v1) & np.isfinite(v2)
    if not mask.any():
        return 0.0
    a, b = v1[mask], v2[mask]
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return float(1.0 - np.dot(a, b) / n) if n > 0 else 0.0


def _pairwise_stats(circuits: List[dict]) -> Tuple[float, float, float]:
    """(mean, min, max) des distances cosinus par paires."""
    vecs = [_profile_vec(c) for c in circuits]
    dists = [
        _cosine_distance(vecs[i], vecs[j])
        for i in range(len(vecs))
        for j in range(i + 1, len(vecs))
    ]
    if not dists:
        return 0.0, 0.0, 0.0
    return float(np.mean(dists)), float(np.min(dists)), float(np.max(dists))


def _col_range(circuits: List[dict], col: str) -> float:
    vals = []
    for c in circuits:
        try:
            v = c.get(col, "")
            vals.append(float(v) if v not in ("", "None", None) else 0.0)
        except (ValueError, TypeError):
            pass
    return float(max(vals) - min(vals)) if len(vals) >= 2 else 0.0


def _fitness_stats(circuits: List[dict]) -> Tuple[float, float]:
    vals = []
    for c in circuits:
        try:
            vals.append(float(c.get("fitness", 0.0) or 0.0))
        except (ValueError, TypeError):
            pass
    if not vals:
        return 0.0, 0.0
    return float(max(vals)), float(np.mean(vals))


# ---------------------------------------------------------------------------
# Chargement Atlas
# ---------------------------------------------------------------------------
def load_atlas(path: Path) -> Dict[str, List[dict]]:
    groups: Dict[str, List[dict]] = defaultdict(list)
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            groups[row["bbox_id"]].append(row)
    return groups


# ---------------------------------------------------------------------------
# Simulation Avant / Après Sprint 3
# ---------------------------------------------------------------------------
def before_sprint3(rows: List[dict], n: int = 3) -> List[dict]:
    """Top-n circuits d'un seul run (run_id=0) — intra-run convergence."""
    run0 = sorted(
        [r for r in rows if r.get("run_id") == "0"],
        key=lambda r: int(r.get("rank_in_run", 99)),
    )
    return run0[:n]


def after_sprint3(rows: List[dict], n_runs: int = 3) -> List[dict]:
    """Meilleur circuit de chaque run 0..n_runs-1 — pool inter-runs."""
    selected = []
    for rid in range(n_runs):
        candidates = sorted(
            [r for r in rows if r.get("run_id") == str(rid)],
            key=lambda r: int(r.get("rank_in_run", 99)),
        )
        if candidates:
            selected.append(candidates[0])
    return selected


# ---------------------------------------------------------------------------
# Métriques par carte
# ---------------------------------------------------------------------------
def compute_map_metrics(rows: List[dict]) -> Optional[dict]:
    before = before_sprint3(rows, n=3)
    after = after_sprint3(rows, n_runs=3)
    if len(before) < 2 or len(after) < 2:
        return None

    fit_best_before, _ = _fitness_stats(before)
    fit_best_after, fit_mean_after = _fitness_stats(after)

    fitness_loss_pct = (
        (fit_best_before - fit_mean_after) / fit_best_before * 100.0
        if fit_best_before > 0 else 0.0
    )

    cos_mean_b, cos_min_b, cos_max_b = _pairwise_stats(before)
    cos_mean_a, cos_min_a, cos_max_a = _pairwise_stats(after)

    return {
        "fit_best_before":      fit_best_before,
        "fit_best_after":       fit_best_after,
        "fit_mean_after":       fit_mean_after,
        "fitness_loss_pct":     fitness_loss_pct,
        "mean_cosine_before":   cos_mean_b,
        "min_cosine_before":    cos_min_b,
        "max_cosine_before":    cos_max_b,
        "mean_cosine_after":    cos_mean_a,
        "min_cosine_after":     cos_min_a,
        "max_cosine_after":     cos_max_a,
        "coverage_range_before": _col_range(before, "map_coverage"),
        "coverage_range_after":  _col_range(after, "map_coverage"),
        "rcd_range_before":      _col_range(before, "route_choice_density"),
        "rcd_range_after":       _col_range(after, "route_choice_density"),
    }


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------
def _ok(val: float, op: str, threshold: float) -> bool:
    return (val > threshold) if op == ">" else (val < threshold)


def generate_report(per_map: Dict[str, Optional[dict]], n_maps: int) -> str:
    maps = [m for m in per_map.values() if m is not None]
    if not maps:
        return "Aucune donnee."

    def agg(key: str) -> float:
        return float(np.mean([m[key] for m in maps]))

    S = {k: agg(k) for k in maps[0]}
    lines = [
        "=" * 72,
        "BENCHMARK DIVERSIFICATION INTER-RUNS — Sprint 3.5a",
        f"Cartes analysees : {len(maps)} / {n_maps}",
        "=" * 72,
        "",
        "METRIQUES COMPAREES (moyenne sur toutes les cartes)",
        f"  {'Indicateur':<38}  {'Avant S3':>9}  {'Apres S3':>9}  {'Gain':>8}",
        "  " + "-" * 68,
    ]

    def row(label, bk, ak, fmt=".4f", hi=True):
        bv, av = S.get(bk, 0.0), S.get(ak, 0.0)
        gain = (av - bv) if hi else (bv - av)
        return f"  {label:<38}  {bv:>9{fmt}}  {av:>9{fmt}}  {gain:>+8{fmt}}"

    lines += [
        row("mean_cosine",           "mean_cosine_before",    "mean_cosine_after"),
        row("min_cosine",            "min_cosine_before",     "min_cosine_after"),
        row("max_cosine",            "max_cosine_before",     "max_cosine_after"),
        row("coverage_range",        "coverage_range_before", "coverage_range_after"),
        row("route_choice_density_range", "rcd_range_before", "rcd_range_after"),
        f"  {'perte_fitness (%)':<38}  {'':>9}  {S['fitness_loss_pct']:>9.2f}  {'':>8}",
        "",
        "CRITERES DE SUCCES",
        "  " + "-" * 55,
    ]

    all_ok = True
    for key, (op, threshold) in CRITERIA.items():
        val = S.get(key, 0.0)
        ok = _ok(val, op, threshold)
        if not ok:
            all_ok = False
        sym = "OK   " if ok else "ECHEC"
        lines.append(f"  [{sym}] {key:<38} {op} {threshold:.2f}  (mesure: {val:.4f})")

    verdict = "SPRINT 3 VALIDE" if all_ok else "SPRINT 3 INSUFFISANT — voir detail"
    lines += [
        "",
        "  " + "-" * 55,
        f"  VERDICT : {verdict}",
        "  " + "-" * 55,
        "",
    ]

    # Détail par carte
    lines += [
        "DETAIL PAR CARTE",
        f"  {'bbox_id':>10}  {'loss%':>6}  {'cos_bef':>8}  {'cos_aft':>8}  {'cov_rng':>8}  {'rcd_rng':>8}",
        "  " + "-" * 56,
    ]
    for bbox_id, m in sorted(per_map.items()):
        if m is None:
            continue
        lines.append(
            f"  {bbox_id:>10}  {m['fitness_loss_pct']:>6.2f}  "
            f"{m['mean_cosine_before']:>8.4f}  {m['mean_cosine_after']:>8.4f}  "
            f"{m['coverage_range_after']:>8.4f}  {m['rcd_range_after']:>8.4f}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(atlas_path: Optional[Path] = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    path = atlas_path or ATLAS_CSV
    if not path.exists():
        print(f"Atlas introuvable : {path}")
        print("Lancez atlas_generation.py d'abord.")
        sys.exit(1)

    print(f"Chargement {path} ...", flush=True)
    groups = load_atlas(path)
    n_maps = len(groups)
    print(f"  {n_maps} cartes, {sum(len(v) for v in groups.values())} circuits", flush=True)

    per_map: Dict[str, Optional[dict]] = {}
    for bbox_id, rows in sorted(groups.items()):
        per_map[bbox_id] = compute_map_metrics(rows)

    valid = sum(1 for m in per_map.values() if m is not None)
    print(f"  {valid} cartes valides (>= 2 circuits avant et apres)", flush=True)

    report = generate_report(per_map, n_maps)
    print("\n" + report, flush=True)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(f"\nRapport : {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark diversification Sprint 3.5a")
    parser.add_argument("--atlas", type=Path, default=None, help="Chemin vers atlas_results.csv")
    args = parser.parse_args()
    main(args.atlas)
