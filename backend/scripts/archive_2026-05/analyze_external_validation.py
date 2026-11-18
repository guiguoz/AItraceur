"""
Validation externe du manifold latent — généralisation sur nouvelles cartes.

Usage:
  python backend/scripts/analyze_external_validation.py \\
    backend/debug/intent_legs_post_fix_full.csv \\
    backend/debug/intent_legs_cerisy_full.csv \\
    backend/debug/intent_legs_feuguerolles_full.csv \\
    backend/debug/intent_legs_tourouvre_full.csv \\
    backend/debug/intent_legs_montmirel_full.csv

Premier CSV = baseline (stanne+crohot) : PCA + scaler fittés UNIQUEMENT dessus.
CSVs suivants = nouvelles cartes projetées via transform() dans l'espace figé.

CRITIQUE : scaler.fit() et PCA.fit() appelés uniquement sur la baseline.
Les nouvelles cartes utilisent transform() — jamais fit_transform().
Un refactoring qui appelle fit_transform() sur toutes les cartes invalide la logique OOD.

Métriques :
  Table 1 — sep_ratio TD, slope/R²/r par TD3 et TD5 par carte
  Table 2 — domain shift pairwise TD3 (M1 permutation / M2 bootstrap / M3 ΔR²)
  Table 3 — distance OOD Mahalanobis TD-conditionnelle
"""

from __future__ import annotations

import sys
import csv
import pathlib
import warnings
from collections import defaultdict
from itertools import combinations

import numpy as np
from scipy.stats import pearsonr


FEATURE_COLS = [
    "parallel_affordance", "crossing_density", "exit_clarity",
    "contour_crossing_guidance",
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
    "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
]

BASELINE_MAPS = {"stanne", "crohot"}
TD_LEVELS = [3, 4, 5]


# ── Chargement / agrégation ───────────────────────────────────────────────────

def _load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _aggregate_circuits(rows: list[dict]) -> list[dict]:
    """Une ligne = un circuit. Features = moyenne simple des jambes (pas médiane, pas pondérée)."""
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


# ── Statistiques ─────────────────────────────────────────────────────────────

def _pooled_cov_2d(pcs_a: np.ndarray, pcs_b: np.ndarray) -> np.ndarray:
    """Pooled covariance 2D : ((n_a-1)*cov_a + (n_b-1)*cov_b) / (n_a+n_b-2).

    Formule figée — réutilisée identiquement pour sep_ratio et M1. Pas de variantes.
    """
    n_a, n_b = len(pcs_a), len(pcs_b)
    cov_a = np.cov(pcs_a.T, ddof=1) if n_a >= 2 else np.zeros((2, 2))
    cov_b = np.cov(pcs_b.T, ddof=1) if n_b >= 2 else np.zeros((2, 2))
    denom = n_a + n_b - 2
    if denom <= 0:
        return np.zeros((2, 2))
    return ((n_a - 1) * cov_a + (n_b - 1) * cov_b) / denom


def _d_norm(mu_a: np.ndarray, mu_b: np.ndarray, pooled_cov: np.ndarray) -> float:
    """d_norm = ||mu_a - mu_b|| / sqrt(trace(pooled_cov)/2).

    Définition unifiée pour sep_ratio TD, M1, et reporting pairwise.
    NE PAS utiliser de variante (std scalaire, std PC1 seul, déterminant).
    """
    denom = np.sqrt(np.trace(pooled_cov) / 2.0)
    if denom < 1e-10:
        return float("nan")
    return float(np.linalg.norm(mu_a - mu_b) / denom)


def _sep_ratio_td(pcs: np.ndarray, tds: np.ndarray) -> float:
    """d_norm(centroïde_TD3, centroïde_TD5) dans l'espace PC1-PC2."""
    td3 = pcs[tds == 3]
    td5 = pcs[tds == 5]
    if len(td3) < 2 or len(td5) < 2:
        return float("nan")
    cov3 = np.cov(td3.T, ddof=1) if len(td3) >= 2 else np.zeros((2, 2))
    cov5 = np.cov(td5.T, ddof=1) if len(td5) >= 2 else np.zeros((2, 2))
    if np.trace(cov3) < 1e-10 or np.trace(cov5) < 1e-10:
        warnings.warn("Covariance TD quasi-dégénérée dans sep_ratio — résultat potentiellement instable")
    pcov = _pooled_cov_2d(td3, td5)
    return _d_norm(td3.mean(axis=0), td5.mean(axis=0), pcov)


def _slope_r2_r(pc1: np.ndarray, fitness: np.ndarray) -> tuple[float, float, float]:
    """OLS slope, R², Pearson r pour fitness ~ PC1.

    Retourne (nan, nan, nan) si variance PC1 ou fitness quasi nulle.
    """
    if len(pc1) < 3 or np.std(pc1) < 1e-8 or np.std(fitness) < 1e-8:
        return float("nan"), float("nan"), float("nan")
    X = np.column_stack([np.ones(len(pc1)), pc1])
    coef, *_ = np.linalg.lstsq(X, fitness, rcond=None)
    pred = X @ coef
    ss_res = float(np.sum((fitness - pred) ** 2))
    ss_tot = float(np.sum((fitness - fitness.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-10 else float("nan")
    r_val, _ = pearsonr(pc1, fitness)
    return float(coef[1]), r2, float(r_val)


# ── Tests domain shift ────────────────────────────────────────────────────────

def _m1_permutation(pcs_a: np.ndarray, pcs_b: np.ndarray,
                    n_perm: int = 2000) -> tuple[float, float]:
    """M1 : permutation test sur d_norm.

    IMPORTANT : effectuer UNIQUEMENT sur TD3 — évite contamination par la structure TD.
    NE PAS modifier pour utiliser un autre TD ou un mélange de TDs.

    p = (count + 1) / (n_perm + 1) — formule exacte two-sided, évite p=0.
    """
    pcov_obs = _pooled_cov_2d(pcs_a, pcs_b)
    d_obs = _d_norm(pcs_a.mean(axis=0), pcs_b.mean(axis=0), pcov_obs)
    if np.isnan(d_obs):
        return d_obs, float("nan")

    all_pcs = np.vstack([pcs_a, pcs_b])
    n_a = len(pcs_a)
    rng = np.random.default_rng(42)
    count = 0
    for _ in range(n_perm):
        perm = rng.permutation(len(all_pcs))
        g1 = all_pcs[perm[:n_a]]
        g2 = all_pcs[perm[n_a:]]
        pcov_perm = _pooled_cov_2d(g1, g2)
        d_perm = _d_norm(g1.mean(axis=0), g2.mean(axis=0), pcov_perm)
        if not np.isnan(d_perm) and d_perm >= d_obs:
            count += 1
    return d_obs, (count + 1) / (n_perm + 1)


def _m2_bootstrap_ci(fit_a: np.ndarray, fit_b: np.ndarray,
                     b: int = 1000) -> tuple[float, float]:
    """M2 : bootstrap percentile CI 95% sur mean_A - mean_B."""
    rng = np.random.default_rng(42)
    deltas = [
        float(rng.choice(fit_a, len(fit_a), replace=True).mean()
              - rng.choice(fit_b, len(fit_b), replace=True).mean())
        for _ in range(b)
    ]
    return float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))


def _m3_delta_r2(pc1: np.ndarray, fitness: np.ndarray, labels: np.ndarray) -> float:
    """M3 : ΔR² pairwise uniquement (jamais global multi-cartes — instable à N≈12).

    Réduit  : fitness ~ PC1 + map_label
    Complet : fitness ~ PC1 + map_label + PC1:map_label
    ΔR² = R²_complet - R²_réduit

    Interprétation qualitative uniquement : robuste si signe cohérent ET ΔR² > 0.05.
    """
    def _r2(X: np.ndarray, y: np.ndarray) -> float:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        ss_tot = ((y - y.mean()) ** 2).sum()
        return 1.0 - ((y - X @ coef) ** 2).sum() / ss_tot if ss_tot > 1e-10 else 0.0

    lf = labels.astype(float)
    X_reduced = np.column_stack([np.ones(len(pc1)), pc1, lf])
    X_full = np.column_stack([np.ones(len(pc1)), pc1, lf, pc1 * lf])
    return float(_r2(X_full, fitness) - _r2(X_reduced, fitness))


# ── OOD Mahalanobis ──────────────────────────────────────────────────────────

def _mahalanobis_dist(x: np.ndarray, mean: np.ndarray, cov: np.ndarray) -> float:
    """Mahalanobis avec ridge adaptatif max(1e-6, trace(cov)*1e-6) — stabilité à N≈12."""
    ridge = max(1e-6, float(np.trace(cov)) * 1e-6)
    cov_reg = cov + np.eye(cov.shape[0]) * ridge
    cond = float(np.linalg.cond(cov_reg))
    if cond > 1e8:
        warnings.warn(f"cov_reg conditionnée ({cond:.1e}) — distance OOD potentiellement instable")
    cov_inv = np.linalg.inv(cov_reg)
    diff = x - mean
    return float(np.sqrt(max(0.0, float(diff @ cov_inv @ diff))))


# ── Main ──────────────────────────────────────────────────────────────────────

def _f(v: float, fmt: str = ".2f") -> str:
    try:
        return "    —" if np.isnan(v) else f"{v:{fmt}}"
    except (TypeError, ValueError):
        return "    —"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python analyze_external_validation.py baseline.csv [new_map.csv ...]")
        sys.exit(1)

    print("Chargement des CSV :")
    all_circuits: list[dict] = []
    for path in sys.argv[1:]:
        if not pathlib.Path(path).exists():
            print(f"ERREUR: fichier introuvable : {path}")
            sys.exit(1)
        rows = _load_csv(path)
        circuits = _aggregate_circuits(rows)
        all_circuits.extend(circuits)
        maps_in_file = sorted({c["map_name"] for c in circuits})
        tds_in_file = sorted({c["td"] for c in circuits})
        print(f"  {pathlib.Path(path).name} : {len(circuits)} circuits — cartes: {maps_in_file}, TDs: {tds_in_file}")

    # Grouper par carte
    by_map: dict[str, list[dict]] = defaultdict(list)
    for c in all_circuits:
        by_map[c["map_name"]].append(c)

    # Assertions TD3/TD5 + N minimum — uniquement pour les nouvelles cartes
    # Baseline maps (stanne/crohot) sont validées par construction (stanne = TD3 only)
    for mname, circs in by_map.items():
        if mname in BASELINE_MAPS:
            continue
        tds_present = {c["td"] for c in circs}
        by_td: dict[int, list] = defaultdict(list)
        for c in circs:
            by_td[c["td"]].append(c)
        assert tds_present >= {3, 5}, f"{mname} manque TD3 ou TD5 (présents: {sorted(tds_present)})"
        assert len(by_td[3]) >= 8, f"{mname} TD3 : {len(by_td[3])} circuits (min 8)"
        assert len(by_td[5]) >= 8, f"{mname} TD5 : {len(by_td[5])} circuits (min 8)"

    map_names = sorted(by_map.keys())
    new_maps = [m for m in map_names if m not in BASELINE_MAPS]

    # ── PCA figée sur baseline (stanne+crohot) uniquement ────────────────────
    # CRITIQUE : scaler.fit() et PCA.fit() appelés uniquement sur baseline.
    # Les nouvelles cartes utilisent transform() — jamais fit_transform().
    baseline_circuits = [c for c in all_circuits if c["map_name"] in BASELINE_MAPS]
    if not baseline_circuits:
        print("ERREUR: aucun circuit baseline (stanne/crohot) trouvé.")
        sys.exit(1)

    X_baseline = _feature_matrix(baseline_circuits)
    mean_ = X_baseline.mean(axis=0)
    std_ = X_baseline.std(axis=0)  # ddof=0 (cohérent avec StandardScaler sklearn)
    std_[std_ == 0] = 1.0
    X_bl_scaled = (X_baseline - mean_) / std_

    # SVD = PCA(n_components=2) — figée, déterministe
    _, S, Vt = np.linalg.svd(X_bl_scaled, full_matrices=False)
    Vt2 = Vt[:2].copy()  # copie : l'orientation peut être modifiée sans affecter Vt

    total_var = float((S ** 2).sum())
    pc1_var_pct = S[0] ** 2 / total_var * 100
    pc2_var_pct = S[1] ** 2 / total_var * 100

    # Orientation canonique PC1 — FIXÉE UNE SEULE FOIS sur baseline.
    # TD5 doit avoir PC1 moyen > TD3 (continuum TD3→TD5 le long de PC1 positif).
    # NE PAS réorienter carte par carte — forcerait artificiellement le continuum OOD.
    baseline_tds = np.array([c["td"] for c in baseline_circuits])
    X_bl_init = X_bl_scaled @ Vt2.T
    mu_td5_bl = float(X_bl_init[baseline_tds == 5, 0].mean())
    mu_td3_bl = float(X_bl_init[baseline_tds == 3, 0].mean())
    if mu_td5_bl < mu_td3_bl:
        Vt2[0] *= -1  # toutes les projections via _project() héritent de cette orientation

    def _project(circuits: list[dict]) -> np.ndarray:
        """transform() uniquement — scaler+PCA figés sur baseline."""
        X = _feature_matrix(circuits)
        return ((X - mean_) / std_) @ Vt2.T  # (n, 2)

    print(f"\n{'=' * 72}")
    print(f"PCA baseline (stanne+crohot, {len(baseline_circuits)} circuits)")
    print(f"  explained_variance_ratio_ : PC1={pc1_var_pct:.1f}%  PC2={pc2_var_pct:.1f}%")
    print(f"  Orientation PC1 : TD5 > TD3 fixée sur baseline, héritée par projections OOD")
    print(f"  Nouvelles cartes : {new_maps or '(aucune)'}")

    # Projeter toutes les cartes dans l'espace baseline figé
    pcs_by_map: dict[str, np.ndarray] = {
        mname: _project(circs) for mname, circs in by_map.items()
    }
    tds_by_map: dict[str, np.ndarray] = {
        mname: np.array([c["td"] for c in circs]) for mname, circs in by_map.items()
    }
    fit_by_map: dict[str, np.ndarray] = {
        mname: np.array([c["fitness_total"] for c in circs]) for mname, circs in by_map.items()
    }

    # Std PC1 baseline (pour détecter extrapolation OOD excessive)
    bl_pcs_all = np.vstack([pcs_by_map[m] for m in sorted(BASELINE_MAPS) if m in pcs_by_map])
    baseline_pc1_std = float(bl_pcs_all[:, 0].std())

    # ── Table 1 — Métriques par carte ────────────────────────────────────────
    print(f"\n{'─' * 72}")
    print("TABLE 1 — Métriques par carte (espace PCA figé baseline)")
    hdr = (f"{'Carte':<14}{'N_TD3':>6}{'N_tot':>6}{'SepRatio':>10}"
           f"  {'Slope_TD3':>10}{'R²_TD3':>7}{'r_TD3':>7}"
           f"  {'Slope_TD5':>10}{'R²_TD5':>7}{'r_TD5':>7}")
    print(f"\n{hdr}")
    print("-" * 82)

    for mname in map_names:
        pcs = pcs_by_map[mname]
        tds = tds_by_map[mname]
        fit = fit_by_map[mname]
        n_td3 = int((tds == 3).sum())
        n_td5 = int((tds == 5).sum())
        n_tot = len(tds)
        sep = _sep_ratio_td(pcs, tds)

        s3, r2_3, r3 = _slope_r2_r(pcs[tds == 3, 0], fit[tds == 3]) if n_td3 >= 3 else (float("nan"),) * 3
        s5, r2_5, r5 = _slope_r2_r(pcs[tds == 5, 0], fit[tds == 5]) if n_td5 >= 3 else (float("nan"),) * 3

        print(f"{mname:<14}{n_td3:>6}{n_tot:>6}{_f(sep):>10}"
              f"  {_f(s3):>10}{_f(r2_3):>7}{_f(r3):>7}"
              f"  {_f(s5):>10}{_f(r2_5):>7}{_f(r5):>7}")

        if mname not in BASELINE_MAPS:
            pc1_max_abs = float(np.abs(pcs[:, 0]).max())
            if pc1_max_abs > 5 * baseline_pc1_std:
                print(f"  ⚠ {mname} : |PC1|_max={pc1_max_abs:.2f} > 5σ_bl={5*baseline_pc1_std:.2f} → extrapolation OOD excessive")

    # ── Table 2 — Domain shift pairwise TD3 ──────────────────────────────────
    print(f"\n{'─' * 72}")
    print("TABLE 2 — Domain shift pairwise TD3 (exploratoire, N faible)")
    # M1 effectué uniquement sur TD3 — évite contamination par la structure TD.
    # NE PAS modifier pour utiliser un autre TD ou un mélange de TDs.
    print("  M1 sur TD3 uniquement | M3 qualitatif (robuste si ΔR²>0.05 + signe cohérent)")
    hdr2 = f"{'Paire':<26}{'d_norm':>8}{'p_M1':>7}  {'ΔFit_lo':>8}{'ΔFit_hi':>9}  {'ΔR²_M3':>8}"
    print(f"\n{hdr2}")
    print("-" * 72)

    for m_a, m_b in combinations(map_names, 2):
        mask_a3 = tds_by_map[m_a] == 3
        mask_b3 = tds_by_map[m_b] == 3
        if mask_a3.sum() < 2 or mask_b3.sum() < 2:
            continue

        pcs_a3 = pcs_by_map[m_a][mask_a3]
        pcs_b3 = pcs_by_map[m_b][mask_b3]
        fit_a3 = fit_by_map[m_a][mask_a3]
        fit_b3 = fit_by_map[m_b][mask_b3]

        d_obs, p_m1 = _m1_permutation(pcs_a3, pcs_b3)
        ci_lo, ci_hi = _m2_bootstrap_ci(fit_a3, fit_b3)

        # M3 pairwise : réduit = fitness ~ PC1 + map_label
        pcs_pool = np.vstack([pcs_a3, pcs_b3])
        fit_pool = np.concatenate([fit_a3, fit_b3])
        labels = np.array([0] * len(pcs_a3) + [1] * len(pcs_b3))
        dr2 = _m3_delta_r2(pcs_pool[:, 0], fit_pool, labels)

        incl0 = "✓0" if ci_lo <= 0 <= ci_hi else "✗0"
        robust = " ← robust" if not np.isnan(dr2) and abs(dr2) > 0.05 else ""
        pair = f"{m_a} vs {m_b}"
        print(f"{pair:<26}{_f(d_obs, '.3f'):>8}{_f(p_m1, '.3f'):>7}  "
              f"{ci_lo:>8.1f}{ci_hi:>9.1f}  {_f(dr2, '.3f'):>8}  {incl0}{robust}")

    # ── Table 3 — Distance OOD Mahalanobis ───────────────────────────────────
    print(f"\n{'─' * 72}")
    print("TABLE 3 — Distance OOD Mahalanobis TD-conditionnelle (ridge adaptatif)")
    hdr3 = f"{'Carte':<14}{'TD':>4}{'N':>5}  {'mean_OOD':>10}{'max_OOD':>10}{'min_OOD':>10}"
    print(f"\n{hdr3}")
    print("-" * 55)

    for mname in new_maps:
        pcs = pcs_by_map[mname]
        tds = tds_by_map[mname]
        for td_val in TD_LEVELS:
            mask = tds == td_val
            if mask.sum() == 0:
                continue
            bl_parts = [
                pcs_by_map[m][tds_by_map[m] == td_val]
                for m in sorted(BASELINE_MAPS)
                if m in pcs_by_map and (tds_by_map[m] == td_val).sum() > 0
            ]
            if not bl_parts:
                continue
            bl_pcs_td = np.vstack(bl_parts)
            if len(bl_pcs_td) < 3:
                continue
            centroid = bl_pcs_td.mean(axis=0)
            cov = np.cov(bl_pcs_td.T, ddof=1)
            dists = np.array([_mahalanobis_dist(pc, centroid, cov) for pc in pcs[mask]])
            print(f"{mname:<14}{td_val:>4}{int(mask.sum()):>5}  "
                  f"{dists.mean():>10.3f}{dists.max():>10.3f}{dists.min():>10.3f}")

    # ── Critères d'interprétation ─────────────────────────────────────────────
    print(f"\n{'─' * 72}")
    print("Référence baseline stanne+crohot :")
    print("  PC1≈63%  sep_ratio_TD≈0.21  Slope_TD5≈+22.6  fitness_TD5≈29.7  CV≈0.76")
    print()
    print("Critères d'interprétation :")
    print("  d_norm M1 comparable  → domain shift robuste hors stanne/crohot")
    print("  sep_ratio TD similaire → continuum TD3→TD5 généralisé (manifold baseline)")
    print("  Slope_TD5 >0 + r>0    → dépendance manifold→fitness transférable")
    print("  OOD faible + slope similaire → manifold robuste hors domaine")
    print("  OOD fort   + slope similaire → invariance fonctionnelle malgré shift géo")
    print("  OOD fort   + slope cassée    → vrai domain shift, manifold non généralisé")
    print()
    print("  N≈12 circuits/carte → exploratoire. Effect size > p-value.")
    print("  M3 ΔR² qualitatif uniquement : robuste si ΔR²>0.05 + signe cohérent.")
    print("  Compatible latent geometry ≠ manifold causal universel.")


if __name__ == "__main__":
    main()
