"""
Phase A.8b -- Fitness alignment : PC1 encode-t-il la performance GA ?
Usage: python backend/scripts/analyze_fitness_alignment.py [path/to/intent_legs.csv]

Hierarchie (toutes informatives -- pas de gate) :
  GLOBAL       -- mixture baseline (non causal)
  Intra-map    -- controle effet TD | carte fixe
  Intra-TD     -- structure fonctionnelle par niveau de difficulte

Analyses par sous-groupe :
  D1 -- corr(mean_PC1_per_circuit, mean_fitness_per_circuit) : Pearson brut
  D2 -- partial_corr(PC1, fitness | leg_m) : controle couplage generatif

Toutes les analyses conditionnelles a (map, TD) sauf GLOBAL qui est une mixture.
"""

import sys
import csv
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
DEFAULT_CSV = "backend/debug/intent_legs.csv"


def load_csv(path: str) -> list:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def extract_matrix(
    rows: list,
    cols: list[str],
    map_filter: Optional[str] = None,
    td_filter: Optional[int] = None,
):
    X, meta = [], []
    for r in rows:
        if map_filter is not None and r.get("map_name", "") != map_filter:
            continue
        if td_filter is not None:
            try:
                td_val = int(r.get("td", 0))
            except ValueError:
                continue
            if td_val != td_filter:
                continue
        try:
            vec = [float(r[c]) for c in cols]
        except (ValueError, KeyError):
            continue
        fit_raw = r.get("fitness_total", "")
        X.append(vec)
        meta.append({
            "circuit_id":    r.get("circuit_id", "?"),
            "map_name":      r.get("map_name", ""),
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
    if len(X) < 10:
        print(f"  {name} : n < 10, skip")
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


def _run_slice(
    label: str,
    rows: list,
    map_filter: Optional[str] = None,
    td_filter: Optional[int] = None,
) -> None:
    X_aff, meta_aff = extract_matrix(rows, AFFORDANCE_COLS, map_filter, td_filter)
    X_int, meta_int = extract_matrix(rows, INTENT_COLS,     map_filter, td_filter)
    analyze_fitness_alignment(f"AFFORDANCE | {label}", X_aff, meta_aff)
    analyze_fitness_alignment(f"INTENT     | {label}", X_int, meta_int)


def main(path: str) -> None:
    rows = load_csv(path)
    print(f"Charge {len(rows)} lignes depuis {path}")

    n_with_fit = sum(1 for r in rows if r.get("fitness_total", "") not in ("", None))
    print(f"Lignes avec fitness_total : {n_with_fit}/{len(rows)}")
    if n_with_fit == 0:
        print("WARN : colonne fitness_total absente ou vide.")
        print("  -> Regenerer un circuit avec INTENT_DEBUG_CSV=1 apres la mise a jour genetic_algo.py")
        return

    has_map = any(r.get("map_name") for r in rows)

    # 1. GLOBAL — mixture baseline, non causal
    print("\n" + "=" * 60)
    print("GLOBAL (mixture baseline — non causal)")
    _run_slice("global", rows)

    if has_map:
        # 2. Intra-map — controle effet TD | carte fixe
        maps = sorted({r.get("map_name", "") for r in rows if r.get("map_name")})
        print("\n" + "=" * 60)
        print("INTRA-MAP (controle effet TD | carte fixe)")
        for m in maps:
            _run_slice(f"map={m}", rows, map_filter=m)

    # 3. Intra-TD — structure fonctionnelle par niveau
    tds = sorted({int(r.get("td", 0)) for r in rows if r.get("td", "").isdigit()})
    if len(tds) > 1:
        print("\n" + "=" * 60)
        print("INTRA-TD (secondaire)")
        for td in tds:
            _run_slice(f"TD{td}", rows, td_filter=td)

    print(f"\n{'=' * 60}")
    print("A.8b termine.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
