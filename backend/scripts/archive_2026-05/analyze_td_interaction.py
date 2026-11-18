"""
A.8c -- Interaction TD x PC1 + quadratic fit TD5 + decomposition fitness (Phase B).

Usage: python backend/scripts/analyze_td_interaction.py [path/to/intent_legs_a8b_v2.csv]

Sections:
  A1 -- OLS interaction fitness ~ PC1c + TD + PC1c*TD, slopes avec CI bootstrap
  A2 -- Fit lineaire vs quadratique sur crohot TD5 (N=12 circuits)
  A3 -- Decomposition fitness par terme (Phase B -- necessite score_a/penalty_b/score_d/score_h)

Bootstrap: resample circuits avec remise par stratum (map, TD) --
           unite = circuit entier, tous les legs groupes ensemble.
"""

import sys
import csv
import pathlib
from collections import defaultdict
from typing import Optional
import numpy as np

AFFORDANCE_COLS = [
    "parallel_affordance",
    "crossing_density",
    "exit_clarity",
    "contour_crossing_guidance",
]
INTENT_COLS = [
    "HANDRAIL_FOLLOW",
    "LINE_CROSSING",
    "ATTACK_POINT",
    "DIRECT_RISK_RUN",
    "RELIEF_CROSSING_GUIDANCE",
    "SAFETY_RECOVERY",
]
DECOMP_COLS = ["score_a", "penalty_b", "score_d", "score_h"]

DEFAULT_CSV = "backend/debug/intent_legs_a8b_v2.csv"
N_BOOT = 1000
RNG_SEED = 42

SEP = "=" * 62


# ── Utilities ────────────────────────────────────────────────────────────────

def load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_pca(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    Xc = X - X.mean(axis=0)
    _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    ev = S ** 2 / max(len(X) - 1, 1)
    evr = ev / ev.sum()
    return evr, Vt, Xc @ Vt.T


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    return coeffs


def r2_score(y: np.ndarray, y_pred: np.ndarray) -> float:
    ss_tot = float(np.var(y))
    return 1.0 - float(np.var(y - y_pred)) / ss_tot if ss_tot > 1e-12 else 0.0


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def build_interaction_design(pc1c: np.ndarray, td: np.ndarray) -> np.ndarray:
    """[intercept, PC1c, D_TD4, D_TD5, PC1c*D_TD4, PC1c*D_TD5]  (ref = TD3)"""
    d4 = (td == 4).astype(float)
    d5 = (td == 5).astype(float)
    return np.column_stack([np.ones(len(pc1c)), pc1c, d4, d5, pc1c * d4, pc1c * d5])


def slopes_from_coeffs(c: np.ndarray) -> tuple[float, float, float]:
    return float(c[1]), float(c[1] + c[4]), float(c[1] + c[5])


# ── Load + PCA + aggregate ───────────────────────────────────────────────────

def load_and_aggregate(csv_path: str, has_decomp: bool):
    """Returns (circ dict, pc1_global_mean, circ_ids list)."""
    rows = load_csv(csv_path)
    all_cols = AFFORDANCE_COLS + INTENT_COLS

    feat_rows, meta_rows = [], []
    for r in rows:
        try:
            vec = [float(r[c]) for c in all_cols]
        except (ValueError, KeyError):
            continue
        fit_raw = r.get("fitness_total", "")
        if fit_raw in ("", None):
            continue
        try:
            fitness = float(fit_raw)
        except ValueError:
            continue
        m: dict = {
            "circuit_id": r.get("circuit_id", ""),
            "td":         int(r.get("td", 0)),
            "map":        r.get("map_name", ""),
            "leg_m":      float(r.get("leg_m", 0.0)),
            "fitness":    fitness,
        }
        if has_decomp:
            for c in DECOMP_COLS:
                try:
                    m[c] = float(r.get(c, 0.0))
                except ValueError:
                    m[c] = 0.0
        feat_rows.append(vec)
        meta_rows.append(m)

    print(f"  {len(feat_rows)} legs valides")
    X = np.array(feat_rows, dtype=float)
    _, _, scores = run_pca(X)
    pc1_per_leg = scores[:, 0]

    circ: dict = {}
    for pc1, m in zip(pc1_per_leg, meta_rows):
        cid = m["circuit_id"]
        if cid not in circ:
            circ[cid] = {
                "td": m["td"], "map": m["map"],
                "fitness": m["fitness"],
                "pc1s": [],
                **({c: [] for c in DECOMP_COLS} if has_decomp else {}),
            }
        circ[cid]["pc1s"].append(pc1)
        if has_decomp:
            for c in DECOMP_COLS:
                circ[cid][c].append(m[c])

    return circ


def to_arrays(circ: dict, has_decomp: bool):
    cids    = list(circ.keys())
    td_arr  = np.array([circ[c]["td"]                   for c in cids], dtype=float)
    map_arr = np.array([circ[c]["map"]                  for c in cids])
    pc1_arr = np.array([np.mean(circ[c]["pc1s"])        for c in cids])
    fit_arr = np.array([circ[c]["fitness"]              for c in cids])
    decomp  = {}
    if has_decomp:
        for col in DECOMP_COLS:
            decomp[col] = np.array([np.mean(circ[c][col]) for c in cids])
    return cids, td_arr, map_arr, pc1_arr, fit_arr, decomp


# ── A1 — Interaction model ───────────────────────────────────────────────────

def a1_interaction(
    pc1_c: np.ndarray,
    td_arr: np.ndarray,
    map_arr: np.ndarray,
    fit_arr: np.ndarray,
    circ: dict,
    cids: list[str],
    rng: np.random.Generator,
) -> None:
    print(f"\n{SEP}")
    print("A1 — INTERACTION  fitness ~ PC1c + TD + PC1c*TD")
    print(SEP)

    X_design = build_interaction_design(pc1_c, td_arr)
    cond = np.linalg.cond(X_design)
    cond_warn = "  ⚠ WARN: mal conditionne — coefficients instables" if cond > 100 else ""
    print(f"  condition_number = {cond:.1f}{cond_warn}")

    coeffs = ols(X_design, fit_arr)
    s3, s4, s5 = slopes_from_coeffs(coeffs)

    # Bootstrap — unite = circuit entier par stratum (map, TD)
    strata: dict[tuple, list[int]] = defaultdict(list)
    for i, cid in enumerate(cids):
        strata[(circ[cid]["map"], circ[cid]["td"])].append(i)

    boot = np.full((N_BOOT, 3), np.nan)
    for b in range(N_BOOT):
        idx = []
        for idxs in strata.values():
            idx.extend(rng.choice(idxs, size=len(idxs), replace=True).tolist())
        idx = np.array(idx)
        try:
            cb = ols(build_interaction_design(pc1_c[idx], td_arr[idx]), fit_arr[idx])
            boot[b] = slopes_from_coeffs(cb)
        except Exception:
            pass

    ci_lo = np.nanpercentile(boot, 2.5, axis=0)
    ci_hi = np.nanpercentile(boot, 97.5, axis=0)

    rows_out = [
        ("TD3 (ref)", s3, ci_lo[0], ci_hi[0]),
        ("TD4",       s4, ci_lo[1], ci_hi[1]),
        ("TD5",       s5, ci_lo[2], ci_hi[2]),
    ]
    print(f"\n  {'Niveau':<12}  {'slope':>8}  {'CI95_lo':>9}  {'CI95_hi':>9}")
    print("  " + "-" * 46)
    for label, slope, lo, hi in rows_out:
        sig = " *" if (lo > 0 or hi < 0) else "  "
        print(f"  {label:<12}  {slope:>8.3f}  {lo:>9.3f}  {hi:>9.3f}{sig}")
    print()
    print("  [* CI95 excluant 0  |  PC1c centre : beta_TD = intercept a PC1=mean]")


# ── A2 — Quadratic fit TD5 ───────────────────────────────────────────────────

def a2_quadratic_td5(
    pc1_c: np.ndarray,
    td_arr: np.ndarray,
    fit_arr: np.ndarray,
    pc1_mean: float,
    rng: np.random.Generator,
) -> None:
    print(f"\n{SEP}")
    print("A2 — FIT QUADRATIQUE TD5  (crohot, N=12 circuits)")
    print(SEP)

    mask   = (td_arr == 5)
    pc1_t5 = pc1_c[mask]
    fit_t5 = fit_arr[mask]
    n      = int(mask.sum())
    print(f"  N = {n} circuits")

    # Linear
    Xl      = np.column_stack([np.ones(n), pc1_t5])
    cl      = ols(Xl, fit_t5)
    r2_lin  = r2_score(fit_t5, Xl @ cl)

    # Quadratic  [intercept, PC1c, PC1c²]
    Xq      = np.column_stack([np.ones(n), pc1_t5, pc1_t5 ** 2])
    cq      = ols(Xq, fit_t5)
    r2_quad = r2_score(fit_t5, Xq @ cq)
    delta   = r2_quad - r2_lin

    # b = cq[1], a = cq[2]  =>  fitness = c0 + b*PC1c + a*PC1c²
    a_coef, b_coef = float(cq[2]), float(cq[1])
    if abs(a_coef) > 1e-10:
        vertex_c  = -b_coef / (2.0 * a_coef)
        vertex_pc1 = vertex_c + pc1_mean
    else:
        vertex_c = vertex_pc1 = float("nan")

    curvature = (
        "concave (optimum interieur possible)" if a_coef < 0
        else "convexe (optimum aux bords)"
    )

    # Bootstrap CI (resample circuits, N=12)
    boot_a   = np.full(N_BOOT, np.nan)
    boot_vtx = np.full(N_BOOT, np.nan)
    for b in range(N_BOOT):
        idx = rng.integers(0, n, size=n)
        try:
            cb = ols(Xq[idx], fit_t5[idx])
            boot_a[b] = cb[2]
            if abs(cb[2]) > 1e-10:
                boot_vtx[b] = -cb[1] / (2.0 * cb[2]) + pc1_mean
        except Exception:
            pass

    a_lo, a_hi = np.nanpercentile(boot_a, [2.5, 97.5])
    v_lo, v_hi = np.nanpercentile(boot_vtx, [2.5, 97.5])

    print(f"\n  R2_lin  = {r2_lin:.3f}")
    print(f"  R2_quad = {r2_quad:.3f}")
    note_delta = "(faible — non-linearite non etablie)" if delta < 0.05 else "(substantiel — non-linearite plausible)"
    print(f"  delta_R2 = {delta:+.3f}  {note_delta}")
    print(f"\n  a (courbure)  = {a_coef:.4f}   CI95=[{a_lo:.4f}, {a_hi:.4f}]")
    print(f"  Vertex PC1*   = {vertex_pc1:.3f}    CI95=[{v_lo:.3f}, {v_hi:.3f}]  (echelle PC1 originale)")
    print(f"  Courbure      : {curvature}")

    print()
    if delta >= 0.05 and a_coef < 0 and a_lo < 0:
        print("  -> evidence consistent with a nonlinear TD5 regime")
        print(f"     optimum potentiel vers PC1={vertex_pc1:.2f}")
    elif delta >= 0.05:
        print("  -> courbure detectee mais signe ambigu (CI a couvre 0)")
    else:
        print("  -> pas d'evidence claire de non-linearite a N=12")
    print("  [Interpretation prudente — N=12 insuffisant pour conclusion forte]")


# ── A3 — Fitness decomposition (Phase B) ────────────────────────────────────

def vif(X_vars: np.ndarray) -> np.ndarray:
    """VIF[i] = 1/(1-R²) en regressant X_vars[:,i] sur les autres colonnes."""
    n, p = X_vars.shape
    vifs = np.zeros(p)
    for i in range(p):
        y = X_vars[:, i]
        others = np.delete(X_vars, i, axis=1)
        X_oth = np.column_stack([np.ones(n), others])
        pred = X_oth @ ols(X_oth, y)
        r2_i = r2_score(y, pred)
        vifs[i] = 1.0 / (1.0 - r2_i) if r2_i < 1.0 - 1e-12 else float("inf")
    return vifs


def standardize(arr: np.ndarray) -> np.ndarray:
    sd = arr.std()
    return (arr - arr.mean()) / sd if sd > 1e-10 else arr - arr.mean()


def a3_decomposition(
    pc1_c: np.ndarray,
    td_arr: np.ndarray,
    fit_arr: np.ndarray,
    decomp: dict[str, np.ndarray],
) -> None:
    print(f"\n{SEP}")
    print("A3 — DECOMPOSITION FITNESS PAR TERME  (TD5, N circuits)")
    print(SEP)

    if not decomp:
        print("\n  [Phase B requise]")
        print("  Colonnes manquantes : score_a, penalty_b, score_d, score_h")
        print("  -> Modifier genetic_algo.py (CSV write block ~L2326) pour exporter les composantes,")
        print("     puis relancer collect_fitness_data.py + mettre a jour _GLOBAL_FIELDS.")
        return

    # Analyse au niveau circuit (agregation deja faite dans decomp[col])
    mask   = (td_arr == 5)
    pc1_t5 = pc1_c[mask]
    fit_t5 = fit_arr[mask]
    n      = int(mask.sum())
    print(f"\n  N = {n} circuits TD5  (unite = circuit, pas leg)")

    comps = {col: decomp[col][mask] for col in DECOMP_COLS}

    # Niveau 1 — correlations simples
    print(f"\n  Correlations simples PC1c -> composante et composante -> fitness :")
    print(f"  {'composante':<14}  {'corr(PC1c,comp)':>16}  {'corr(comp,fitness)':>18}")
    print("  " + "-" * 54)
    for col in DECOMP_COLS:
        arr = comps[col]
        r_pc1 = pearson(pc1_t5, arr) if arr.std() > 1e-10 else float("nan")
        r_fit = pearson(arr, fit_t5)  if arr.std() > 1e-10 else float("nan")
        print(f"  {col:<14}  {r_pc1:>16.3f}  {r_fit:>18.3f}")

    # Niveau 2 — regression multiple standardisee + VIF
    print(f"\n  Regression standardisee : fitness ~ z(score_a) + z(penalty_b) + z(score_d) + z(score_h)")
    z_comps = np.column_stack([standardize(comps[c]) for c in DECOMP_COLS])
    z_fit   = standardize(fit_t5)
    X_reg   = np.column_stack([np.ones(n), z_comps])
    beta    = ols(X_reg, z_fit)
    r2_mult = r2_score(z_fit, X_reg @ beta)
    vifs    = vif(z_comps)

    print(f"  R2_multiple = {r2_mult:.3f}")
    print(f"\n  {'composante':<14}  {'beta_std':>9}  {'VIF':>7}")
    print("  " + "-" * 35)
    for i, col in enumerate(DECOMP_COLS):
        vif_warn = "  ⚠ colinearite" if vifs[i] > 5 else ""
        print(f"  {col:<14}  {beta[i+1]:>9.4f}  {vifs[i]:>7.2f}{vif_warn}")

    print()
    dominant = DECOMP_COLS[int(np.argmax(np.abs(beta[1:])))]
    print(f"  Terme dominant (|beta_std| max) : {dominant}")
    print()
    print("  Hypothese : penalty_b medie l'inversion —")
    print("    PC1c eleve en LD = jambes longues/directes => distance depassee => penalite B.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main(csv_path: str) -> None:
    print(f"=== A.8c analyze_td_interaction.py ===\n")
    print(f"Charge {csv_path}")

    # Detect Phase B columns
    sample_rows = load_csv(csv_path)
    has_decomp = bool(sample_rows) and all(c in sample_rows[0] for c in DECOMP_COLS)
    if has_decomp:
        print("  composantes fitness detectees (Phase B active)")
    else:
        print("  composantes fitness absentes (A3 = placeholder)")

    circ = load_and_aggregate(csv_path, has_decomp)
    cids, td_arr, map_arr, pc1_arr, fit_arr, decomp = to_arrays(circ, has_decomp)

    N = len(cids)
    print(f"  {N} circuits  TD3={int((td_arr==3).sum())}  TD4={int((td_arr==4).sum())}  TD5={int((td_arr==5).sum())}")

    pc1_mean = float(pc1_arr.mean())
    pc1_c    = pc1_arr - pc1_mean

    rng = np.random.default_rng(RNG_SEED)

    a1_interaction(pc1_c, td_arr, map_arr, fit_arr, circ, cids, rng)
    a2_quadratic_td5(pc1_c, td_arr, fit_arr, pc1_mean, rng)
    a3_decomposition(pc1_c, td_arr, fit_arr, decomp)

    print(f"\n{'=' * 62}")
    print("A.8c termine.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
