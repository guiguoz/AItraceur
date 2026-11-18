"""
Q3 -- Domain shift test : stanne_td3 vs crohot_td3.

Usage: python backend/scripts/analyze_map_effects.py [path/to/intent_legs_a8b_v2.csv]

Comparaison stricte : TD=3 uniquement (N=22 circuits, 10 stanne + 12 crohot).
Exploratoire -- pas d'ajustement multiple comparisons avec A.8b/A.8c.

Sections:
  M1 -- Comparaison distributions PC dans l'espace latent (permutation test)
  M2 -- Comparaison distributions fitness (Cohen's d + CI bootstrap)
  M3 -- Interaction map x PC1 sur fitness (modeles emboires R2_A / R2_B / deltaR2)

Bootstrap: resample circuits avec remise par groupe (unite = circuit entier).
"""

import sys
import csv
from collections import defaultdict
import numpy as np

# Force UTF-8 output sur Windows (cp1252 par défaut)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_CSV = "backend/debug/intent_legs_a8b_v2.csv"

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

N_PERM   = 2000
N_BOOT   = 1000
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


def centroid_distance(g1: np.ndarray, g2: np.ndarray) -> float:
    return float(np.linalg.norm(g1.mean(axis=0) - g2.mean(axis=0)))


def sigma_pooled_2d(g1: np.ndarray, g2: np.ndarray) -> float:
    """sqrt(moyenne des variances intra-groupe sur PC1 et PC2)."""
    var1 = g1.var(axis=0)
    var2 = g2.var(axis=0)
    return float(np.sqrt(np.mean(np.concatenate([var1, var2]))))


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    n1, n2 = len(a), len(b)
    if n1 + n2 < 3:
        return 0.0
    pooled_sd = np.sqrt(
        ((n1 - 1) * np.var(a, ddof=1) + (n2 - 1) * np.var(b, ddof=1)) / (n1 + n2 - 2)
    )
    return float((a.mean() - b.mean()) / pooled_sd) if pooled_sd > 1e-10 else 0.0


# ── Load + filter TD3 + PCA ──────────────────────────────────────────────────

def load_td3(csv_path: str):
    """
    Filtre TD=3, PCA sur ces legs uniquement.
    Retourne (circ, pc12_arr, fit_arr, cids, map_arr, evr).
    """
    rows = load_csv(csv_path)
    all_cols = AFFORDANCE_COLS + INTENT_COLS

    feat_rows, meta_rows = [], []
    for r in rows:
        if int(r.get("td", 0)) != 3:
            continue
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
        feat_rows.append(vec)
        meta_rows.append({
            "circuit_id": r.get("circuit_id", ""),
            "map":        r.get("map_name", ""),
            "fitness":    fitness,
        })

    X = np.array(feat_rows, dtype=float)
    evr, _, scores = run_pca(X)
    pc12_per_leg = scores[:, :2]

    circ: dict = {}
    for pc12, m in zip(pc12_per_leg, meta_rows):
        cid = m["circuit_id"]
        if cid not in circ:
            circ[cid] = {"map": m["map"], "fitness": m["fitness"], "pc12s": []}
        circ[cid]["pc12s"].append(pc12)

    cids     = list(circ.keys())
    pc12_arr = np.array([np.mean(circ[c]["pc12s"], axis=0) for c in cids])
    fit_arr  = np.array([circ[c]["fitness"]               for c in cids])
    map_arr  = np.array([circ[c]["map"]                   for c in cids])

    return circ, pc12_arr, fit_arr, cids, map_arr, evr


# ── M1 — Comparaison distributions PC ────────────────────────────────────────

def m1_pc_distribution(
    pc12_arr: np.ndarray,
    map_arr: np.ndarray,
    rng: np.random.Generator,
) -> None:
    print(f"\n{SEP}")
    print("M1 — COMPARAISON ESPACE LATENT  stanne vs crohot (TD3)")
    print(SEP)

    mask_s = (map_arr == "stanne")
    mask_c = (map_arr == "crohot")
    g_s = pc12_arr[mask_s]
    g_c = pc12_arr[mask_c]
    n_s, n_c = len(g_s), len(g_c)

    obs_dist = centroid_distance(g_s, g_c)
    sigma_p  = sigma_pooled_2d(g_s, g_c)
    d_norm   = obs_dist / sigma_p if sigma_p > 1e-10 else float("nan")

    # Bootstrap CI sur la distance observée
    boot_dist = np.zeros(N_BOOT)
    for b in range(N_BOOT):
        bs = g_s[rng.integers(0, n_s, size=n_s)]
        bc = g_c[rng.integers(0, n_c, size=n_c)]
        boot_dist[b] = centroid_distance(bs, bc)
    ci_lo, ci_hi = np.percentile(boot_dist, [2.5, 97.5])

    # Permutation test (unite = circuit)
    all_pc12 = pc12_arr.copy()
    perm_dists = np.zeros(N_PERM)
    for p in range(N_PERM):
        shuffled = rng.permutation(map_arr)
        ps = all_pc12[shuffled == "stanne"]
        pc = all_pc12[shuffled == "crohot"]
        if len(ps) > 0 and len(pc) > 0:
            perm_dists[p] = centroid_distance(ps, pc)
    p_val = float((perm_dists >= obs_dist).mean())

    print(f"\n  N stanne={n_s}  N crohot={n_c}")
    print(f"\n  Centroïdes (PC1, PC2) :")
    print(f"    stanne : ({g_s[:,0].mean():+.3f}, {g_s[:,1].mean():+.3f})")
    print(f"    crohot : ({g_c[:,0].mean():+.3f}, {g_c[:,1].mean():+.3f})")
    print(f"\n  Distance centroïdes  : {obs_dist:.4f}   CI95=[{ci_lo:.4f}, {ci_hi:.4f}]")
    print(f"  sigma_pooled             : {sigma_p:.4f}")
    print(f"  d_norm (d/sigma_pooled)  : {d_norm:.3f}")
    print(f"  p-value permutation  : {p_val:.4f}  (N_PERM={N_PERM})")

    if p_val < 0.05:
        print("\n  -> Séparation dans l'espace latent significative (p<0.05)")
    else:
        print("\n  -> Pas de séparation claire dans l'espace latent (p≥0.05)")
    print("  [Exploratoire — N=10/12, interprétation prudente]")


# ── M2 — Comparaison fitness ──────────────────────────────────────────────────

def m2_fitness_comparison(
    fit_arr: np.ndarray,
    map_arr: np.ndarray,
    rng: np.random.Generator,
) -> None:
    print(f"\n{SEP}")
    print("M2 — COMPARAISON FITNESS  stanne vs crohot (TD3)")
    print(SEP)

    f_s = fit_arr[map_arr == "stanne"]
    f_c = fit_arr[map_arr == "crohot"]

    diff_obs = float(f_s.mean() - f_c.mean())
    d = cohens_d(f_s, f_c)

    boot_diff = np.zeros(N_BOOT)
    for b in range(N_BOOT):
        bs = rng.choice(f_s, size=len(f_s), replace=True)
        bc = rng.choice(f_c, size=len(f_c), replace=True)
        boot_diff[b] = bs.mean() - bc.mean()
    ci_lo, ci_hi = np.percentile(boot_diff, [2.5, 97.5])

    print(f"\n  stanne  mean={f_s.mean():.2f}  sd={f_s.std(ddof=1):.2f}  N={len(f_s)}")
    print(f"  crohot  mean={f_c.mean():.2f}  sd={f_c.std(ddof=1):.2f}  N={len(f_c)}")
    print(f"\n  diff (stanne - crohot) = {diff_obs:+.2f}   CI95=[{ci_lo:+.2f}, {ci_hi:+.2f}]")
    print(f"  Cohen's d              = {d:+.3f}")

    if ci_lo > 0 or ci_hi < 0:
        print("\n  -> Décalage fitness significatif entre les deux cartes")
    else:
        print("\n  -> CI inclut 0 — pas de décalage fitness établi")
    print("  [Fitness distribution shift — pas de jugement de qualité carte]")


# ── M3 — Interaction map × PC1 ───────────────────────────────────────────────

def m3_interaction(
    pc12_arr: np.ndarray,
    fit_arr: np.ndarray,
    map_arr: np.ndarray,
    cids: list[str],
    circ: dict,
    rng: np.random.Generator,
) -> None:
    print(f"\n{SEP}")
    print("M3 — INTERACTION map × PC1  (TD3, N=22 circuits)")
    print(SEP)

    pc1_c    = pc12_arr[:, 0] - pc12_arr[:, 0].mean()
    d_crohot = (map_arr == "crohot").astype(float)

    Xa = np.column_stack([np.ones(len(pc1_c)), pc1_c, d_crohot])
    Xb = np.column_stack([np.ones(len(pc1_c)), pc1_c, d_crohot, pc1_c * d_crohot])
    cond = np.linalg.cond(Xb)

    ca = ols(Xa, fit_arr)
    cb = ols(Xb, fit_arr)
    r2_a     = r2_score(fit_arr, Xa @ ca)
    r2_b     = r2_score(fit_arr, Xb @ cb)
    delta_r2 = r2_b - r2_a
    beta3    = float(cb[3])

    # Bootstrap par groupe (unite = circuit)
    strata_idx: dict[str, list[int]] = defaultdict(list)
    for i, cid in enumerate(cids):
        strata_idx[circ[cid]["map"]].append(i)

    boot_b3  = np.zeros(N_BOOT)
    boot_dr2 = np.zeros(N_BOOT)
    for b in range(N_BOOT):
        idx = []
        for idxs in strata_idx.values():
            idx.extend(rng.choice(idxs, size=len(idxs), replace=True).tolist())
        idx = np.array(idx)
        try:
            pc1b = pc1_c[idx]
            dcb  = d_crohot[idx]
            fitb = fit_arr[idx]
            Xab  = np.column_stack([np.ones(len(idx)), pc1b, dcb])
            Xbb  = np.column_stack([np.ones(len(idx)), pc1b, dcb, pc1b * dcb])
            r2ab = r2_score(fitb, Xab @ ols(Xab, fitb))
            cbb  = ols(Xbb, fitb)
            r2bb = r2_score(fitb, Xbb @ cbb)
            boot_b3[b]  = cbb[3]
            boot_dr2[b] = r2bb - r2ab
        except Exception:
            boot_b3[b] = boot_dr2[b] = np.nan

    b3_lo,  b3_hi  = np.nanpercentile(boot_b3,  [2.5, 97.5])
    dr2_lo, dr2_hi = np.nanpercentile(boot_dr2, [2.5, 97.5])

    cond_warn = "  ⚠ WARN: mal conditionne" if cond > 100 else ""
    print(f"\n  condition_number = {cond:.1f}{cond_warn}")
    print(f"\n  Modèle A (main effects)  : R2={r2_a:.3f}")
    print(f"  Modèle B (+interaction)  : R2={r2_b:.3f}")
    print(f"  ΔR²                      = {delta_r2:+.4f}   CI95=[{dr2_lo:+.4f}, {dr2_hi:+.4f}]")
    print(f"\n  β3 (interaction PC1c×crohot) = {beta3:+.4f}   CI95=[{b3_lo:+.4f}, {b3_hi:+.4f}]")

    sig_b3  = b3_lo > 0 or b3_hi < 0
    sig_dr2 = dr2_lo > 0.02

    if sig_b3 and sig_dr2:
        print("\n  -> Vrai domain shift structurel : pente PC1→fitness différente selon la carte")
    elif sig_b3 or sig_dr2:
        print("\n  -> Signal faible — évidence partielle d'interaction map×PC1")
    else:
        print("\n  -> ΔR² faible + CI[β3] couvre 0 : même manifold fonctionnel")
        print("     domain shift = déplacement de centroïde (M1), pas de changement de structure")
    print("  [Exploratoire — N=22, CI larges attendus]")


# ── Main ─────────────────────────────────────────────────────────────────────

def main(csv_path: str) -> None:
    print("=== Q3 analyze_map_effects.py — Domain Shift Test ===\n")
    print(f"Charge {csv_path}")

    circ, pc12_arr, fit_arr, cids, map_arr, evr = load_td3(csv_path)

    n_s = int((map_arr == "stanne").sum())
    n_c = int((map_arr == "crohot").sum())
    print(f"  TD3 : {len(cids)} circuits  (stanne={n_s}, crohot={n_c})")
    print(f"  Variance expliquée : PC1={evr[0]:.3f}  PC2={evr[1]:.3f}  "
          f"({'PC2 fiable' if evr[1] > 0.05 else 'PC2 potentiellement bruite'})")

    rng = np.random.default_rng(RNG_SEED)

    m1_pc_distribution(pc12_arr, map_arr, rng)
    m2_fitness_comparison(fit_arr, map_arr, rng)
    m3_interaction(pc12_arr, fit_arr, map_arr, cids, circ, rng)

    print(f"\n{SEP}")
    print("Q3 domain shift terminé.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
