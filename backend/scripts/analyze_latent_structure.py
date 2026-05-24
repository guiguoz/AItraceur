"""
Phase A.8a -- Structure causale du systeme latent valide (A.6 + A.7 OK)
Usage: python backend/scripts/analyze_latent_structure.py [path/to/intent_legs.csv]

Trois directions d'analyse (toutes informatives -- pas de gate ici) :
  D1 -- PC1 vs leg_m    : regression lineaire/quadratique + profil par quartiles
  D2 -- TD dans PC space : centroides, separation, overlap inter-regime
  D3 -- Couplage interne : corr(PCk, TD) et corr(PCk, leg_m) pour k=1,2,3

Cas attendus :
  A -- PC1 monotone avec leg_m -> variable generative dominante (echelle)
  B -- saturation quadratique  -> regime non-lineaire (probable)
  C -- clusters TD separes      -> mixture model confirme

Output : texte uniquement -- pas de gate, pas de graphe
"""

import sys
import csv
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
DEFAULT_CSV = "backend/debug/intent_legs.csv"


def load_csv(path: str):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def extract_matrix(rows, cols):
    X, meta = [], []
    for r in rows:
        try:
            vec = [float(r[c]) for c in cols]
        except (ValueError, KeyError):
            continue
        X.append(vec)
        meta.append({
            "td":    r.get("td", "?"),
            "leg_m": float(r.get("leg_m", 0.0)),
        })
    return np.array(X, dtype=float), meta


def run_pca(X: np.ndarray):
    """SVD-based PCA -- identique a analyze_intent_pca.py."""
    Xc = X - X.mean(axis=0)
    _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    ev = S ** 2 / max(len(X) - 1, 1)
    evr = ev / ev.sum()
    scores = Xc @ Vt.T
    return evr, Vt, scores


def pearson(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def r_squared_linear(x: np.ndarray, y: np.ndarray) -> float:
    xc = x - x.mean()
    if np.dot(xc, xc) < 1e-12:
        return 0.0
    b = np.dot(xc, y - y.mean()) / np.dot(xc, xc)
    pred = y.mean() + b * xc
    ss_res = np.sum((y - pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0


def r_squared_quadratic(x: np.ndarray, y: np.ndarray) -> float:
    xc = x - x.mean()
    A = np.column_stack([xc, xc ** 2])
    yc = y - y.mean()
    try:
        coeffs, _, _, _ = np.linalg.lstsq(A, yc, rcond=None)
    except Exception:
        return 0.0
    pred = y.mean() + A @ coeffs
    ss_res = np.sum((y - pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0


def analyze_d1_pc1_legm(name: str, scores: np.ndarray, meta: list) -> None:
    """D1 -- Relation PC1 vs leg_m : forme et linearite."""
    leg_ms = np.array([m["leg_m"] for m in meta], dtype=float)
    pc1 = scores[:, 0]

    r = pearson(pc1, leg_ms)
    r2_lin  = r_squared_linear(leg_ms, pc1)
    r2_quad = r_squared_quadratic(leg_ms, pc1)
    delta_r2 = r2_quad - r2_lin

    print(f"  corr(PC1, leg_m) = {r:.3f}")
    print(f"  R2 linear={r2_lin:.3f}  R2 quadratic={r2_quad:.3f}  delta={delta_r2:+.3f}")
    if delta_r2 > 0.03:
        print("  -> non-linearite significative (saturation probable)")
    elif abs(r) > 0.50:
        print("  -> relation lineaire forte (leg_m = axe generatif dominant)")
    else:
        print("  -> couplage faible (PC1 peu dependant de leg_m)")

    # Profil par quartiles
    q = np.percentile(leg_ms, [0, 25, 50, 75, 100])
    print("  profil PC1 par quartile leg_m :")
    for i in range(4):
        lo, hi = q[i], q[i + 1]
        mask = (leg_ms >= lo) & (leg_ms <= hi)
        if mask.sum() > 0:
            print(f"    Q{i+1} [{lo:.0f}-{hi:.0f}m] n={mask.sum():3d} "
                  f"mean_PC1={pc1[mask].mean():+.3f}  std={pc1[mask].std():.3f}")


def analyze_d2_td_in_pcspace(name: str, scores: np.ndarray, meta: list) -> None:
    """D2 -- Structure TD dans le plan PC1-PC2 : centroides et separation."""
    pc1 = scores[:, 0]
    pc2 = scores[:, 1]
    tds = [m["td"] for m in meta]
    td_set = sorted(set(tds))

    centroids = {}
    print("  centroides TD dans PC1-PC2 :")
    for td in td_set:
        mask = np.array([t == td for t in tds])
        c1, c2 = pc1[mask].mean(), pc2[mask].mean()
        s1, s2 = pc1[mask].std(), pc2[mask].std()
        centroids[td] = (c1, c2)
        print(f"    TD={td} n={mask.sum():3d}  "
              f"centroid=({c1:+.3f}, {c2:+.3f})  "
              f"std=({s1:.3f}, {s2:.3f})")

    # Separation inter-centroide vs dispersion intra
    td_keys = list(centroids.keys())
    if len(td_keys) >= 2:
        inter_dists = []
        for i in range(len(td_keys)):
            for j in range(i + 1, len(td_keys)):
                a, b_ = np.array(centroids[td_keys[i]]), np.array(centroids[td_keys[j]])
                inter_dists.append(float(np.linalg.norm(a - b_)))
        intra_stds = []
        for td in td_set:
            mask = np.array([t == td for t in tds])
            intra_stds.append(float(np.sqrt(pc1[mask].var() + pc2[mask].var())))
        sep_ratio = float(np.mean(inter_dists)) / (float(np.mean(intra_stds)) + 1e-9)
        print(f"  separation ratio inter/intra = {sep_ratio:.2f}")
        if sep_ratio > 1.5:
            print("  -> clustering par TD (mixture model confirme)")
        elif sep_ratio > 0.8:
            print("  -> chevauchement partiel (regimes couples)")
        else:
            print("  -> forte superposition (TD ne separent pas l'espace latent)")


def analyze_d3_coupling(name: str, scores: np.ndarray, meta: list) -> None:
    """D3 -- Couplage interne : corr(PCk, leg_m) et corr(PCk, TD)."""
    leg_ms = np.array([m["leg_m"] for m in meta], dtype=float)
    try:
        tds_arr = np.array([float(m["td"]) for m in meta], dtype=float)
        td_ok = True
    except (ValueError, TypeError):
        td_ok = False

    n_pc = min(3, scores.shape[1])
    print(f"  {'PC':<4}  {'r_leg_m':>9}  {'r_td':>9}")
    for k in range(n_pc):
        r_lm = pearson(scores[:, k], leg_ms)
        r_td = pearson(scores[:, k], tds_arr) if td_ok else float("nan")
        print(f"  PC{k+1}  {r_lm:>+9.3f}  {r_td:>+9.3f}")


def analyze(name: str, X: np.ndarray, meta: list) -> None:
    if len(X) < 20:
        print(f"  {name} : n < 20, skip")
        return
    evr, Vt, scores = run_pca(X)
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"LATENT STRUCTURE {name} -- n={len(X)}  EV=[{evr[0]:.3f}, {evr[1]:.3f}, ...]")

    print("\n-- D1 : PC1 vs leg_m --")
    analyze_d1_pc1_legm(name, scores, meta)

    print("\n-- D2 : TD dans espace PCA --")
    analyze_d2_td_in_pcspace(name, scores, meta)

    print("\n-- D3 : couplage interne [diagnostic] --")
    analyze_d3_coupling(name, scores, meta)


def main(path: str) -> None:
    rows = load_csv(path)
    print(f"Charge {len(rows)} lignes depuis {path}")

    X_aff, meta = extract_matrix(rows, AFFORDANCE_COLS)
    X_int, _    = extract_matrix(rows, INTENT_COLS)

    analyze("AFFORDANCE", X_aff, meta)
    analyze("INTENT",     X_int, meta)

    print(f"\n{'=' * 60}")
    print("A.8a termine -- lecture des resultats avant A.8b (fitness integration)")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
