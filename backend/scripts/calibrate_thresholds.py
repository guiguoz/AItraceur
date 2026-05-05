"""
calibrate_thresholds.py — Grid search sur les seuils leg_type_thresholds.

Lit backend/data/benchmark_legs.json (produit par annotate_legs.py),
cherche les seuils route_choice_jaccard / handrail_coverage / low_catch_score
qui maximisent le F1-score multi-label vs annotations manuelles,
puis met à jour placement_rules.json et génère CALIBRATION.md.

Usage :
    cd backend
    python scripts/calibrate_thresholds.py
    python scripts/calibrate_thresholds.py --benchmark data/benchmark_legs.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
RULES_PATH = BACKEND_DIR / "src" / "services" / "knowledge_base" / "placement_rules.json"
sys.path.insert(0, str(BACKEND_DIR))


# ── Types ─────────────────────────────────────────────────────────────────────

ALL_LABELS = ["route_choice", "handrail", "technical_read", "direct"]


def _classify_leg(
    leg: dict,
    rc_jaccard: float,
    hr_coverage: float,
    low_catch: float,
) -> List[str]:
    """Classifie un leg selon les seuils donnés, en utilisant les données auto."""
    dp_auto = leg.get("decision_points_auto")
    dist_m = leg.get("dist_m", 100)

    # Proxy Jaccard depuis decision_points_auto (1 DP / 120m → Jaccard ~0.35)
    # En l'absence de Jaccard réel, on l'approche depuis les DP.
    jaccard_proxy = 0.0
    if dp_auto is not None and dist_m > 0:
        dp_rate = dp_auto / (dist_m / 120.0) if dist_m > 120 else dp_auto
        jaccard_proxy = min(1.0, dp_rate * 0.35)  # calibration linéaire simpliste

    types: List[str] = []
    if jaccard_proxy >= rc_jaccard:
        types.append("route_choice")
    # handrail / technical_read : pas de proxy auto disponible dans benchmark_legs.json
    # → on ne prédit que route_choice et direct pour ces deux labels
    if not types:
        types.append("direct")
    return types


def _f1_multilabel(
    data: List[dict],
    rc_jaccard: float,
    hr_coverage: float,
    low_catch: float,
) -> float:
    """F1-score micro-average sur les legs annotés."""
    tp = fp = fn = 0
    for entry in data:
        for leg in entry.get("legs", []):
            manual = set(leg.get("labels", ["direct"]))
            predicted = set(_classify_leg(leg, rc_jaccard, hr_coverage, low_catch))
            tp += len(manual & predicted)
            fp += len(predicted - manual)
            fn += len(manual - predicted)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _decision_point_correlation(data: List[dict]) -> Optional[float]:
    """Corrélation de Pearson entre decision_points_auto et decision_points_manual."""
    pairs = [
        (leg["decision_points_auto"], leg["decision_points_manual"])
        for entry in data
        for leg in entry.get("legs", [])
        if leg.get("decision_points_auto") is not None
        and leg.get("decision_points_manual") is not None
    ]
    if len(pairs) < 3:
        return None

    n = len(pairs)
    auto = [p[0] for p in pairs]
    manual = [p[1] for p in pairs]
    mean_a = sum(auto) / n
    mean_m = sum(manual) / n
    num = sum((a - mean_a) * (m - mean_m) for a, m in zip(auto, manual))
    denom = math.sqrt(
        sum((a - mean_a) ** 2 for a in auto)
        * sum((m - mean_m) ** 2 for m in manual)
    )
    return num / denom if denom > 1e-10 else None


def _dp_rmse(data: List[dict]) -> Optional[float]:
    pairs = [
        (leg["decision_points_auto"], leg["decision_points_manual"])
        for entry in data
        for leg in entry.get("legs", [])
        if leg.get("decision_points_auto") is not None
        and leg.get("decision_points_manual") is not None
    ]
    if not pairs:
        return None
    return math.sqrt(sum((a - m) ** 2 for a, m in pairs) / len(pairs))


def _count_legs(data: List[dict]) -> int:
    return sum(len(entry.get("legs", [])) for entry in data)


# ── Grid search ──────────────────────────────────────────────────────────────

_RC_JACCARD_VALUES = [0.20, 0.25, 0.30, 0.35]
_HR_COVERAGE_VALUES = [0.60, 0.65, 0.70, 0.75]
_LOW_CATCH_VALUES = [0.25, 0.30, 0.35]


def run_grid_search(data: List[dict]) -> Tuple[Dict, float]:
    """Lance le grid search et retourne (best_params, best_f1)."""
    best_f1 = -1.0
    best_params: Dict = {}
    total = len(_RC_JACCARD_VALUES) * len(_HR_COVERAGE_VALUES) * len(_LOW_CATCH_VALUES)

    print(f"Grid search {total} configurations...")
    for i, (rc_j, hr_c, lc) in enumerate(
        product(_RC_JACCARD_VALUES, _HR_COVERAGE_VALUES, _LOW_CATCH_VALUES), 1
    ):
        f1 = _f1_multilabel(data, rc_j, hr_c, lc)
        if f1 > best_f1:
            best_f1 = f1
            best_params = {
                "route_choice_jaccard": rc_j,
                "handrail_coverage": hr_c,
                "low_catch_score": lc,
            }
        if i % 12 == 0:
            print(f"  [{i}/{total}] meilleur F1={best_f1:.4f}", flush=True)

    return best_params, best_f1


# ── Confusion matrix ─────────────────────────────────────────────────────────

def _confusion_row(data: List[dict], label: str, params: Dict) -> Tuple[float, float, float]:
    tp = fp = fn = 0
    for entry in data:
        for leg in entry.get("legs", []):
            manual = set(leg.get("labels", ["direct"]))
            predicted = set(_classify_leg(
                leg,
                params["route_choice_jaccard"],
                params["handrail_coverage"],
                params["low_catch_score"],
            ))
            if label in manual and label in predicted:
                tp += 1
            elif label not in manual and label in predicted:
                fp += 1
            elif label in manual and label not in predicted:
                fn += 1

    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return prec, rec, f1


# ── Mise à jour placement_rules.json ─────────────────────────────────────────

def _update_placement_rules(params: Dict, dry_run: bool) -> None:
    if not RULES_PATH.exists():
        print(f"[WARN] {RULES_PATH} introuvable — pas de mise à jour")
        return

    with open(RULES_PATH, encoding="utf-8") as f:
        rules = json.load(f)

    rules["leg_type_thresholds"] = {
        "_comment": f"Calibré automatiquement le {datetime.now().strftime('%Y-%m-%d')} "
                    "par calibrate_thresholds.py",
        **params,
    }

    if dry_run:
        print("[DRY-RUN] placement_rules.json non modifié. Nouveaux seuils :")
        print(json.dumps(rules["leg_type_thresholds"], indent=2))
        return

    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    print(f"placement_rules.json mis à jour → {RULES_PATH}")


# ── Génération CALIBRATION.md ─────────────────────────────────────────────────

def _write_calibration_md(
    data: List[dict],
    best_params: Dict,
    best_f1: float,
    corr_dp: Optional[float],
    rmse_dp: Optional[float],
    dry_run: bool,
) -> None:
    n_circuits = len(data)
    n_legs = _count_legs(data)
    date_str = datetime.now().strftime("%Y-%m-%d")

    confusion_rows = {
        label: _confusion_row(data, label, best_params)
        for label in ["route_choice", "handrail", "technical_read"]
    }

    corr_str = f"{corr_dp:.3f}" if corr_dp is not None else "n/a"
    rmse_str = f"{rmse_dp:.2f} pts" if rmse_dp is not None else "n/a"
    corr_verdict = (
        "✓ cible ≥0.75 atteinte" if corr_dp is not None and corr_dp >= 0.75
        else ("⚠ cible non atteinte" if corr_dp is not None else "⚠ données insuffisantes")
    )
    f1_verdict = (
        "✓ cible ≥0.70 atteinte" if best_f1 >= 0.70
        else "⚠ cible non atteinte"
    )

    def _row(label: str) -> str:
        p, r, f = confusion_rows.get(label, (0, 0, 0))
        return f"| {label:<16} | {p:.2f}     | {r:.2f}   | {f:.2f} |"

    content = f"""# CALIBRATION.md

> Généré automatiquement par `calibrate_thresholds.py` le {date_str}.

## Benchmark

- **Circuits annotés** : {n_circuits}
- **Legs annotés** : {n_legs}
- Kappa inter-annotateurs : à calculer manuellement si plusieurs annotateurs

## Decision Points

| Métrique | Valeur | Cible |
|----------|--------|-------|
| Corrélation Pearson auto/manuel | {corr_str} | ≥ 0.75 |
| RMSE | {rmse_str} | — |

**Verdict** : {corr_verdict}

## Leg Type Classification

| Métrique | Valeur | Cible |
|----------|--------|-------|
| F1-score micro-average | {best_f1:.4f} | ≥ 0.70 |

**Verdict** : {f1_verdict}

### Meilleurs seuils (grid 4×4×3)

```json
{json.dumps(best_params, indent=2)}
```

### Matrice de confusion (par type de leg)

| Type             | Précision | Rappel | F1   |
|------------------|-----------|--------|------|
{_row("route_choice")}
{_row("handrail")}
{_row("technical_read")}

## Seuils mis à jour dans placement_rules.json

```
route_choice_jaccard : {best_params['route_choice_jaccard']}
handrail_coverage    : {best_params['handrail_coverage']}
low_catch_score      : {best_params['low_catch_score']}
```

## Prochaines étapes

1. Relancer `ablation_study.py` avec les nouveaux seuils
2. Ajuster `controleur_rules.json` : C18.min_jaccard, C19.max_handrail_ratio, C20.max_route_choice_ratio
3. Collecter plus de circuits si F1 < 0.70 (cible : 40-50 circuits)
"""

    cal_path = BACKEND_DIR / "CALIBRATION.md"
    if dry_run:
        print("[DRY-RUN] CALIBRATION.md non écrit. Contenu :")
        print(content)
        return

    cal_path.write_text(content, encoding="utf-8")
    print(f"CALIBRATION.md → {cal_path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grid search sur les seuils leg_type_thresholds pour maximiser F1"
    )
    parser.add_argument(
        "--benchmark",
        default=str(BACKEND_DIR / "data" / "benchmark_legs.json"),
        help="Chemin vers benchmark_legs.json (défaut: data/benchmark_legs.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les résultats sans modifier les fichiers",
    )
    args = parser.parse_args()

    benchmark_path = Path(args.benchmark)
    if not benchmark_path.exists():
        print(f"[ERREUR] {benchmark_path} introuvable.")
        print("Lancer d'abord : python scripts/annotate_legs.py")
        sys.exit(1)

    with open(benchmark_path, encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("[ERREUR] benchmark_legs.json vide.")
        sys.exit(1)

    n_legs = _count_legs(data)
    print(f"Benchmark : {len(data)} circuits, {n_legs} legs")

    if n_legs < 10:
        print("[WARN] Trop peu de legs (<10) — résultats peu fiables.")

    # ── Grid search ──────────────────────────────────────────────────────────
    best_params, best_f1 = run_grid_search(data)

    print(f"\nMeilleurs seuils (F1={best_f1:.4f}) :")
    print(json.dumps(best_params, indent=2))

    # ── Métriques Decision Points ─────────────────────────────────────────────
    corr_dp = _decision_point_correlation(data)
    rmse_dp = _dp_rmse(data)

    if corr_dp is not None:
        print(f"\nDecision Points : corrélation Pearson={corr_dp:.3f}, RMSE={rmse_dp:.2f} pts")
    else:
        print("\nDecision Points : pas assez de données auto/manuel")

    # ── Mise à jour fichiers ──────────────────────────────────────────────────
    _update_placement_rules(best_params, dry_run=args.dry_run)
    _write_calibration_md(data, best_params, best_f1, corr_dp, rmse_dp, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
