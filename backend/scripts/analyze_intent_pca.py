"""
Phase A.6 — PCA latent structure analysis
Usage: python backend/scripts/analyze_intent_pca.py [path/to/intent_legs.csv]

Deux PCAs séparées (pas indépendantes — Intent = transformation non-linéaire d'Affordance) :
  A — Affordance PCA  : parallel_affordance, crossing_density, exit_clarity, contour_crossing_guidance
  B — Intent PCA      : HANDRAIL_FOLLOW, LINE_CROSSING, ATTACK_POINT,
                        DIRECT_RISK_RUN, RELIEF_CROSSING_GUIDANCE, SAFETY_RECOVERY

Tests (par PCA) :
  T1 — explained variance  : EV1+EV2 >= 0.75
  T2 — stabilité inter-TD  : cos(PC1_TD_a, PC1_TD_b) > 0.85 OU sign_agree >= 0.75
  T3 — anti-biais leg_m    : |corr(PC1_scores, leg_m)| < 0.30

Output : résultats texte + LATENT_STRUCTURE_VALID_{AFFORDANCE|INTENT}
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
            "td":     r.get("td", "?"),
            "leg_m":  float(r.get("leg_m", 0.0)),
        })
    return np.array(X, dtype=float), meta


def run_pca(X: np.ndarray):
    """SVD-based PCA. Returns (evr, Vt, scores). Vt[k] = direction du PC k."""
    Xc = X - X.mean(axis=0)
    _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    ev = S ** 2 / max(len(X) - 1, 1)
    evr = ev / ev.sum()
    scores = Xc @ Vt.T
    return evr, Vt, scores


def cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 1e-10 else 0.0


def pearson(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def analyze(name: str, X: np.ndarray, meta: list, cols: list) -> bool:
    n = len(X)
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"PCA {name} — n={n} legs, {len(cols)} features")
    if n < 20:
        print("  ⚠  n < 20 : résultats non fiables — collecter plus de données")
        return False

    evr, Vt, scores = run_pca(X)
    ev12 = float(evr[0] + evr[1])
    t1_ok = ev12 >= 0.75

    print(f"  EV ratio  : {[round(float(e), 3) for e in evr]}")
    print(f"  EV1+EV2   : {ev12:.3f}  {'✓ >= 0.75' if t1_ok else '✗ < 0.75'}")
    print(f"  PC1       : {dict(zip(cols, [round(float(v), 3) for v in Vt[0]]))}")
    print(f"  PC2       : {dict(zip(cols, [round(float(v), 3) for v in Vt[1]]))}")

    # T2 — stabilité inter-TD
    td_groups: dict = {}
    for i, m in enumerate(meta):
        td_groups.setdefault(m["td"], []).append(i)

    td_pcas: dict = {}
    for td, idxs in sorted(td_groups.items()):
        sub = X[idxs]
        print(f"  TD={td} : {len(idxs)} legs", end="")
        if len(idxs) >= 15:
            _, Vt_td, _ = run_pca(sub)
            td_pcas[td] = Vt_td[0]
            print()
        else:
            print("  (trop peu pour PCA locale)")

    t2_ok = True
    tds = sorted(td_pcas.keys())
    for i in range(len(tds)):
        for j in range(i + 1, len(tds)):
            td_a, td_b = tds[i], tds[j]
            cs = cos_sim(td_pcas[td_a], td_pcas[td_b])
            # Critère souple : cosine > 0.85 OU même signe majorité (terrains contraints légitimes)
            sign_agree = float((np.sign(td_pcas[td_a]) == np.sign(td_pcas[td_b])).mean())
            ok = cs > 0.85 or sign_agree >= 0.75
            print(f"  stability PC1 TD{td_a}↔TD{td_b}: cos={cs:.3f}, sign_agree={sign_agree:.2f}  {'✓' if ok else '✗'}")
            if not ok:
                t2_ok = False

    # T3 — anti-biais géométrique
    leg_ms = [m["leg_m"] for m in meta]
    bias_corr = abs(pearson(scores[:, 0], leg_ms))
    t3_ok = bias_corr < 0.30
    print(f"  anti-bias |corr(PC1, leg_m)| = {bias_corr:.3f}  {'✓ < 0.30' if t3_ok else '✗ >= 0.30'}")

    valid = t1_ok and t2_ok and t3_ok
    print(f"  LATENT_STRUCTURE_VALID_{name} : {'TRUE  ✓' if valid else 'FALSE ✗'}")
    return valid


def main(path: str) -> None:
    rows = load_csv(path)
    print(f"Chargé {len(rows)} lignes depuis {path}")

    X_aff, meta = extract_matrix(rows, AFFORDANCE_COLS)
    X_int, _    = extract_matrix(rows, INTENT_COLS)

    valid_aff = analyze("AFFORDANCE", X_aff, meta, AFFORDANCE_COLS)
    valid_int = analyze("INTENT",     X_int, meta, INTENT_COLS)

    print(f"\n{'=' * 60}")
    print("RÉSUMÉ PHASE B :")
    print(f"  Affordance structure valid : {valid_aff}")
    print(f"  Intent structure valid     : {valid_int}")
    if valid_aff and valid_int:
        print("  → GO Phase B : activer W_DIRECT_RUN + W_RELIEF (poids faibles, forêt TD≥3)")
    else:
        print("  → NO-GO : rester log-only — investiguer composantes instables ci-dessus")

    print()
    if not t1_ok_hint(X_aff) or not t1_ok_hint(X_int):
        print("  Hint EV < 0.75 : espace potentiellement 1-dimensionnel")
        print("  → un seul gradient terrain domine (ex: structure/densité linéaire)")
        print("  → envisager réduction à 2-3 features avant Phase B")


def t1_ok_hint(X: np.ndarray) -> bool:
    if len(X) < 20:
        return True
    evr, _, _ = run_pca(X)
    return float(evr[0] + evr[1]) >= 0.75


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
