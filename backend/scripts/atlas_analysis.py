"""atlas_analysis.py — Sprint 1 : Validation Atlas
Répond à Q1 (familles réelles ?) et Q3 (fitness équilibré ?)
Output : output/atlas/atlas_report.txt
Dernière ligne : ATLAS DECISION : A / B / C
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent.parent
CSV_PATH = REPO_ROOT / "output" / "atlas" / "atlas_results.csv"
REPORT_PATH = REPO_ROOT / "output" / "atlas" / "atlas_report.txt"

PROFILE_FIELDS = [
    "map_coverage",
    "route_choice_density",
    "alternation",
    "transition_count",
    "transition_strength",
    "relief_ratio",
    "route_choice_ratio",
    "speed_ratio",
]

Q1_REL_THRESHOLD = 0.10  # écart relatif minimum par champ (entre deux familles)
Q1_FIELD_MIN = 3          # nombre minimum de champs différenciants pour Q1 ✓
Q3_DIFF_THRESHOLD = 0.02  # écart inter-familles (relatif) max pour Q3 ✓


def _max_pairwise_rel_diff(family_vals: dict) -> float:
    """Max pairwise relative difference of family means vs global mean."""
    all_vals = np.concatenate([v for v in family_vals.values() if len(v) > 0])
    global_mean = np.nanmean(all_vals)
    if global_mean == 0:
        return 0.0
    means = {k: np.nanmean(v) for k, v in family_vals.items() if len(v) > 0}
    keys = list(means.keys())
    max_d = 0.0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            d = abs(means[keys[i]] - means[keys[j]]) / abs(global_mean)
            max_d = max(max_d, d)
    return max_d


def analyze_q1(df: pd.DataFrame) -> tuple:
    families = sorted(df["family_id"].unique())
    lines = []
    lines.append("=" * 72)
    lines.append("Q1 — Les familles sont-elles réellement différentes ?")
    lines.append("=" * 72)
    lines.append("")

    col_w = 12 * len(families)
    header = f"{'Champ':<26}" + "".join(f"{'Fam ' + str(f):>13}" for f in families) + f"  {'Rel.Diff':>8}  Diff?"
    lines.append(header)
    lines.append("-" * len(header))

    differentiating = []
    for field in PROFILE_FIELDS:
        family_vals = {f: df[df["family_id"] == f][field].dropna().values for f in families}
        means = {f: np.nanmean(v) if len(v) > 0 else np.nan for f, v in family_vals.items()}
        stds = {f: np.nanstd(v) if len(v) > 0 else np.nan for f, v in family_vals.items()}
        rel_d = _max_pairwise_rel_diff(family_vals)
        is_diff = rel_d >= Q1_REL_THRESHOLD
        if is_diff:
            differentiating.append(field)
        cells = "".join(
            f"{means[f]:>9.2f}±{stds[f]:.2f}" if not np.isnan(means.get(f, np.nan)) else f"{'NaN':>13}"
            for f in families
        )
        flag = "  [Y]" if is_diff else "     "
        lines.append(f"{field:<26}{cells}  {rel_d:>7.1%}  {flag}")

    lines.append("")
    lines.append(f"{'narrative_shape (mode)':<26}" + "".join(
        f"{df[df['family_id'] == f]['narrative_shape'].mode().iat[0]:>13}" for f in families
    ))

    lines.append("")
    lines.append(f"Champs differenciants (>={Q1_REL_THRESHOLD:.0%} relatif) : {len(differentiating)}/{len(PROFILE_FIELDS)}")
    if differentiating:
        lines.append("  -> " + ", ".join(differentiating))
    q1_pass = len(differentiating) >= Q1_FIELD_MIN
    lines.append(f"Q1 : {'[OK] PERSONNALITÉS REELLES' if q1_pass else '[KO] SIGNAL ARTIFICIEL'}"
                 f"  (seuil >= {Q1_FIELD_MIN} champs)")

    return q1_pass, differentiating, "\n".join(lines)


def analyze_q3(df: pd.DataFrame) -> tuple:
    families = sorted(df["family_id"].unique())
    lines = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("Q3 — Le fitness favorise-t-il systématiquement une famille ?")
    lines.append("=" * 72)
    lines.append("")

    global_mean_fitness = df["fitness"].mean()

    header = f"{'bbox_id':<12}" + "".join(f"{'Fam ' + str(f):>11}" for f in families) + f"  {'Δ/mean':>7}"
    lines.append(header)
    lines.append("-" * len(header))

    bbox_diffs = []
    for bbox_id, grp in df.groupby("bbox_id"):
        fam_means = {}
        for f in families:
            sub = grp[grp["family_id"] == f]["fitness"]
            if len(sub) > 0:
                fam_means[f] = sub.mean()
        if len(fam_means) < 2:
            continue
        vals = list(fam_means.values())
        rel_diff = (max(vals) - min(vals)) / global_mean_fitness
        bbox_diffs.append(rel_diff)
        cells = "".join(f"{fam_means.get(f, float('nan')):>11.2f}" for f in families)
        lines.append(f"{bbox_id:<12}{cells}  {rel_diff:>6.1%}")

    mean_rel_diff = float(np.mean(bbox_diffs)) if bbox_diffs else 0.0
    lines.append("")
    lines.append(f"Score fitness global moyen : {global_mean_fitness:.2f}")
    lines.append(f"Ecart inter-familles moyen (relatif) : {mean_rel_diff:.2%}  (seuil < {Q3_DIFF_THRESHOLD:.0%})")
    q3_pass = mean_rel_diff < Q3_DIFF_THRESHOLD
    lines.append(f"Q3 : {'[OK] FITNESS EQUILIBRE' if q3_pass else '[KO] FAMILLE DOMINANTE DETECTEE'}")

    return q3_pass, "\n".join(lines)


_DECISION_LABELS = {
    "A": "Familles distinctes + fitness equilibre  ->  Sprint 2 : zone_sequence + atlas_visual.py",
    "B": "Familles artificielles  ->  Revoir metriques profil. Pas de Sprint 2.",
    "C": "Familles distinctes mais fitness desequilibre  ->  Retravailler poids fitness. Pas de Sprint 2.",
}


def main():
    if not CSV_PATH.exists():
        print(f"CSV introuvable : {CSV_PATH}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(CSV_PATH)
    n_bboxes = df["bbox_id"].nunique()
    n_families = df["family_id"].nunique()
    print(f"Chargé : {len(df)} circuits, {n_bboxes} cartes, {n_families} familles")

    q1_pass, diff_fields, q1_text = analyze_q1(df)
    q3_pass, q3_text = analyze_q3(df)

    if q1_pass and q3_pass:
        decision = "A"
    elif not q1_pass:
        decision = "B"
    else:
        decision = "C"

    summary = [
        "",
        "=" * 72,
        f"ATLAS DECISION : {decision}",
        f"-> {_DECISION_LABELS[decision]}",
        "=" * 72,
    ]

    report = "\n".join([
        "ATLAS ANALYSE — Sprint 1",
        f"CSV : {CSV_PATH}",
        f"Circuits : {len(df)}  |  Cartes : {n_bboxes}  |  Familles : {n_families}",
        "",
        q1_text,
        q3_text,
        *summary,
    ])

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nRapport écrit : {REPORT_PATH}")


if __name__ == "__main__":
    main()
