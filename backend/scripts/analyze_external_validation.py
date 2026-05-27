"""
Validation externe du manifold latent — généralisation sur nouvelles cartes.

Usage:
  python backend/scripts/analyze_external_validation.py \\
    backend/debug/intent_legs_post_fix_full.csv \\
    backend/debug/intent_legs_carte3_full.csv \\
    backend/debug/intent_legs_carte4_full.csv

Le premier CSV est la baseline (stanne+crohot) : PCA figée dessus.
Les CSVs suivants sont les nouvelles cartes projetées dans cet espace.

Chaque CSV doit avoir une colonne `map_name` — c'est la clé de groupement.

Tests produits :
  Table 1 — Métriques par carte (sep ratio TD, slope par TD)
  Table 2 — Domain shift pairwise M1/M2/M3 (TD3, N faible → effet size prioritaire)
  Table 3 — Distance OOD au manifold baseline (Mahalanobis si cov inversible, sinon Euclidean)
"""

from __future__ import annotations

import sys
import csv
import pathlib
from collections import defaultdict
from itertools import combinations

import numpy as np


FEATURE_COLS = [
    "parallel_affordance", "crossing_density", "exit_clarity",
    "contour_crossing_guidance",
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
    "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
]

BASELINE_MAPS = {"stanne", "crohot"}  # cartes qui définissent le PCA baseline


# ── Chargement / agrégation ───────────────────────────────────────────────────

def _load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _aggregate_circuits(rows: list[dict]) -> list[dict]:
    """Agrège les jambes par circuit. Retourne une liste de circuits avec features moyennées."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["circuit_id"]].append(row)

    circuits = []
    for cid, legs in groups.items():
        rec: dict = {
            "circuit_id": cid,
            "map_name": legs[0].get("map_name", "unknown"),
            "td": int(legs[0]["td"]),
            "fitness_total": float(legs[0]["fitness_total"]),
        }
        for col in FEATURE_COLS:
            vals = [float(leg[col]) for leg in legs if col in leg and leg[col] != ""]
            rec[col] = float(np.mean(vals)) if vals else 0.0
        circuits.append(rec)
    return circuits


def _feature_matrix(circuits: list[dict]) -> np.ndarray:
    return np.array([[c[col] for col in FEATURE_COLS] for c in circuits], dtype=float)


def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2:
        return float("nan")
    X = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coef[1])


def _sep_ratio(pcs: np.ndarray, tds: np.ndarray) -> float:
    """d_norm entre centroïde TD3 et TD5 dans l'espace PC1-PC2."""
    td3 = pcs[tds == 3]
    td5 = pcs[tds == 5]
    if len(td3) < 2 or len(td5) < 2:
        return float("nan")
    centroid3 = td3.mean(axis=0)
    centroid5 = td5.mean(axis=0)
    pooled_std = np.concatenate([td3, td5]).std()
    return float(np.linalg.norm(centroid5 - centroid3) / (pooled_std + 1e-10))


def _mahalanobis(x: np.ndarray, mean: np.ndarray, cov: np.ndarray) -> float:
    try:
        cov_inv = np.linalg.inv(cov)
        diff = x - mean
        return float(np.sqrt(diff @ cov_inv @ diff))
    except np.linalg.LinAlgError:
        return float(np.linalg.norm(x - mean))


# ── Tests domain shift ────────────────────────────────────────────────────────

def _m1_permutation(pcs_a: np.ndarray, pcs_b: np.ndarray, n_perm: int = 2000) -> tuple[float, float]:
    """M1 : permutation test sur d_norm. Retourne (d_norm_obs, p_value)."""
    all_pcs = np.vstack([pcs_a, pcs_b])
    n_a = len(pcs_a)
    pooled_std = all_pcs.std() + 1e-10

    def _d(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.linalg.norm(a.mean(axis=0) - b.mean(axis=0)) / pooled_std)

    d_obs = _d(pcs_a, pcs_b)
    rng = np.random.default_rng(42)
    count = 0
    for _ in range(n_perm):
        perm = rng.permutation(len(all_pcs))
        count += _d(all_pcs[perm[:n_a]], all_pcs[perm[n_a:]]) >= d_obs
    return d_obs, count / n_perm


def _m2_bootstrap_ci(fit_a: np.ndarray, fit_b: np.ndarray, b: int = 1000) -> tuple[float, float]:
    """M2 : bootstrap CI 95% sur mean_A − mean_B. Retourne (ci_low, ci_high)."""
    rng = np.random.default_rng(42)
    deltas = []
    for _ in range(b):
        s_a = rng.choice(fit_a, size=len(fit_a), replace=True)
        s_b = rng.choice(fit_b, size=len(fit_b), replace=True)
        deltas.append(s_a.mean() - s_b.mean())
    deltas_arr = np.array(deltas)
    return float(np.percentile(deltas_arr, 2.5)), float(np.percentile(deltas_arr, 97.5))


def _m3_delta_r2(pc1: np.ndarray, fitness: np.ndarray, labels: np.ndarray) -> float:
    """M3 : ΔR² en ajoutant interaction map_label × PC1."""
    def _r2(X: np.ndarray, y: np.ndarray) -> float:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = X @ coef
        ss_res = ((y - pred) ** 2).sum()
        ss_tot = ((y - y.mean()) ** 2).sum()
        return 1.0 - ss_res / ss_tot if ss_tot > 1e-10 else 0.0

    X_base = np.column_stack([np.ones(len(pc1)), pc1])
    X_int = np.column_stack([np.ones(len(pc1)), pc1, labels.astype(float),
                              pc1 * labels.astype(float)])
    r2_base = _r2(X_base, fitness)
    r2_int = _r2(X_int, fitness)
    return float(r2_int - r2_base)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python analyze_external_validation.py baseline.csv [new_map1.csv ...]")
        sys.exit(1)

    # Charger tous les CSV
    all_circuits: list[dict] = []
    for path in sys.argv[1:]:
        if not pathlib.Path(path).exists():
            print(f"ERREUR: fichier introuvable : {path}")
            sys.exit(1)
        rows = _load_csv(path)
        circuits = _aggregate_circuits(rows)
        all_circuits.extend(circuits)
        maps_in_file = {c["map_name"] for c in circuits}
        print(f"  {pathlib.Path(path).name} : {len(circuits)} circuits — cartes: {sorted(maps_in_file)}")

    # Grouper par carte
    by_map: dict[str, list[dict]] = defaultdict(list)
    for c in all_circuits:
        by_map[c["map_name"]].append(c)

    map_names = sorted(by_map.keys())
    new_maps = [m for m in map_names if m not in BASELINE_MAPS]

    # ── PCA figée sur baseline (stanne + crohot uniquement) ──────────────────
    baseline_circuits = [c for c in all_circuits if c["map_name"] in BASELINE_MAPS]
    if not baseline_circuits:
        print("ERREUR: aucun circuit baseline (stanne/crohot) trouvé dans les CSV fournis.")
        sys.exit(1)

    X_baseline = _feature_matrix(baseline_circuits)
    mean_ = X_baseline.mean(axis=0)
    std_ = X_baseline.std(axis=0)
    std_[std_ == 0] = 1.0
    X_bl_scaled = (X_baseline - mean_) / std_

    # PCA(n_components=2, random_state=0) — figée, reproductible
    U, S, Vt = np.linalg.svd(X_bl_scaled, full_matrices=False)
    Vt2 = Vt[:2]  # 2 premières composantes

    total_var = (S ** 2).sum()
    pc1_var = S[0] ** 2 / total_var * 100
    pc2_var = S[1] ** 2 / total_var * 100

    print(f"\n{'=' * 65}")
    print(f"PCA baseline (stanne+crohot, {len(baseline_circuits)} circuits) :")
    print(f"  PC1 = {pc1_var:.1f}%    PC2 = {pc2_var:.1f}%")
    print(f"  Nouvelles cartes projetées dans cet espace figé : {new_maps or '(aucune)'}")

    def _project(circuits: list[dict]) -> np.ndarray:
        X = _feature_matrix(circuits)
        X_scaled = (X - mean_) / std_
        return X_scaled @ Vt2.T  # (n, 2)

    # Projeter toutes les cartes
    pcs_by_map: dict[str, np.ndarray] = {}
    tds_by_map: dict[str, np.ndarray] = {}
    fit_by_map: dict[str, np.ndarray] = {}
    for mname, circs in by_map.items():
        pcs_by_map[mname] = _project(circs)
        tds_by_map[mname] = np.array([c["td"] for c in circs])
        fit_by_map[mname] = np.array([c["fitness_total"] for c in circs])

    # ── Table 1 — Métriques par carte ────────────────────────────────────────
    col_w = 12
    print(f"\n{'─' * 65}")
    print("TABLE 1 — Métriques par carte (espace PCA figé baseline)")
    print(f"\n{'Carte':<12}{'N TD3':>8}{'N tot':>7}{'SepRatioTD':>12}{'Slope_TD3':>11}{'Slope_TD4':>11}{'Slope_TD5':>11}")
    print("-" * 72)

    for mname in map_names:
        pcs = pcs_by_map[mname]
        tds = tds_by_map[mname]
        fit = fit_by_map[mname]
        n_td3 = int((tds == 3).sum())
        n_tot = len(tds)
        sep = _sep_ratio(pcs, tds)

        slopes = {}
        for td_val in (3, 4, 5):
            mask = tds == td_val
            if mask.sum() >= 2:
                slopes[td_val] = _ols_slope(pcs[mask, 0], fit[mask])
            else:
                slopes[td_val] = float("nan")

        def _fmt(v: float) -> str:
            return f"{v:.2f}" if not np.isnan(v) else "—"

        print(f"{mname:<12}{n_td3:>8}{n_tot:>7}{_fmt(sep):>12}"
              f"{_fmt(slopes[3]):>11}{_fmt(slopes[4]):>11}{_fmt(slopes[5]):>11}")

    # ── Table 2 — Domain shift pairwise (TD3) ────────────────────────────────
    print(f"\n{'─' * 65}")
    print("TABLE 2 — Domain shift pairwise TD3 (exploratoire, N faible)")
    print("  Effect size (d_norm) prioritaire sur p-value à N=12\n")
    print(f"{'Paire':<24}{'d_norm':>8}{'p M1':>8}{'ΔFit CI_low':>13}{'ΔFit CI_high':>13}{'ΔR² M3':>9}")
    print("-" * 77)

    for m_a, m_b in combinations(map_names, 2):
        mask_a = tds_by_map[m_a] == 3
        mask_b = tds_by_map[m_b] == 3
        if mask_a.sum() < 2 or mask_b.sum() < 2:
            continue

        pcs_a3 = pcs_by_map[m_a][mask_a]
        pcs_b3 = pcs_by_map[m_b][mask_b]
        fit_a3 = fit_by_map[m_a][mask_a]
        fit_b3 = fit_by_map[m_b][mask_b]

        d_norm, p_val = _m1_permutation(pcs_a3, pcs_b3)
        ci_lo, ci_hi = _m2_bootstrap_ci(fit_a3, fit_b3)

        # M3 : combiner les deux cartes, label binaire
        pcs_all3 = np.vstack([pcs_a3, pcs_b3])
        fit_all3 = np.concatenate([fit_a3, fit_b3])
        labels3 = np.array([0] * len(pcs_a3) + [1] * len(pcs_b3))
        delta_r2 = _m3_delta_r2(pcs_all3[:, 0], fit_all3, labels3)

        ci_str = f"[{ci_lo:+.1f},{ci_hi:+.1f}]"
        incl0 = "✓0" if ci_lo <= 0 <= ci_hi else "✗0"
        pair_label = f"{m_a} vs {m_b}"
        print(f"{pair_label:<24}{d_norm:>8.3f}{p_val:>8.3f}{ci_lo:>13.1f}{ci_hi:>13.1f}{delta_r2:>9.3f}  {incl0}")

    # ── Table 3 — Distance OOD ────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("TABLE 3 — Distance OOD au manifold baseline (Mahalanobis si cov inversible)")
    print(f"\n{'Carte':<12}{'TD':>4}{'N':>5}{'mean_OOD':>10}{'max_OOD':>10}{'min_OOD':>10}")
    print("-" * 53)

    for mname in new_maps:
        pcs = pcs_by_map[mname]
        tds = tds_by_map[mname]

        for td_val in (3, 4, 5):
            mask = tds == td_val
            if mask.sum() == 0:
                continue

            # Centroïde et covariance baseline au même TD
            bl_mask = np.array([tds_by_map[m][i] == td_val
                                 for m in BASELINE_MAPS if m in pcs_by_map
                                 for i in range(len(tds_by_map[m]))])
            bl_pcs_td = np.vstack([pcs_by_map[m][tds_by_map[m] == td_val]
                                    for m in BASELINE_MAPS if m in pcs_by_map and
                                    (tds_by_map[m] == td_val).sum() > 0])

            if len(bl_pcs_td) < 3:
                continue

            centroid = bl_pcs_td.mean(axis=0)
            cov = np.cov(bl_pcs_td.T)
            use_mahal = cov.ndim == 2 and np.linalg.matrix_rank(cov) == 2

            dists = []
            for pc in pcs[mask]:
                if use_mahal:
                    dists.append(_mahalanobis(pc, centroid, cov))
                else:
                    dists.append(float(np.linalg.norm(pc - centroid)))

            dist_arr = np.array(dists)
            dist_type = "M" if use_mahal else "E"
            print(f"{mname:<12}{td_val:>4}{mask.sum():>5}"
                  f"{dist_arr.mean():>10.3f}{dist_arr.max():>10.3f}{dist_arr.min():>10.3f}  [{dist_type}]")

    # ── Critères d'interprétation ─────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("Critères d'interprétation :")
    print("  d_norm M1 comparable à baseline (1.358) → domain shift robuste hors stanne/crohot")
    print("  Sep ratio TD similaire → continuum TD3→TD5 généralisé")
    print("  Slopes TD5 >0 sur nouvelles cartes → dépendance manifold→fitness robuste")
    print("  OOD faible  + slope similaire → manifold robuste hors domaine")
    print("  OOD fort    + slope similaire → invariance fonctionnelle malgré shift géométrique")
    print("  OOD fort    + slope cassée    → vrai domain shift, manifold non généralisé")
    print("  [M] = Mahalanobis   [E] = Euclidean (fallback si cov non inversible)")
    print(f"\n  NOTE : N=12 circuits/carte → tests exploratoires. Effect size > p-value.")


if __name__ == "__main__":
    main()
