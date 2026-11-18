"""
Phase A.7 — Bootstrap stability : manifold consistency under sampling noise
Usage: python backend/scripts/analyze_pca_bootstrap.py [path/to/intent_legs.csv]

Deux niveaux de test (par PCA — AFFORDANCE et INTENT) :
  intra-TD  : pour chaque TD avec n >= 15, resample n_boot fois → mean(|cos(PC1_full, PC1_boot)|)
              GATE : bootstrap_alignment > 0.80 pour tous les TDs
  global    : resample sur le dataset complet → diagnostic uniquement (non-gate)
              (peut être trompeur si TDs multimodaux — information structurelle seulement)

Preprocessing : identique à analyze_intent_pca.py
  - pas de résidualisation
  - centrage par run_pca() (X - X.mean(axis=0))
  - PCA locale par TD = centrage sur le sous-ensemble TD seul
  - normalisation L2 explicite des vecteurs PC1 (cohérence cos_sim)

Output : bootstrap_alignment par TD + gate A.7 (PROCEED A.8 / WAIT)
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
N_BOOT = 100
ALIGNMENT_THRESHOLD = 0.80
MIN_TD_N = 15


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
    """SVD-based PCA — identique a analyze_intent_pca.py. Vt[k] = direction PC k."""
    Xc = X - X.mean(axis=0)
    _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    ev = S ** 2 / max(len(X) - 1, 1)
    evr = ev / ev.sum()
    scores = Xc @ Vt.T
    return evr, Vt, scores


def cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 1e-10 else 0.0


def bootstrap_intra_td(X: np.ndarray, meta: list, base_seed: int = 42) -> dict:
    """
    Pour chaque TD avec n >= MIN_TD_N :
      - PC1_full_TD = Vt[0] normalise L2 de run_pca(sub_TD)  [centrage sur le TD seul]
      - n_boot = min(N_BOOT, 2*n) -- evite sur-echantillonnage sur petits TDs
      - seed par TD stable cross-run : base_seed + int.from_bytes(td, 'little') % 10000
      - bootstrap_alignment = mean(|cos(PC1_full, PC1_boot)|)
    Returns dict td -> {"bootstrap_alignment": float|None, "n": int, "n_boot": int}
    """
    td_groups: dict = {}
    for i, m in enumerate(meta):
        td_groups.setdefault(m["td"], []).append(i)

    results: dict = {}
    for td, idxs in sorted(td_groups.items()):
        sub = X[idxs]
        n = len(sub)
        if n < MIN_TD_N:
            results[td] = {"bootstrap_alignment": None, "n": n, "n_boot": 0}
            continue

        _, Vt_full, _ = run_pca(sub)
        pc1_full = Vt_full[0] / np.linalg.norm(Vt_full[0])

        n_boot = min(N_BOOT, 2 * n)
        td_seed = base_seed + int.from_bytes(str(td).encode(), "little") % 10000
        rng = np.random.default_rng(td_seed)

        cos_vals = []
        for _ in range(n_boot):
            boot_idx = rng.integers(0, n, size=n)
            try:
                _, Vt_b, _ = run_pca(sub[boot_idx])
                pc1_b = Vt_b[0] / np.linalg.norm(Vt_b[0])
                cos_vals.append(abs(cos_sim(pc1_full, pc1_b)))
            except Exception:
                pass

        alignment = float(np.mean(cos_vals)) if cos_vals else 0.0
        results[td] = {"bootstrap_alignment": alignment, "n": n, "n_boot": len(cos_vals)}
    return results


def bootstrap_global(X: np.ndarray, seed: int = 42):
    """
    Diagnostic uniquement -- non-gate.
    Resample sur le dataset complet -> mesure bootstrap_alignment de PC1_global.
    Peut etre trompeur si TDs multimodaux.
    """
    n = len(X)
    if n < 20:
        return None
    rng = np.random.default_rng(seed)
    _, Vt_full, _ = run_pca(X)
    pc1_full = Vt_full[0] / np.linalg.norm(Vt_full[0])

    n_boot = min(N_BOOT, 2 * n)
    cos_vals = []
    for _ in range(n_boot):
        boot_idx = rng.integers(0, n, size=n)
        try:
            _, Vt_b, _ = run_pca(X[boot_idx])
            pc1_b = Vt_b[0] / np.linalg.norm(Vt_b[0])
            cos_vals.append(abs(cos_sim(pc1_full, pc1_b)))
        except Exception:
            pass
    return float(np.mean(cos_vals)) if cos_vals else None


def run_bootstrap(name: str, X: np.ndarray, meta: list) -> bool:
    """Execute intra-TD + global pour un dataset. Retourne intra_td_ok."""
    n = len(X)
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Bootstrap {name} -- n={n} legs")
    if n < 20:
        print("  n < 20 : skip")
        return False

    results = bootstrap_intra_td(X, meta)

    intra_ok = True
    alignments = []
    for td, r in results.items():
        if r["bootstrap_alignment"] is None:
            print(f"  TD={td} n={r['n']}  (trop peu -- skip)")
            continue
        ok = r["bootstrap_alignment"] > ALIGNMENT_THRESHOLD
        alignments.append(r["bootstrap_alignment"])
        status = "ok" if ok else "LOW"
        print(f"  TD={td} n={r['n']} n_boot={r['n_boot']} "
              f"bootstrap_alignment={r['bootstrap_alignment']:.3f}  {status}")
        if not ok:
            intra_ok = False

    if alignments:
        print(f"  mean intra-TD alignment : {float(np.mean(alignments)):.3f}")
    print(f"  intra_td_ok : {'TRUE' if intra_ok else 'FALSE'}")

    g = bootstrap_global(X)
    if g is not None:
        print(f"  global bootstrap_alignment = {g:.3f}  [diagnostic -- non-gate]")

    return intra_ok


def main(path: str) -> None:
    rows = load_csv(path)
    print(f"Charge {len(rows)} lignes depuis {path}")

    X_aff, meta = extract_matrix(rows, AFFORDANCE_COLS)
    X_int, _    = extract_matrix(rows, INTENT_COLS)

    ok_aff = run_bootstrap("AFFORDANCE", X_aff, meta)
    ok_int = run_bootstrap("INTENT",     X_int, meta)

    print(f"\n{'=' * 60}")
    print("GATE A.7 :")
    print(f"  AFFORDANCE intra-TD ok : {'TRUE' if ok_aff else 'FALSE'}")
    print(f"  INTENT intra-TD ok     : {'TRUE' if ok_int else 'FALSE'}")
    if ok_aff and ok_int:
        print("  -> PROCEED A.8 : fitness alignment analysis")
    else:
        print("  -> WAIT -- resampling instability detected, collect more data per TD")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
