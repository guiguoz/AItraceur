#!/usr/bin/env python3
"""
analyze_label_correlation.py — STEP C
Mesure ρ(PC1, label_humain) sur les cartes annotées.

Usage :
  python backend/scripts/analyze_label_correlation.py
  python backend/scripts/analyze_label_correlation.py --maps airelles llose
"""

from __future__ import annotations

import argparse
import csv
import math
import pathlib
import re
import random
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.model_selection import (RepeatedKFold, RepeatedStratifiedKFold,
                                     cross_val_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

_SCRIPT = pathlib.Path(__file__).parent
_ROOT   = _SCRIPT.parent.parent
OUTPUT  = _ROOT / "output"

LABEL_SCORE = {"suivi": -1.0, "attaque": +1.0}   # uncertain → NaN, exclu

_SPRINT_RE = re.compile(r"^([012])_([012])$")

N_PERMUTATIONS = 2000


def _to_float_or_none(v: object) -> float | None:
    try:
        return float(v) if v not in (None, "", "nan") else None  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def _parse_sprint_label(label: str) -> tuple[int, int] | None:
    m = _SPRINT_RE.match(label)
    return (int(m.group(1)), int(m.group(2))) if m else None


# ── Chargement ────────────────────────────────────────────────────────────────

def load_map_data(map_name: str) -> list[dict]:
    """Retourne les jambes matchées avec leur dernière annotation."""
    legs_path = OUTPUT / f"intent_legs_{map_name}.csv"
    ann_path  = OUTPUT / f"annotations_{map_name}.csv"

    if not legs_path.exists():
        print(f"  [WARN] intent_legs_{map_name}.csv absent — carte ignorée")
        return []
    if not ann_path.exists():
        print(f"  [WARN] annotations_{map_name}.csv absent — carte ignorée")
        return []

    legs = {(r["circuit_id"], r["leg_index"]): r
            for r in csv.DictReader(legs_path.open(encoding="utf-8"))}

    last_ann: dict[tuple, str] = {}
    for r in csv.DictReader(ann_path.open(encoding="utf-8")):
        last_ann[(r["circuit_id"], r["leg_index"])] = r["label"]

    rows = []
    for key, label in last_ann.items():
        if key not in legs:
            continue
        leg = legs[key]
        sprint = _parse_sprint_label(label)
        score  = LABEL_SCORE.get(label) if sprint is None else None
        rows.append({
            "map":               map_name,
            "circuit_id":        key[0],
            "leg_index":         int(key[1]),
            "label":             label,
            "score":             score,
            "route_count":       sprint[0] if sprint else None,
            "route_impact":      sprint[1] if sprint else None,
            "pc1":               float(leg["pc1"]),
            "pc2":               float(leg["pc2"]),
            "decision_pressure": float(leg["decision_pressure"]),
            "ATTACK_POINT":      float(leg["ATTACK_POINT"]),
            "SAFETY_RECOVERY":   float(leg["SAFETY_RECOVERY"]),
            "HANDRAIL_FOLLOW":   float(leg["HANDRAIL_FOLLOW"]),
            "leg_m":             float(leg["leg_m"]),
            "condition":         leg["condition"],
            # Features OSM (présentes après enrich_sprint_legs.py)
            "route_diversity":   _to_float_or_none(leg.get("route_diversity")),
            "path_length_ratio": _to_float_or_none(leg.get("path_length_ratio")),
            "decision_points":   _to_float_or_none(leg.get("decision_points")),
            "valid_graph_ratio": _to_float_or_none(leg.get("valid_graph_ratio")),
        })
    return rows


# ── Métriques ─────────────────────────────────────────────────────────────────

def entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((n / total) * math.log2(n / total) for n in counts.values() if n > 0)


def spearman_ci(x: np.ndarray, y: np.ndarray, n_boot: int = 2000) -> tuple[float, float, float]:
    rho, p = spearmanr(x, y)
    rhos = []
    rng = np.random.default_rng(42)
    for _ in range(n_boot):
        idx = rng.integers(0, len(x), len(x))
        r, _ = spearmanr(x[idx], y[idx])
        rhos.append(r)
    rhos_arr = np.array(rhos)
    return rho, float(np.percentile(rhos_arr, 2.5)), float(np.percentile(rhos_arr, 97.5))


def permutation_pval(x: np.ndarray, y: np.ndarray, n: int = N_PERMUTATIONS) -> float:
    """P-value bilatérale par permutation (fraction de |ρ_shuffle| ≥ |ρ_obs|)."""
    rho_obs, _ = spearmanr(x, y)
    rng = np.random.default_rng(42)
    extreme = sum(
        1 for _ in range(n)
        if abs(spearmanr(x, rng.permutation(y))[0]) >= abs(rho_obs)
    )
    return extreme / n


def random_baseline(x: np.ndarray, y: np.ndarray, n: int = N_PERMUTATIONS) -> tuple[float, float]:
    rng = np.random.default_rng(0)
    rhos = []
    for _ in range(n):
        y_shuf = rng.permutation(y)
        r, _ = spearmanr(x, y_shuf)
        rhos.append(r)
    return float(np.mean(rhos)), float(np.std(rhos))


def analyze_sprint(rows: list[dict], label: str = "") -> None:
    total = len(rows)
    cnt   = Counter(r["label"] for r in rows)

    valid   = [r for r in rows if r["route_count"] is not None]
    n_valid = len(valid)

    print(f"\n{'─'*60}")
    print(f"  {label}  ({total} jambes annotées)")
    print(f"{'─'*60}")
    print(f"  Labels : {dict(sorted(cnt.items()))}")
    print(f"  Mode : sprint ordinal (route_count × route_impact)")
    print(f"  Jambes valides : {n_valid}")

    if n_valid < 5:
        print(f"  ⚠ Trop peu de jambes valides pour l'analyse")
        return

    pc1    = np.array([r["pc1"]               for r in valid])
    dp     = np.array([r["decision_pressure"]  for r in valid])
    count  = np.array([float(r["route_count"])  for r in valid])
    impact = np.array([float(r["route_impact"]) for r in valid])
    csum   = count + impact

    print(f"\n  Distribution count  : {dict(sorted(Counter(int(x) for x in count).items()))}")
    print(f"  Distribution impact : {dict(sorted(Counter(int(x) for x in impact).items()))}")

    # Spearman ρ pour chaque cible (+ bootstrap IC95)
    print(f"\n  Corrélations Spearman  (bootstrap IC95, n={n_valid})")
    hdr = f"  {'Cible':22s}  {'ρ(PC1)':>7}  {'p':>7}  {'IC95':>16}  {'ρ(dp)':>7}  {'p':>7}"
    print(hdr)
    for name, y in [("route_count", count), ("route_impact", impact), ("count+impact", csum)]:
        rho_pc1, ci_lo, ci_hi = spearman_ci(pc1, y)
        _, p_pc1               = spearmanr(pc1, y)
        rho_dp, p_dp           = spearmanr(dp, y)
        sig = " *" if p_pc1 < 0.05 else (" ~" if p_pc1 < 0.10 else "  ")
        print(f"  {name:22s}  {rho_pc1:+.3f}   {p_pc1:.4f}  [{ci_lo:+.3f},{ci_hi:+.3f}]"
              f"  {rho_dp:+.3f}   {p_dp:.4f}{sig}")

    # Interprétation
    rho_c, p_c = spearmanr(pc1, count)
    rho_i, p_i = spearmanr(pc1, impact)
    rho_s, p_s = spearmanr(pc1, csum)
    any_sig = any(p < 0.05 for p in (p_c, p_i, p_s))
    print()
    if any_sig and abs(rho_s) >= 0.4:
        print("  Signal sprint détecté — PC1 corrèle avec count+impact (p<0.05)")
    elif any_sig:
        print("  Signal partiel significatif — voir détail par dimension ci-dessus")
    else:
        print("  Aucun ρ significatif (p≥0.05) sur les trois cibles")
        print("  → PC1 ne capture pas les dimensions annotées (nb routes / impact)")
        print("    (≠ 'PC1 inutile en sprint' — peut mesurer lisibilité, charge décisionnelle…)")

    if n_valid < 15:
        return

    # Régression linéaire : prédire count+impact depuis {PC1, dp, PC1+dp}
    print(f"\n  Régression (cible : count+impact)  [RepeatedKFold 5×20, R²]")
    cv_r = RepeatedKFold(n_splits=5, n_repeats=20, random_state=42)
    feat_sets: dict[str, np.ndarray] = {
        "PC1":      pc1.reshape(-1, 1),
        "dp":       dp.reshape(-1, 1),
        "PC1 + dp": np.column_stack([pc1, dp]),
    }
    r2_results: dict[str, float] = {}
    for name, X in feat_sets.items():
        pipe = make_pipeline(StandardScaler(), LinearRegression())
        r2   = cross_val_score(pipe, X, csum, cv=cv_r, scoring="r2")
        r2_results[name] = float(r2.mean())
        print(f"  {name:15s}  R²={r2.mean():+.3f}±{r2.std():.3f}")

    gain = r2_results.get("PC1 + dp", 0.0) - r2_results.get("dp", 0.0)
    print(f"\n  → Gain R²(PC1+dp) vs R²(dp) = {gain:+.3f}")
    if gain >= 0.03:
        print("    PC1 apporte une information complémentaire sur le choix d'itinéraire")
    else:
        print("    PC1 n'apporte pas d'info au-delà de dp sur ce concept sprint")

    # ── Features réseau OSM (si enrich_sprint_legs.py a été exécuté) ─────────
    osm_valid = [r for r in valid if r.get("route_diversity") is not None]
    if not osm_valid:
        return

    n_osm = len(osm_valid)
    vgr   = osm_valid[0].get("valid_graph_ratio")

    print(f"\n{'─'*62}")
    print(f"  Features réseau OSM  (n={n_osm} jambes avec chemin trouvé)")
    print(f"{'─'*62}")
    if vgr is not None:
        warn = "  ⚠ graphe OSM fragmenté — biais potentiel" if vgr < 0.7 else ""
        print(f"  valid_graph_ratio = {vgr:.3f}{warn}")

    rd_arr  = np.array([r["route_diversity"]   for r in osm_valid], dtype=float)
    plr_arr = np.array([r["path_length_ratio"] for r in osm_valid], dtype=float)
    dp_arr  = np.array([r["decision_points"]   for r in osm_valid], dtype=float)
    count_o = np.array([float(r["route_count"])  for r in osm_valid])
    impact_o = np.array([float(r["route_impact"]) for r in osm_valid])
    csum_o   = count_o + impact_o

    print(f"\n  Corrélations Spearman + p-valeur permutation (n={n_osm})")
    print(f"  (p_perm = fraction de |ρ_shuffle| ≥ |ρ_obs| sur {N_PERMUTATIONS} tirages)")
    hdr = f"  {'Feature':28s}  {'Cible':14s}  {'ρ':>7}  {'p':>7}  {'p_perm':>7}"
    print(hdr)
    print(f"  {'-'*66}")

    for feat_name, feat_arr, is_secondary in [
        ("route_diversity",           rd_arr,  False),
        ("path_length_ratio",         plr_arr, False),
        ("decision_points  [explor]", dp_arr,  True),
    ]:
        for lbl_name, lbl_arr in [
            ("route_count",  count_o),
            ("route_impact", impact_o),
            ("count+impact", csum_o),
        ]:
            if n_osm < 5:
                continue
            rho, p = spearmanr(feat_arr, lbl_arr)
            p_perm = permutation_pval(feat_arr, lbl_arr)
            sig = " *" if p < 0.05 else (" ~" if p < 0.10 else "  ")
            sec = "  (exploratoire)" if is_secondary and lbl_name == "route_count" else ""
            print(f"  {feat_name:28s}  {lbl_name:14s}  {rho:+.3f}   {p:.4f}   {p_perm:.3f}{sig}{sec}")
        print()

    # ── Interprétation H1/H2/H3 ───────────────────────────────────────────────
    rho_rd_count, p_rd_count = spearmanr(rd_arr, count_o)
    rho_plr_imp,  p_plr_imp  = spearmanr(plr_arr, impact_o)
    strong_h1 = abs(rho_rd_count) > 0.4 and p_rd_count < 0.05 \
                and abs(rho_plr_imp) > 0.4 and p_plr_imp < 0.05
    any_sig_osm = p_rd_count < 0.05 or p_plr_imp < 0.05

    print(f"  {'─'*58}")
    if strong_h1:
        print("  H1 — Signal fort : annotation partiellement alignée avec la structure OSM")
        print("       route_diversity ↔ route_count et path_length_ratio ↔ route_impact")
        print("       Features exploitables pour scoring sprint.")
    elif any_sig_osm:
        print("  H1/H2 — Signal partiel : alignement partiel avec la structure de graphe")
        print("           Le concept sprint est probablement hybride (structurel + perceptif).")
    else:
        print("  H2 — Aucun signal OSM : annotation humaine capture un concept perceptif")
        print("       (lisibilité, angle, trou de carte) que le graphe ne modélise pas.")
        print("       Résultat cohérent avec ρ≈0 observé sur PC1/dp.")
    print()


def analyze(rows: list[dict], label: str = "") -> None:
    # Branchement sprint vs forêt
    sprint_rows = [r for r in rows if r.get("route_count") is not None]
    forest_rows = [r for r in rows if r.get("score")       is not None]
    if sprint_rows and not forest_rows:
        analyze_sprint(rows, label)
        return

    total = len(rows)
    cnt = Counter(r["label"] for r in rows)
    H = entropy(cnt)

    valid = [r for r in rows if r["score"] is not None]
    n_valid = len(valid)

    print(f"\n{'─'*60}")
    print(f"  {label}  ({total} jambes annotées)")
    print(f"{'─'*60}")
    print(f"  Labels : {dict(cnt)}")
    print(f"  Entropie H = {H:.3f} bits  (max={math.log2(len(LABEL_SCORE)):.3f})")
    if H < 0.8:
        print(f"  ⚠ H < 0.8 — dataset déséquilibré, corrélation peu interprétable")
    print(f"  Jambes valides (excl. uncertain) : {n_valid}")

    if n_valid < 10:
        print(f"  ⚠ Trop peu de jambes valides pour l'analyse")
        return

    pc1    = np.array([r["pc1"]               for r in valid])
    dp     = np.array([r["decision_pressure"]  for r in valid])
    scores = np.array([r["score"]              for r in valid])

    # Spearman ρ(PC1, label)
    rho_pc1, ci_lo, ci_hi = spearman_ci(pc1, scores)
    _, p_pc1 = spearmanr(pc1, scores)
    rho_rand, std_rand = random_baseline(pc1, scores)

    # Spearman ρ(decision_pressure, label)
    rho_dp, p_dp = spearmanr(dp, scores)

    # Separation power
    pc1_att = pc1[scores > 0]
    pc1_sui = pc1[scores < 0]
    sep = float(np.mean(pc1_att) - np.mean(pc1_sui)) if len(pc1_att) > 0 and len(pc1_sui) > 0 else 0.0

    print(f"\n  ρ(PC1, label)      = {rho_pc1:+.3f}  p={p_pc1:.4f}  "
          f"IC95=[{ci_lo:+.3f}, {ci_hi:+.3f}]")
    print(f"  Baseline aléatoire = {rho_rand:+.4f} ± {std_rand:.4f}")
    print(f"  Signal vs baseline = {abs(rho_pc1) - abs(rho_rand):.3f}  "
          f"({abs(rho_pc1)/max(std_rand,1e-9):.1f} σ)")
    print(f"\n  ρ(decision_pressure, label) = {rho_dp:+.3f}  p={p_dp:.4f}")
    print(f"\n  Separation power = {sep:+.3f}  "
          f"[mean PC1(attaque)={np.mean(pc1_att):.3f}  "
          f"mean PC1(suivi)={np.mean(pc1_sui):.3f}]")

    # Interprétation
    print()
    if abs(rho_pc1) > 0.5 and p_pc1 < 0.05:
        print("  CONCLUSION : ρ fort — PC1 capte la qualité traceur → LRI v2 justifié")
    elif abs(rho_pc1) > 0.3 and p_pc1 < 0.05:
        print("  CONCLUSION : ρ modéré — signal présent, LRI v2 à affiner")
    elif p_pc1 >= 0.05:
        print("  CONCLUSION : ρ non significatif — PC1 ≠ jugement expert sur ces données")
    else:
        print("  CONCLUSION : ρ faible — PC1 = artefact géométrique probable")

    # ── Régression multivariée ─────────────────────────────────────────────────
    if n_valid < 15:
        return

    attack = np.array([r["ATTACK_POINT"]    for r in valid])
    safety = np.array([r["SAFETY_RECOVERY"] for r in valid])
    y_bin  = (scores > 0).astype(int)

    majority_acc = float(max(y_bin.mean(), 1 - y_bin.mean()))

    print(f"\n{'─'*60}")
    print(f"  Régression multivariée  (RepeatedStratifiedKFold 5×20)")
    print(f"{'─'*60}")
    print(f"  n={n_valid}  majority_acc={majority_acc:.3f}  chance_bal_acc=0.500")
    print()

    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=20, random_state=42)
    feature_sets: dict[str, np.ndarray] = {
        "PC1":           pc1.reshape(-1, 1),
        "decision_p":    dp.reshape(-1, 1),
        "ATTACK_POINT":  attack.reshape(-1, 1),
        "SAFETY_RECOV":  safety.reshape(-1, 1),
        "PC1 + dp":      np.column_stack([pc1, dp]),
    }
    auc_results: dict[str, float] = {}
    for name, X in feature_sets.items():
        pipe   = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500))
        s_auc  = cross_val_score(pipe, X, y_bin, cv=cv, scoring="roc_auc")
        s_bal  = cross_val_score(pipe, X, y_bin, cv=cv, scoring="balanced_accuracy")
        auc_results[name] = float(s_auc.mean())
        print(f"  {name:20s}  AUC={s_auc.mean():.3f}±{s_auc.std():.3f}  "
              f"bal_acc={s_bal.mean():.3f}±{s_bal.std():.3f}")

    # Test central : gain AUC(PC1+dp) vs AUC(dp)
    gain = auc_results.get("PC1 + dp", 0.0) - auc_results.get("decision_p", 0.0)
    print(f"\n  → Gain AUC(PC1+dp) vs AUC(dp) = {gain:+.3f}")
    if gain >= 0.05:
        print("    PC1 apporte une information complémentaire — LRI v2 justifié")
    elif gain >= 0.03:
        print("    Gain marginal — interpréter avec prudence (n faible)")
    else:
        print("    PC1 n'apporte pas d'info au-delà de decision_pressure")

    # Intercorrélations PC1 vs features composantes
    print()
    for name, feat in [("decision_p",   dp),
                       ("ATTACK_POINT", attack),
                       ("SAFETY_RECOV", safety)]:
        if np.std(feat) == 0:
            print(f"  corr(PC1, {name:13s}) = n/a  (feature constante)")
            continue
        rho_ic, p_ic = spearmanr(pc1, feat)
        flag = "  ← variance partagée" if abs(rho_ic) > 0.85 else ""
        print(f"  corr(PC1, {name:13s}) = {rho_ic:+.3f}  p={p_ic:.4f}{flag}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maps", nargs="*",
                        default=["airelles", "llose"],
                        help="Cartes à analyser")
    args = parser.parse_args()

    all_rows: list[dict] = []
    for map_name in args.maps:
        rows = load_map_data(map_name)
        if rows:
            analyze(rows, label=f"Carte : {map_name}")
            all_rows.extend(rows)

    if len(args.maps) > 1 and all_rows:
        analyze(all_rows, label="COMBINÉ — toutes cartes")

        # Validation croisée
        print(f"\n{'─'*60}")
        print("  Validation croisée")
        print(f"{'─'*60}")
        for test_map in args.maps:
            train = [r for r in all_rows if r["map"] != test_map and r["score"] is not None]
            test  = [r for r in all_rows if r["map"] == test_map  and r["score"] is not None]
            if len(train) < 5 or len(test) < 5:
                continue
            rho_train, _ = spearmanr(
                [r["pc1"] for r in train], [r["score"] for r in train]
            )
            rho_test, p_test = spearmanr(
                [r["pc1"] for r in test],  [r["score"] for r in test]
            )
            print(f"  Train={[r['map'] for r in train if r['map']!=test_map][0]!r}  "
                  f"ρ_train={rho_train:+.3f}  →  "
                  f"Test={test_map!r}  ρ_test={rho_test:+.3f}  p={p_test:.4f}")

    print()


if __name__ == "__main__":
    main()
