"""
Phase A.6b — PCA latent structure analysis + diagnostics interprétabilité
Usage: python backend/scripts/analyze_intent_pca.py [path/to/intent_legs.csv]

Deux PCAs séparées (pas indépendantes — Intent = transformation non-linéaire d'Affordance) :
  A — Affordance PCA  : parallel_affordance, crossing_density, exit_clarity, contour_crossing_guidance
  B — Intent PCA      : HANDRAIL_FOLLOW, LINE_CROSSING, ATTACK_POINT,
                        DIRECT_RISK_RUN, RELIEF_CROSSING_GUIDANCE, SAFETY_RECOVERY

Gate (par PCA) :
  T1 — explained variance  : EV1+EV2 >= 0.75
  T2 — orientation inter-TD : |cos(PC1_TD_a, PC1_TD_b)| >= 0.85  [heuristique — pas stabilité structurelle]
  D1 — eigenvalue ratios   : λ1/λ2 > 1.3 (axes distincts)
  D2 — sparsité intent     : mean actifs/leg ∈ [1.0, 4.5]

Diagnostics informatifs (non-gate) :
  T3 — corr(PC1, leg_m)    : couplage génératif, attendu élevé si TD mixés
  D3 — sign inconsistency  : orientation PC1 inter-TD (informatif)
  A.6d — axis attribution  : dominant feature, r_leg_m, r_td par PCk

Output : gate A.7 (PROCEED / WAIT)
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


def residualize(X: np.ndarray, meta: list) -> np.ndarray:
    """Retire l'effet linéaire de leg_m sur chaque colonne — supprime le biais géométrique."""
    leg_ms = np.array([m["leg_m"] for m in meta], dtype=float)
    lc = leg_ms - leg_ms.mean()
    denom = np.dot(lc, lc) + 1e-10
    X_res = X.copy()
    for j in range(X.shape[1]):
        b = np.dot(lc, X[:, j]) / denom
        X_res[:, j] = X[:, j] - b * lc
    return X_res


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


def analyze(name: str, X: np.ndarray, meta: list, cols: list) -> tuple:
    """Returns (valid: bool, r12: float)."""
    n = len(X)
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"PCA {name} — n={n} legs, {len(cols)} features")
    if n < 20:
        print("  ⚠  n < 20 : résultats non fiables — collecter plus de données")
        return False, 0.0

    evr, Vt, scores = run_pca(X)
    ev12 = float(evr[0] + evr[1])
    t1_ok = ev12 >= 0.75

    print(f"  EV ratio  : {[round(float(e), 3) for e in evr]}")
    print(f"  EV1+EV2   : {ev12:.3f}  {'✓ >= 0.75' if t1_ok else '✗ < 0.75'}")

    # D1 — séparation des axes (eigenvalue ratios)
    r12 = float(evr[0] / evr[1]) if len(evr) >= 2 and evr[1] > 1e-9 else float("inf")
    r23 = float(evr[1] / evr[2]) if len(evr) >= 3 and evr[2] > 1e-9 else float("inf")
    print(f"  λ1/λ2 : {r12:.2f}  {'OK >1.3' if r12 > 1.3 else 'WARN — axes potentiellement arbitraires'}")
    print(f"  λ2/λ3 : {r23:.2f}")

    print(f"  PC1       : {dict(zip(cols, [round(float(v), 3) for v in Vt[0]]))}")
    print(f"  PC2       : {dict(zip(cols, [round(float(v), 3) for v in Vt[1]]))}")

    # T2 — orientation heuristique inter-TD
    # NOTE: td_pcas (local TD) et PCA globale (run_pca) sont deux espaces analytiques distincts
    # td_pcas = projection PC1 locale par TD (heuristique T2 uniquement — pas PCA canonique)
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
            acs = abs(cs)
            ok = acs >= 0.85
            flip_note = " (sign flip)" if cs < 0 and acs >= 0.85 else ""
            print(f"  PC1 alignment heuristic TD{td_a}↔TD{td_b}: cos={cs:.3f}, |cos|={acs:.3f}  {'✓' if ok else '✗'}{flip_note}")
            if not ok:
                t2_ok = False
            # D3 — sign inconsistency informatif quand |cos| < 0.85
            if acs < 0.85:
                disagree = [cols[k] for k in range(len(cols))
                            if np.sign(td_pcas[td_a][k]) != np.sign(td_pcas[td_b][k])]
                print(f"    sign inconsistency : {disagree if disagree else '(none)'}")

    # T3 — couplage génératif (informative — non-gate)
    leg_ms = [m["leg_m"] for m in meta]
    r_legm = pearson(scores[:, 0], leg_ms)
    print(f"  corr(PC1, leg_m) = {r_legm:.3f}  [informative]")

    valid = t1_ok and t2_ok
    print(f"  LATENT_STRUCTURE_VALID_{name} : {'TRUE  ✓' if valid else 'FALSE ✗'}")
    return valid, r12


def main(path: str) -> None:
    rows = load_csv(path)
    print(f"Chargé {len(rows)} lignes depuis {path}")

    X_aff, meta = extract_matrix(rows, AFFORDANCE_COLS)
    X_int, _    = extract_matrix(rows, INTENT_COLS)

    # D2 — sparsité vecteurs intent (seuil 0.25 = gate GA)
    mean_active = 0.0
    if len(X_int) >= 1:
        n_active = (X_int > 0.25).sum(axis=1)
        mean_active = float(n_active.mean())
        counts: dict = {}
        for k in n_active:
            counts[int(k)] = counts.get(int(k), 0) + 1
        print(f"\n--- Sparsité vecteurs intent ---")
        print(f"  mean actifs/leg : {mean_active:.2f} / {len(INTENT_COLS)}")
        print(f"  distribution    : {counts}")
        if mean_active > 4.5:
            print("  WARN : vecteurs trop denses — PCA détecte magnitude globale, pas modes navigationnels")
        elif mean_active < 1.0:
            print("  WARN : vecteurs trop creux — signal insuffisant")

    valid_aff, r12_aff = analyze("AFFORDANCE", X_aff, meta, AFFORDANCE_COLS)
    valid_int, r12_int = analyze("INTENT",     X_int, meta, INTENT_COLS)

    # A.6d — axis attribution (informative, single canonical PCA per dataset)
    print(f"\n--- informative diagnostics ---")
    leg_ms_arr = np.array([m["leg_m"] for m in meta], dtype=float)
    tds_arr    = np.array([float(m["td"]) for m in meta if m["td"] != "?"], dtype=float)
    for label, X_, cols_ in [("AFFORDANCE", X_aff, AFFORDANCE_COLS),
                              ("INTENT",     X_int, INTENT_COLS)]:
        if len(X_) < 20:
            continue
        evr_, Vt_, sc_ = run_pca(X_)
        for k in range(min(3, len(evr_))):
            dom = cols_[int(np.argmax(np.abs(Vt_[k])))]
            r_lm = pearson(sc_[:, k], leg_ms_arr)
            r_td  = pearson(sc_[:, k], tds_arr) if len(tds_arr) == len(X_) else 0.0
            print(f"  {label} PC{k+1} EV={evr_[k]:.2f} dom={dom} "
                  f"r_leg_m={r_lm:.2f} r_td={r_td:.2f}")

    # Résumé + Gate A.7
    print(f"\n{'=' * 60}")
    print("RÉSUMÉ PHASE A.6b :")
    print(f"  Affordance structure valid : {valid_aff}  (λ1/λ2={r12_aff:.2f})")
    print(f"  Intent structure valid     : {valid_int}  (λ1/λ2={r12_int:.2f})")
    print(f"  Sparsité intent mean       : {mean_active:.2f} / {len(INTENT_COLS)}")

    sparsity_ok = 1.0 <= mean_active <= 4.5
    axes_ok_both = r12_aff > 1.3 and r12_int > 1.3

    print(f"\n--- Gate A.7 (alignment fitness/PCA) ---")
    print(f"  λ1/λ2 > 1.3 (aff + int)  : {'✓' if axes_ok_both else '✗ — A.7 prématurée'}")
    print(f"  sparsité 1.0–4.5          : {'✓' if sparsity_ok else '✗ — revoir vecteurs'}")
    print(f"  structure valide          : {'✓' if valid_aff and valid_int else '✗'}")

    if axes_ok_both and sparsity_ok and valid_aff and valid_int:
        print("  → PROCEED A.7 : corréler fitness et scores PC1/PC2")
    else:
        print("  → WAIT — investiguer diagnostics ci-dessus avant alignment")

    print()
    if not _t1_ok_hint(X_aff) or not _t1_ok_hint(X_int):
        print("  Hint EV < 0.75 : espace potentiellement 1-dimensionnel")
        print("  → un seul gradient terrain domine (ex: structure/densité linéaire)")
        print("  → envisager réduction à 2-3 features avant Phase B")


def _t1_ok_hint(X: np.ndarray) -> bool:
    if len(X) < 20:
        return True
    evr, _, _ = run_pca(X)
    return float(evr[0] + evr[1]) >= 0.75


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
