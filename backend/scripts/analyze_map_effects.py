#!/usr/bin/env python3
"""
Phase A.8b Q3 — Domain shift test (map effect).

Compare stanne_td3 vs crohot_td3 : meme TD, cartes differentes.
Question : est-ce que la geometrie des intents depend du terrain ?

NE PAS agreger mentalement avec Q1/Q2 (analyze_fitness_alignment.py).
Ce script repond a une question differente : structure environnementale.

Usage: python backend/scripts/analyze_map_effects.py [path/to/intent_legs_a8b_v2.csv]
"""

import csv
import sys
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

DEFAULT_CSV = "backend/debug/intent_legs_a8b_v2.csv"


def load_csv(path: str) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def extract(rows: list, cols: list[str], map_name: str, td: int) -> Optional[np.ndarray]:
    vecs = []
    for r in rows:
        if r.get("map_name") != map_name:
            continue
        try:
            if int(r.get("td", 0)) != td:
                continue
        except ValueError:
            continue
        try:
            vecs.append([float(r[c]) for c in cols])
        except (ValueError, KeyError):
            continue
    return np.array(vecs, dtype=float) if vecs else None


def pca_scores(X: np.ndarray) -> np.ndarray:
    Xc = X - X.mean(axis=0)
    _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
    return Xc @ Vt.T


def centroid_dist(a: np.ndarray, b: np.ndarray) -> float:
    """L2 distance between PC1/PC2 centroids."""
    ca = a[:, :2].mean(axis=0)
    cb = b[:, :2].mean(axis=0)
    return float(np.linalg.norm(ca - cb))


def overlap_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """Fraction of points from A whose PC1 falls within B's [min, max] on PC1."""
    lo, hi = b[:, 0].min(), b[:, 0].max()
    return float(np.mean((a[:, 0] >= lo) & (a[:, 0] <= hi)))


def print_distribution(label: str, X: np.ndarray) -> None:
    pc1 = X[:, 0]
    print(f"  {label:20s} n={len(X):4d}  "
          f"PC1 mean={pc1.mean():.3f}  std={pc1.std():.3f}  "
          f"[{pc1.min():.3f}, {pc1.max():.3f}]")


def domain_shift_test(
    feat_label: str,
    cols: list[str],
    rows: list,
    map_a: str,
    map_b: str,
    td: int,
) -> None:
    sep = "=" * 62
    print(f"\n{sep}")
    print(f"DOMAIN SHIFT — {feat_label} | TD{td} : {map_a} vs {map_b}")

    Xa = extract(rows, cols, map_a, td)
    Xb = extract(rows, cols, map_b, td)

    if Xa is None or len(Xa) < 5:
        print(f"  {map_a} : insuffisant (n={len(Xa) if Xa is not None else 0}), skip")
        return
    if Xb is None or len(Xb) < 5:
        print(f"  {map_b} : insuffisant (n={len(Xb) if Xb is not None else 0}), skip")
        return

    # PCA on the combined space to compare on the same axes
    X_all = np.vstack([Xa, Xb])
    Xc = X_all - X_all.mean(axis=0)
    _, _, Vt = np.linalg.svd(Xc, full_matrices=False)

    Sa = (Xa - X_all.mean(axis=0)) @ Vt.T
    Sb = (Xb - X_all.mean(axis=0)) @ Vt.T

    print_distribution(map_a, Sa)
    print_distribution(map_b, Sb)

    cd = centroid_dist(Sa, Sb)
    ov = overlap_ratio(Sa, Sb)
    print(f"\n  Centroid dist (PC1/PC2) = {cd:.3f}")
    print(f"  Overlap {map_a}→{map_b} PC1 = {ov:.2f}  (1.0=full overlap)")

    if cd < 0.5 and ov > 0.8:
        print("  -> faible shift : geometrie stable entre cartes")
    elif cd < 1.5 and ov > 0.5:
        print("  -> shift modere : adaptation partielle au terrain")
    else:
        print("  -> fort shift : geometrie sensible au terrain (OOD)")


def main(path: str) -> None:
    rows = load_csv(path)
    print(f"Charge {len(rows)} lignes depuis {path}")

    maps = sorted({r.get("map_name", "") for r in rows if r.get("map_name")})
    tds  = sorted({int(r["td"]) for r in rows if r.get("td", "").isdigit()})
    print(f"Cartes : {maps}")
    print(f"TDs    : {tds}")

    if len(maps) < 2:
        print("WARN: moins de 2 cartes — domain shift test impossible")
        return

    # Test principal : stanne_td3 vs crohot_td3 — effet carte, TD fixe
    if "stanne" in maps and "crohot" in maps and 3 in tds:
        domain_shift_test("AFFORDANCE", AFFORDANCE_COLS, rows, "stanne", "crohot", td=3)
        domain_shift_test("INTENT",     INTENT_COLS,     rows, "stanne", "crohot", td=3)

    # Tests secondaires : crohot TD3 vs TD4 vs TD5 — effet TD, carte fixe
    if "crohot" in maps:
        crohot_tds = sorted({int(r["td"]) for r in rows
                             if r.get("map_name") == "crohot" and r.get("td", "").isdigit()})
        if len(crohot_tds) >= 2:
            print(f"\n{'=' * 62}")
            print(f"EFFET TD (carte fixe = crohot) — reference pour interpretation Q3")
            for feat_label, cols in [("AFFORDANCE", AFFORDANCE_COLS), ("INTENT", INTENT_COLS)]:
                for i, td_a in enumerate(crohot_tds):
                    for td_b in crohot_tds[i + 1:]:
                        Xa = extract(rows, cols, "crohot", td_a)
                        Xb = extract(rows, cols, "crohot", td_b)
                        if Xa is None or Xb is None or len(Xa) < 5 or len(Xb) < 5:
                            continue
                        X_all = np.vstack([Xa, Xb])
                        mean_all = X_all.mean(axis=0)
                        Xc = X_all - mean_all
                        _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
                        Sa = (Xa - mean_all) @ Vt.T
                        Sb = (Xb - mean_all) @ Vt.T
                        sep_label = f"\n  crohot TD{td_a} vs TD{td_b} ({feat_label})"
                        print(sep_label)
                        print_distribution(f"TD{td_a}", Sa)
                        print_distribution(f"TD{td_b}", Sb)
                        cd = centroid_dist(Sa, Sb)
                        ov = overlap_ratio(Sa, Sb)
                        print(f"  Centroid dist={cd:.3f}  Overlap={ov:.2f}")

    print(f"\n{'=' * 62}")
    print("Q3 domain shift test termine.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
