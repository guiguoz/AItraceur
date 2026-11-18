"""
Phase A -- Test d'invariance des regimes LRI (Latent Regime Index).

Objectif : valider que les regimes definis sur la baseline sont presents (non degeneres)
dans les cartes OOD. Question cle : est-ce que toutes les cartes OOD tombent dans un
seul cluster, ou les regimes sont-ils representes ?

Usage:
  python backend/scripts/analyze_lri_invariance.py \\
    backend/debug/intent_legs_post_fix_full.csv \\
    backend/debug/intent_legs_cerisy_full.csv \\
    backend/debug/intent_legs_feuguerolles_full.csv \\
    backend/debug/intent_legs_tourouvre_full.csv \\
    backend/debug/intent_legs_montmirel_full.csv

Premier CSV = baseline (stanne+crohot) : PCA + scaler fittes UNIQUEMENT dessus.
KMeans fitte sur 10D scaled baseline (diagnostic offline).
Assignment runtime via nearest centroid dans l'espace PC (jamais 10D).

CRITIQUE -- regle un seul espace :
  10D clustering = diagnostic offline uniquement.
  Runtime = projection PCA baseline + nearest centroid PC1/PC2.
  Ne jamais exposer les centroids 10D en runtime.
"""

from __future__ import annotations

import sys
import csv
import pathlib
from collections import defaultdict

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, adjusted_rand_score


FEATURE_COLS = [
    "parallel_affordance", "crossing_density", "exit_clarity",
    "contour_crossing_guidance",
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
    "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
]

FEATURE_SHORT = [
    "parallel", "crossing", "exit_clar", "relief_guid",
    "HANDRAIL", "LINE_X", "ATTACK", "DIRECT_RISK", "RELIEF_X", "SAFETY",
]

BASELINE_MAPS = {"stanne", "crohot"}
K_RANGE = [2, 3, 4, 5]


# -- Chargement / agregation ---------------------------------------------------

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


# -- Assignment via nearest centroid PC ---------------------------------------

def _assign_pc(pcs: np.ndarray, centroids_pc: np.ndarray) -> np.ndarray:
    """Nearest centroid dans l'espace PC1/PC2 -- regle runtime (jamais 10D)."""
    dists = np.linalg.norm(pcs[:, np.newaxis, :] - centroids_pc[np.newaxis, :, :], axis=2)
    return np.argmin(dists, axis=1)


# -- Affichage -----------------------------------------------------------------

def _bar(v: float, lo: float, hi: float, width: int = 20) -> str:
    if hi <= lo:
        return " " * width
    pos = int((v - lo) / (hi - lo) * width)
    return "." * pos + "#" + "." * (width - pos - 1)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python analyze_lri_invariance.py baseline.csv [new_map.csv ...]")
        sys.exit(1)

    # -- 1. Chargement --------------------------------------------------------
    print("Chargement des CSV :")
    all_circuits: list[dict] = []
    for path in sys.argv[1:]:
        if not pathlib.Path(path).exists():
            print(f"ERREUR: fichier introuvable : {path}")
            sys.exit(1)
        rows = _load_csv(path)
        circuits = _aggregate_circuits(rows)
        all_circuits.extend(circuits)
        maps_in = sorted({c["map_name"] for c in circuits})
        tds_in = sorted({c["td"] for c in circuits})
        print(f"  {pathlib.Path(path).name:<45} {len(circuits):>3} circuits -- "
              f"cartes: {maps_in}, TDs: {tds_in}")

    by_map: dict[str, list[dict]] = defaultdict(list)
    for c in all_circuits:
        by_map[c["map_name"]].append(c)

    map_names = sorted(by_map.keys())
    new_maps = [m for m in map_names if m not in BASELINE_MAPS]

    # -- 2. Baseline PCA -- figee (identique a analyze_external_validation.py) -
    baseline_circuits = [c for c in all_circuits if c["map_name"] in BASELINE_MAPS]
    if not baseline_circuits:
        print("ERREUR: aucun circuit baseline (stanne/crohot) trouve.")
        sys.exit(1)

    X_baseline = _feature_matrix(baseline_circuits)
    mean_ = X_baseline.mean(axis=0)
    std_ = X_baseline.std(axis=0)  # ddof=0 (coherent avec StandardScaler sklearn)
    std_[std_ == 0] = 1.0
    X_bl_scaled = (X_baseline - mean_) / std_

    # SVD = PCA(n_components=2)
    _, S, Vt = np.linalg.svd(X_bl_scaled, full_matrices=False)
    Vt2 = Vt[:2].copy()
    total_var = float((S ** 2).sum())
    pc1_var_pct = S[0] ** 2 / total_var * 100
    pc2_var_pct = S[1] ** 2 / total_var * 100

    # Orientation canonique PC1 -- fixee une seule fois sur baseline
    # TD5 doit avoir PC1 moyen > TD3
    baseline_tds = np.array([c["td"] for c in baseline_circuits])
    X_bl_init = X_bl_scaled @ Vt2.T
    mu_td5_bl = float(X_bl_init[baseline_tds == 5, 0].mean())
    mu_td3_bl = float(X_bl_init[baseline_tds == 3, 0].mean())
    pc1_sign_flip = mu_td5_bl < mu_td3_bl
    if pc1_sign_flip:
        Vt2[0] *= -1

    pc_scores_baseline = X_bl_scaled @ Vt2.T  # (n_bl, 2)

    print(f"\n{'=' * 72}")
    print(f"PCA baseline ({len(baseline_circuits)} circuits stanne+crohot)")
    print(f"  PC1={pc1_var_pct:.1f}%  PC2={pc2_var_pct:.1f}%  "
          f"orientation : {'flippee' if pc1_sign_flip else 'native'} (TD5>TD3 sur baseline)")

    # -- 3. KMeans pour k in K_RANGE -- 10D scaled baseline (diagnostic offline) -
    print(f"\n{'-' * 72}")
    print("Selection k par silhouette (10D scaled baseline, KMeans random_state=0) :")
    silhouettes: dict[int, float] = {}
    for k in K_RANGE:
        km = KMeans(n_clusters=k, random_state=0, n_init=10)
        labels_k = km.fit_predict(X_bl_scaled)
        score = silhouette_score(X_bl_scaled, labels_k)
        silhouettes[k] = score
        bar = _bar(score, 0.0, 0.6)
        print(f"  k={k} : silhouette={score:.4f}  |{bar}|")

    k_opt = max(silhouettes, key=silhouettes.__getitem__)
    sil_opt = silhouettes[k_opt]
    print(f"\n  -> k optimal = {k_opt}  (silhouette={sil_opt:.4f})")

    # -- 4. KMeans final k_opt -- labels 10D + centroids PC --------------------
    km_final = KMeans(n_clusters=k_opt, random_state=0, n_init=10)
    labels_10d = km_final.fit_predict(X_bl_scaled)
    centroids_10d_scaled = km_final.cluster_centers_  # (k, 10) -- scaled

    # Centroids dans l'espace PC (pour runtime nearest centroid)
    centroids_pc = centroids_10d_scaled @ Vt2.T  # (k, 2)

    # Centroids en features brutes (pour interpretation -- Phase B)
    centroids_raw = centroids_10d_scaled * std_ + mean_  # (k, 10) -- unscaled

    # -- 5. ARI diagnostic -- clustering 10D vs clustering 2D ------------------
    print(f"\n{'-' * 72}")
    print("Stabilite clustering 2D vs 10D (ARI) :")
    km_2d = KMeans(n_clusters=k_opt, random_state=0, n_init=10)
    labels_2d = km_2d.fit_predict(pc_scores_baseline)
    ari = float(adjusted_rand_score(labels_10d, labels_2d))

    if ari >= 0.7:
        ari_verdict = "GO -- projection PC suffisante pour runtime centroid"
    elif ari >= 0.5:
        ari_verdict = "CAUTION -- projection PC partiellement fidele (runtime reste PC)"
    else:
        ari_verdict = "WARNING -- projection 2D compresse mal les clusters (runtime reste PC)"

    print(f"  ARI(10D, 2D) = {ari:.4f}  -> {ari_verdict}")
    print("  Note : ARI est un diagnostic de visualisation, pas de validite LRI.")
    print("  Le runtime utilise toujours le nearest centroid PC -- independamment de l'ARI.")

    # -- 6. Assignment baseline + OOD via nearest centroid PC ------------------
    # REGLE : jamais les centroids 10D pour l'assignment -- espace PC uniquement
    bl_assignments = _assign_pc(pc_scores_baseline, centroids_pc)

    ood_data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for mname in new_maps:
        circs = by_map[mname]
        X_ood = _feature_matrix(circs)
        X_ood_scaled = (X_ood - mean_) / std_
        pc_ood = X_ood_scaled @ Vt2.T
        tds_ood = np.array([c["td"] for c in circs])
        assign_ood = _assign_pc(pc_ood, centroids_pc)
        ood_data[mname] = (pc_ood, tds_ood, assign_ood)

    # -- 7. Distribution par (map, TD, cluster) --------------------------------
    print(f"\n{'-' * 72}")
    print(f"Distribution par (carte, TD, cluster)  [k={k_opt}]\n")

    cluster_ids = list(range(k_opt))
    hdr_clusters = "".join(f"  cl_{i}" for i in cluster_ids)
    print(f"  {'carte':<14}{'TD':>4}{hdr_clusters}")
    print("  " + "-" * (18 + 6 * k_opt))

    # Baseline
    baseline_tds_arr = np.array([c["td"] for c in baseline_circuits])
    for mname in sorted(BASELINE_MAPS):
        if mname not in by_map:
            continue
        tds_m = np.array([c["td"] for c in by_map[mname]])
        # Baseline assignments par carte
        bl_mask = np.array([c["map_name"] == mname for c in baseline_circuits])
        assigns_m = bl_assignments[bl_mask]
        tds_assigns = baseline_tds_arr[bl_mask]
        for td_val in sorted({c["td"] for c in by_map[mname]}):
            td_mask = tds_assigns == td_val
            counts = [int((assigns_m[td_mask] == cl).sum()) for cl in cluster_ids]
            counts_str = "".join(f"  {n:>4}" for n in counts)
            print(f"  {mname:<14}{td_val:>4}{counts_str}")

    if new_maps:
        print("  " + "- " * (9 + 3 * k_opt))

    # Nouvelles cartes
    ood_collapsed = True  # sera False si une carte ood a > 1 cluster peuple
    for mname in new_maps:
        _, tds_ood, assign_ood = ood_data[mname]
        for td_val in sorted(set(tds_ood.tolist())):
            td_mask = tds_ood == td_val
            counts = [int((assign_ood[td_mask] == cl).sum()) for cl in cluster_ids]
            if sum(1 for n in counts if n > 0) > 1:
                ood_collapsed = False
            counts_str = "".join(f"  {n:>4}" for n in counts)
            print(f"  {mname:<14}{td_val:>4}{counts_str}")

    # -- 8. Critere OOD -- LRI inter-cartes justifie ? -------------------------
    print(f"\n{'-' * 72}")
    if ood_collapsed and new_maps:
        print("VERDICT OOD : toutes les cartes OOD collapsent dans un seul cluster.")
        print("-> LRI inter-cartes NON justifie. Regimes = artefact baseline.")
    else:
        print("VERDICT OOD : cartes OOD distribuees dans plusieurs clusters.")
        print("-> LRI inter-cartes justifie. Regimes presents hors baseline.")

    # -- 9. Features moyennes par cluster (base pour nommage a posteriori) -----
    print(f"\n{'-' * 72}")
    print("Features moyennes par cluster (baseline 10D, non-scalees)\n")
    print(f"  {'feature':<14}" + "".join(f"  {'cl_' + str(i):<9}" for i in cluster_ids))
    print("  " + "-" * (14 + 12 * k_opt))

    for j, (feat, short) in enumerate(zip(FEATURE_COLS, FEATURE_SHORT)):
        row = f"  {short:<14}"
        for cl in cluster_ids:
            row += f"  {centroids_raw[cl, j]:>9.3f}"
        print(row)

    # -- 10. Resume pour Phase B -----------------------------------------------
    print(f"\n{'-' * 72}")
    print(f"Resume Phase B (build_lri_model.py) :")
    print(f"  k = {k_opt}")
    print(f"  pc1_sign_flip = {pc1_sign_flip}")
    print(f"  n_baseline_circuits = {len(baseline_circuits)}")
    print(f"  feature_cols = {FEATURE_COLS}")
    print(f"\n  Centroids PC :")
    for i, cp in enumerate(centroids_pc):
        print(f"    cluster_{i} : PC1={cp[0]:.4f}  PC2={cp[1]:.4f}")
    print()
    print("  Labels provisoires : regime_0 / regime_1 / ... -- nommer apres analyse features.")
    print("  Ne pas hardcoder les labels semantiques avant inspection des features moyennes.")


if __name__ == "__main__":
    main()
