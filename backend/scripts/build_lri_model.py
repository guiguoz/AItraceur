"""
Phase B -- Build du modele LRI fige (Latent Regime Index).

Produit backend/data/lri_baseline.json a partir de la baseline stanne+crohot.

Usage:
  python backend/scripts/build_lri_model.py [baseline_csv]
  # Default: backend/debug/intent_legs_post_fix_full.csv

Sorties:
  backend/data/lri_baseline.json

Contraintes architecturales :
- PCA + scaler fites sur baseline uniquement
- pca_components deja flippe (pc1_sign_flip applique une seule fois ici)
- cluster_centroids_pc = centroids 10D projetes dans PC space (pour runtime)
- cluster_centroids_raw = centroids en features brutes (pour diagnostic)
- regime_names : labels provisoires regime_0/regime_1 -- a renommer apres Phase A
- k selectionne par silhouette sur 10D scaled baseline
"""

from __future__ import annotations

import sys
import csv
import json
import pathlib
from collections import defaultdict

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score


FEATURE_COLS = [
    "parallel_affordance", "crossing_density", "exit_clarity",
    "contour_crossing_guidance",
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
    "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
]

BASELINE_MAPS = {"stanne", "crohot"}
K_RANGE = [2, 3, 4, 5]

DEFAULT_CSV = "backend/debug/intent_legs_post_fix_full.csv"
OUTPUT_PATH = pathlib.Path("backend/data/lri_baseline.json")


# -- Chargement / agregation --------------------------------------------------

def _load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _aggregate_circuits(rows: list[dict]) -> list[dict]:
    """Une ligne = un circuit. Features = moyenne simple des jambes."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["circuit_id"]].append(row)

    circuits = []
    for cid, legs in groups.items():
        rec: dict = {
            "circuit_id": cid,
            "map_name": legs[0].get("map_name", "unknown"),
            "td": int(legs[0]["td"]),
        }
        for col in FEATURE_COLS:
            vals = [float(leg[col]) for leg in legs if col in leg and leg[col] != ""]
            rec[col] = float(np.mean(vals)) if vals else 0.0
        circuits.append(rec)
    return circuits


def _feature_matrix(circuits: list[dict]) -> np.ndarray:
    return np.array([[c[col] for col in FEATURE_COLS] for c in circuits], dtype=float)


# -- Main ---------------------------------------------------------------------

def main() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV

    if not pathlib.Path(csv_path).exists():
        print(f"ERREUR: fichier introuvable : {csv_path}")
        sys.exit(1)

    rows = _load_csv(csv_path)
    all_circuits = _aggregate_circuits(rows)
    baseline_circuits = [c for c in all_circuits if c["map_name"] in BASELINE_MAPS]

    if not baseline_circuits:
        print("ERREUR: aucun circuit baseline (stanne/crohot) dans le CSV.")
        sys.exit(1)

    print(f"Baseline : {len(baseline_circuits)} circuits "
          f"({sorted(set(c['map_name'] for c in baseline_circuits))})")

    # -- PCA fige sur baseline -------------------------------------------------
    X_baseline = _feature_matrix(baseline_circuits)
    mean_ = X_baseline.mean(axis=0)
    std_ = X_baseline.std(axis=0)  # ddof=0
    std_[std_ == 0] = 1.0
    X_bl_scaled = (X_baseline - mean_) / std_

    _, S, Vt = np.linalg.svd(X_bl_scaled, full_matrices=False)
    Vt2 = Vt[:2].copy()
    total_var = float((S ** 2).sum())
    pc1_var_pct = S[0] ** 2 / total_var * 100

    # Orientation canonique PC1 -- appliquee ici, stockee dans pca_components
    baseline_tds = np.array([c["td"] for c in baseline_circuits])
    X_bl_init = X_bl_scaled @ Vt2.T
    mu_td5_bl = float(X_bl_init[baseline_tds == 5, 0].mean())
    mu_td3_bl = float(X_bl_init[baseline_tds == 3, 0].mean())
    pc1_sign_flip = bool(mu_td5_bl < mu_td3_bl)
    if pc1_sign_flip:
        Vt2[0] *= -1  # flip stocke dans Vt2 -- lri_model.py n'a pas a flipper

    pc_scores_baseline = X_bl_scaled @ Vt2.T  # (n_bl, 2)

    print(f"PCA : PC1={pc1_var_pct:.1f}%  pc1_sign_flip={pc1_sign_flip}")

    # -- Selection k par silhouette -------------------------------------------
    silhouettes: dict[int, float] = {}
    for k in K_RANGE:
        km = KMeans(n_clusters=k, random_state=0, n_init=10)
        labels_k = km.fit_predict(X_bl_scaled)
        silhouettes[k] = silhouette_score(X_bl_scaled, labels_k)

    k_opt = max(silhouettes, key=silhouettes.__getitem__)
    print(f"Silhouettes : { {k: round(v, 4) for k, v in silhouettes.items()} }")
    print(f"k optimal = {k_opt}")

    # -- KMeans final ---------------------------------------------------------
    km_final = KMeans(n_clusters=k_opt, random_state=0, n_init=10)
    km_final.fit(X_bl_scaled)
    centroids_10d_scaled = km_final.cluster_centers_  # (k, 10)

    # Centroids PC = centroids 10D projetes (pour nearest centroid runtime)
    centroids_pc = (centroids_10d_scaled @ Vt2.T).tolist()  # (k, 2)

    # Centroids bruts (pour diagnostic et interprétation)
    centroids_raw = (centroids_10d_scaled * std_ + mean_).tolist()  # (k, 10)

    # Labels provisoires -- a renommer apres analyse features Phase A
    regime_names = {str(i): f"regime_{i}" for i in range(k_opt)}

    # -- Construire JSON -------------------------------------------------------
    model = {
        "feature_cols": FEATURE_COLS,
        "pca_mean": mean_.tolist(),
        "pca_std": std_.tolist(),
        "pca_components": Vt2.tolist(),   # (2, 10) -- deja flippe
        "pc1_sign_flip": pc1_sign_flip,   # trace pour audit -- lri_model.py n'y touche pas
        "cluster_centroids_pc": centroids_pc,   # runtime nearest centroid
        "cluster_centroids_raw": centroids_raw,  # diagnostic/interpretation
        "regime_names": regime_names,            # provisoires -- editer a la main apres Phase A
        "n_baseline_circuits": len(baseline_circuits),
        "k": k_opt,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)

    print(f"\nModele sauvegarde : {OUTPUT_PATH}")
    print(f"  k={k_opt}  n_baseline={len(baseline_circuits)}  pc1_sign_flip={pc1_sign_flip}")
    print(f"  Centroids PC :")
    for i, cp in enumerate(centroids_pc):
        print(f"    regime_{i} : PC1={cp[0]:.4f}  PC2={cp[1]:.4f}")
    print()
    print("  IMPORTANT : renommer les regime_names dans lri_baseline.json apres")
    print("  avoir inspecte les features moyennes (cf. sortie analyze_lri_invariance.py).")


if __name__ == "__main__":
    main()
