"""
Analyse de l'expérience W_DIVERSITY (w_diversity_mult ×0.5 / ×1.0 / ×1.5).

Usage:
  python backend/scripts/analyze_diversity_experiment.py \\
    backend/debug/intent_legs_wdiv05_td5.csv:W_DIV×0.5 \\
    backend/debug/intent_legs_post_fix_full.csv:baseline \\
    backend/debug/intent_legs_wdiv15_td5.csv:W_DIV×1.5

Chaque argument : <chemin_csv>:<label>
Filtre TD5 uniquement, agrège par circuit, PCA partagée sur la concaténation des 3 runs.

Phase A — métriques minimales :
  - fitness CV (std / mean)
  - slope TD5 : OLS fitness ~ PC1 (espace commun)
  - latent area : std(PC1) × std(PC2)
  - mean_unique_tags

Critères d'interprétation imprimés en fin d'analyse.
"""

from __future__ import annotations

import sys
import csv
import pathlib
from collections import defaultdict

import numpy as np


# ── Features utilisées pour la PCA ────────────────────────────────────────────
FEATURE_COLS = [
    "parallel_affordance", "crossing_density", "exit_clarity",
    "contour_crossing_guidance",
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
    "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
]


def _load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _aggregate_circuits(rows: list[dict], td_filter: int = 5) -> list[dict]:
    """Agrège les legs par circuit (mean features + fitness_total + n_unique_tags)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        try:
            if int(row["td"]) == td_filter:
                groups[row["circuit_id"]].append(row)
        except (ValueError, KeyError):
            continue

    circuits = []
    for cid, legs in groups.items():
        rec: dict = {"circuit_id": cid}
        rec["fitness_total"] = float(legs[0]["fitness_total"])
        for col in FEATURE_COLS:
            vals = []
            for leg in legs:
                try:
                    vals.append(float(leg[col]))
                except (ValueError, KeyError):
                    pass
            rec[col] = float(np.mean(vals)) if vals else 0.0
        # n_unique_tags est per-circuit (identique sur toutes les jambes d'un même circuit)
        try:
            rec["n_unique_tags"] = float(legs[0]["n_unique_tags"])
        except (ValueError, KeyError):
            rec["n_unique_tags"] = 0.0
        circuits.append(rec)
    return circuits


def _feature_matrix(circuits: list[dict]) -> np.ndarray:
    return np.array([[c[col] for col in FEATURE_COLS] for c in circuits], dtype=float)


def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    """OLS slope β₁ pour y = β₀ + β₁·x."""
    X = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coef[1])


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python analyze_diversity_experiment.py file1.csv:label1 [file2.csv:label2 ...]")
        sys.exit(1)

    runs: list[tuple[str, str, list[dict]]] = []
    for arg in sys.argv[1:]:
        if ":" in arg:
            path, label = arg.rsplit(":", 1)
        else:
            path, label = arg, pathlib.Path(arg).stem
        if not pathlib.Path(path).exists():
            print(f"ERREUR: fichier introuvable : {path}")
            sys.exit(1)
        rows = _load_csv(path)
        circuits = _aggregate_circuits(rows, td_filter=5)
        if not circuits:
            print(f"WARN: aucun circuit TD5 dans {path}")
        runs.append((label, path, circuits))

    if not runs:
        print("Aucun run chargé.")
        sys.exit(1)

    # ── PCA partagée : fit sur la concaténation de tous les runs ──────────────
    all_circuits = [c for _, _, circs in runs for c in circs]
    all_features = _feature_matrix(all_circuits)

    mean_ = all_features.mean(axis=0)
    std_ = all_features.std(axis=0)
    std_[std_ == 0] = 1.0  # éviter division par zéro
    all_scaled = (all_features - mean_) / std_

    U, S, Vt = np.linalg.svd(all_scaled, full_matrices=False)
    total_var = (S ** 2).sum()
    pc1_var = S[0] ** 2 / total_var * 100
    pc2_var = S[1] ** 2 / total_var * 100

    print(f"\n{'=' * 60}")
    print(f"PCA partagée  ({len(all_circuits)} circuits au total)")
    print(f"  PC1 = {pc1_var:.1f}%    PC2 = {pc2_var:.1f}%")

    # ── Projeter chaque run dans l'espace commun ──────────────────────────────
    col_w = 14
    header = f"{'Métrique':<28}" + "".join(f"{label:>{col_w}}" for label, _, _ in runs)
    print(f"\n{header}")
    print("-" * (28 + col_w * len(runs)))

    results: list[dict] = []
    for label, path, circuits in runs:
        if not circuits:
            results.append({"label": label, "n": 0})
            continue

        feat = _feature_matrix(circuits)
        scaled = (feat - mean_) / std_
        # Projeter sur les 2 premières composantes
        pc_scores = scaled @ Vt[:2].T  # shape (n_circuits, 2)
        pc1 = pc_scores[:, 0]
        pc2 = pc_scores[:, 1]

        fitness = np.array([c["fitness_total"] for c in circuits])
        n_tags = np.array([c["n_unique_tags"] for c in circuits])

        cv = float(fitness.std() / fitness.mean()) if fitness.mean() != 0 else float("nan")
        slope = _ols_slope(pc1, fitness)
        area = float(pc1.std() * pc2.std())
        mean_tags = float(n_tags.mean())

        results.append({
            "label": label,
            "n": len(circuits),
            "cv": cv,
            "slope": slope,
            "area": area,
            "mean_tags": mean_tags,
            "fitness_mean": float(fitness.mean()),
            "fitness_std": float(fitness.std()),
            "pc1_std": float(pc1.std()),
            "pc2_std": float(pc2.std()),
        })

    # Afficher tableau
    metrics = [
        ("N circuits", "n", ".0f"),
        ("fitness mean", "fitness_mean", ".2f"),
        ("fitness SD", "fitness_std", ".2f"),
        ("fitness CV", "cv", ".3f"),
        ("slope TD5 (OLS)", "slope", ".1f"),
        ("latent area (PC1×PC2)", "area", ".4f"),
        ("std PC1", "pc1_std", ".4f"),
        ("std PC2", "pc2_std", ".4f"),
        ("mean_unique_tags", "mean_tags", ".2f"),
    ]

    for mname, mkey, fmt in metrics:
        row = f"{mname:<28}"
        for r in results:
            val = r.get(mkey)
            if val is None or r["n"] == 0:
                row += f"{'—':>{col_w}}"
            else:
                row += f"{val:{col_w}{fmt}}"
        print(row)

    # ── Interprétation ────────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("Critères d'interprétation (Phase A) :")
    print("  latent area UP + slope DOWN + CV stable  → collapse morphologique réduit")
    print("  latent area UP + slope stable            → diversité sans impact fitness")
    print("  latent area stable + CV UP               → bruit/instabilité sans exploration")
    print("  n_unique_tags UP sans latent area UP     → diversité locale, manifold inchangé")

    if len(results) >= 2:
        r_ref = next((r for r in results if "baseline" in r["label"].lower()), results[0])
        ref_label = r_ref["label"]
        print(f"\n  Référence : {ref_label}  (fitness mean={r_ref.get('fitness_mean', 0):.2f}, "
              f"CV={r_ref.get('cv', 0):.3f}, area={r_ref.get('area', 0):.4f}, "
              f"slope={r_ref.get('slope', 0):.1f})")
        for r in results:
            if r["label"] == ref_label or r["n"] == 0:
                continue
            delta_cv = r.get("cv", 0) - r_ref.get("cv", 0)
            delta_area = r.get("area", 0) - r_ref.get("area", 0)
            delta_slope = r.get("slope", 0) - r_ref.get("slope", 0)
            delta_tags = r.get("mean_tags", 0) - r_ref.get("mean_tags", 0)
            print(f"\n  vs {r['label']} :")
            print(f"    ΔCV={delta_cv:+.3f}  Δarea={delta_area:+.4f}  "
                  f"Δslope={delta_slope:+.1f}  Δtags={delta_tags:+.2f}")


if __name__ == "__main__":
    main()
