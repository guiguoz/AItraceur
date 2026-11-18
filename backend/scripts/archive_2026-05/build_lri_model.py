"""
Phase B -- Build du modele LRI fige (Latent Regime Index).

Produit backend/data/lri_baseline.json a partir de la baseline stanne+crohot.

Usage:
  python backend/scripts/build_lri_model.py [baseline_csv]
  # Default: backend/debug/intent_legs_post_fix_full.csv

Contraintes architecturales :
- PCA + scaler fites sur baseline uniquement
- pca_components deja flippe (pc1_sign_flip applique une seule fois ici)
- cluster_centroids_pc = centroids tries par PC1 desc, projetes dans PC space (runtime)
- cluster_centroids_raw = centroids en features brutes (diagnostic/interpretation)
- Noms semantiques figes : high PC1 = "open", low PC1 = "handrail" (pour k=2)
- k selectionne par silhouette sur 10D scaled baseline
- semantic_anchor valide au chargement dans lri_model.py
"""

from __future__ import annotations

import sys
import csv
import json
import pathlib
from collections import defaultdict

import numpy as np
import sklearn
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

# Noms semantiques pour k=2 : high PC1 = "open" (azimut, peu de guidance),
#                              low PC1  = "handrail" (longeant, guidance forte)
_SEMANTIC_NAMES_K2 = ["open", "handrail"]


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
    pc1_var = float(S[0] ** 2 / total_var)
    pc2_var = float(S[1] ** 2 / total_var)

    # Orientation canonique PC1 -- appliquee ici, stockee dans pca_components
    baseline_tds = np.array([c["td"] for c in baseline_circuits])
    X_bl_init = X_bl_scaled @ Vt2.T
    mu_td5_bl = float(X_bl_init[baseline_tds == 5, 0].mean())
    mu_td3_bl = float(X_bl_init[baseline_tds == 3, 0].mean())
    pc1_sign_flip = bool(mu_td5_bl < mu_td3_bl)
    if pc1_sign_flip:
        Vt2[0] *= -1  # flip stocke dans Vt2 -- lri_model.py n'a pas a flipper

    print(f"PCA : PC1={pc1_var*100:.1f}%  PC2={pc2_var*100:.1f}%  pc1_sign_flip={pc1_sign_flip}")

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
    centroids_10d = km_final.cluster_centers_  # (k, 10) scaled

    # Tri deterministe par PC1 desc — independant de l'ordre KMeans
    centroids_pc_arr = centroids_10d @ Vt2.T  # (k, 2)
    pc1_order = np.argsort(centroids_pc_arr[:, 0])[::-1]
    centroids_10d = centroids_10d[pc1_order]
    centroids_pc_arr = centroids_pc_arr[pc1_order]

    centroids_pc = centroids_pc_arr.tolist()
    centroids_raw = (centroids_10d * std_ + mean_).tolist()

    # Noms semantiques figes : high PC1 = "open", low PC1 = "handrail"
    regime_names = {
        str(i): (_SEMANTIC_NAMES_K2[i] if k_opt == 2 and i < 2 else f"regime_{i}")
        for i in range(k_opt)
    }

    # Ancre geometrique — valide au chargement dans lri_model.load()
    semantic_anchor = {
        regime_names[str(i)] + "_pc1_mean": round(float(centroids_pc_arr[i, 0]), 3)
        for i in range(k_opt)
    }

    # -- Construire JSON -------------------------------------------------------
    model_sig = f"lri_v1_k{k_opt}_pc{int(round(pc1_var, 3) * 1000)}"

    model = {
        "feature_cols": FEATURE_COLS,
        "pca_mean": mean_.tolist(),
        "pca_std": std_.tolist(),
        "pca_components": Vt2.tolist(),          # (2, 10) -- deja flippe
        "pc1_sign_flip": pc1_sign_flip,           # trace audit -- jamais relu en runtime
        "cluster_centroids_pc": centroids_pc,     # runtime nearest centroid (espace PC)
        "cluster_centroids_raw": centroids_raw,   # diagnostic/interpretation
        "regime_names": regime_names,
        "n_baseline_circuits": len(baseline_circuits),
        "k": k_opt,
        "cluster_semantics_version": 1,
        "pc1_positive_semantics": "open_attack",  # high PC1 = azimut / peu de guidance lineaire
        "baseline_maps": sorted(BASELINE_MAPS),
        "pca_variance_ratio": [round(pc1_var, 4), round(pc2_var, 4)],
        "kmeans_random_state": 0,
        "sklearn_version": sklearn.__version__,
        "semantic_anchor": semantic_anchor,       # garde-fou geometrique valide au load()
        "model_signature": model_sig,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)

    print(f"\nModele sauvegarde : {OUTPUT_PATH}")
    print(f"  model_signature = {model_sig}")
    print(f"  k={k_opt}  n_baseline={len(baseline_circuits)}  sklearn={sklearn.__version__}")
    print(f"  Regimes (tries par PC1 desc) :")
    for i, cp in enumerate(centroids_pc):
        print(f"    {regime_names[str(i)]} : PC1={cp[0]:.4f}  PC2={cp[1]:.4f}")
    print(f"  semantic_anchor : {semantic_anchor}")


if __name__ == "__main__":
    main()
