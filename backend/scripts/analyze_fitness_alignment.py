"""
Phase A.8b -- Fitness alignment : PC1 encode-t-il la performance GA ?
Usage: python backend/scripts/analyze_fitness_alignment.py [path/to/intent_legs.csv]

Deux analyses (toutes informatives -- pas de gate) :
  D1 -- corr(mean_PC1_per_circuit, mean_fitness_per_circuit) : Pearson brut
  D2 -- partial_corr(PC1, fitness | leg_m) : controle le couplage generatif

Hypothese : si PC1 encode la geographie (non la performance), r_partial ~ 0.
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
        fit_raw = r.get("fitness_total", "")
        X.append(vec)
        meta.append({
            "circuit_id":    r.get("circuit_id", "?"),
            "td":            r.get("td", "?"),
            "leg_m":         float(r.get("leg_m", 0.0)),
            "fitness_total": float(fit_raw) if fit_raw not in ("", None) else None,
        })
    return np.array(X, dtype=float), meta


def run_pca(X: np.ndarray):
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


def partial_corr(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> float:
    """corr(x, y | z) -- residualise x et y sur z, puis Pearson."""
    def residualize(v: np.ndarray, covar: np.ndarray) -> np.ndarray:
        zc = covar - covar.mean()
        denom = float(np.dot(zc, zc)) + 1e-10
        b = np.dot(zc, v - v.mean()) / denom
        return v - b * zc

    return pearson(residualize(x, z), residualize(y, z))


def analyze_fitness_alignment(name: str, X: np.ndarray, meta: list) -> None:
    if len(X) < 20:
        print(f"  {name} : n < 20, skip")
        return

    _, _, scores = run_pca(X)
    pc1 = scores[:, 0]

    circuit_groups: dict = {}
    for i, m in enumerate(meta):
        circuit_groups.setdefault(m["circuit_id"], []).append(i)

    mean_pc1, mean_fit, mean_legm = [], [], []
    for cid, idxs in circuit_groups.items():
        fit_vals = [meta[i]["fitness_total"] for i in idxs if meta[i]["fitness_total"] is not None]
        if not fit_vals:
            continue
        mean_pc1.append(float(np.mean(pc1[idxs])))
        mean_fit.append(float(np.mean(fit_vals)))
        mean_legm.append(float(np.mean([meta[i]["leg_m"] for i in idxs])))

    n_circ = len(mean_pc1)
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"FITNESS ALIGNMENT {name} -- {len(X)} legs, {n_circ} circuits")

    if n_circ < 5:
        print(f"  n_circuits={n_circ} < 5 -- pas assez pour correlation")
        return

    mp = np.array(mean_pc1)
    mf = np.array(mean_fit)
    ml = np.array(mean_legm)

    r_raw     = pearson(mp, mf)
    r_partial = partial_corr(mp, mf, ml)

    print(f"  corr(mean_PC1, fitness)            = {r_raw:.3f}")
    print(f"  partial_corr(PC1, fitness | leg_m) = {r_partial:.3f}")

    if abs(r_partial) > 0.40:
        print("  -> signal modere : PC1 encode partiellement la qualite GA")
    elif abs(r_partial) > 0.20:
        print("  -> signal faible : couplage marginal")
    else:
        print("  -> pas de signal : PC1 encode la geographie, pas la performance")

    n_with_fit = sum(1 for m in meta if m["fitness_total"] is not None)
    print(f"  (legs avec fitness_total : {n_with_fit}/{len(meta)})")


def main(path: str) -> None:
    rows = load_csv(path)
    print(f"Charge {len(rows)} lignes depuis {path}")

    n_with_fit = sum(1 for r in rows if r.get("fitness_total", "") not in ("", None))
    print(f"Lignes avec fitness_total : {n_with_fit}/{len(rows)}")
    if n_with_fit == 0:
        print("WARN : colonne fitness_total absente ou vide.")
        print("  -> Regenerer un circuit avec INTENT_DEBUG_CSV=1 apres la mise a jour genetic_algo.py")
        return

    X_aff, meta = extract_matrix(rows, AFFORDANCE_COLS)
    X_int, _    = extract_matrix(rows, INTENT_COLS)

    analyze_fitness_alignment("AFFORDANCE", X_aff, meta)
    analyze_fitness_alignment("INTENT",     X_int, meta)

    print(f"\n{'=' * 60}")
    print("A.8b termine.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
