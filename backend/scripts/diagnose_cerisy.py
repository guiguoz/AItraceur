#!/usr/bin/env python3
"""
diagnose_cerisy.py — Diagnostic anomalie Cerisy (ρ PC1 inversé)

Test n°1 : séparation PC1 suivi/attaque par carte + features ISOM structurelles
Test n°2 : comparaison jambes "attaque" Cerisy vs Grochot (Mann-Whitney U)

Usage :
  python backend/scripts/diagnose_cerisy.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from scipy.stats import mannwhitneyu

_SCRIPT = pathlib.Path(__file__).parent
_ROOT   = _SCRIPT.parent.parent
OUTPUT  = _ROOT / "output"

FOREST_MAPS = ["airelles", "llose", "montmirel", "cerisy", "grochot", "steanne"]
FEATURES    = ["ATTACK_POINT", "HANDRAIL_FOLLOW", "RELIEF_CROSSING_GUIDANCE", "leg_m"]


def _load(map_name: str) -> list[dict]:
    legs_path = OUTPUT / f"intent_legs_{map_name}.csv"
    ann_path  = OUTPUT / f"annotations_{map_name}.csv"
    if not legs_path.exists() or not ann_path.exists():
        return []

    legs = {(r["circuit_id"], r["leg_index"]): r
            for r in csv.DictReader(legs_path.open(encoding="utf-8"))}

    last_ann: dict[tuple, str] = {}
    for r in csv.DictReader(ann_path.open(encoding="utf-8")):
        last_ann[(r["circuit_id"], r["leg_index"])] = r["label"]

    rows = []
    for key, label in last_ann.items():
        if key not in legs or label == "uncertain":
            continue
        leg = legs[key]
        rows.append({
            "map":   map_name,
            "label": label,
            "pc1":   float(leg["pc1"]),
            **{f: float(leg.get(f, 0)) for f in FEATURES},
        })
    return rows


def _fmt(v: float, s: float) -> str:
    return f"{v:+.3f}±{s:.3f}"


# ── Chargement ────────────────────────────────────────────────────────────────

all_rows: list[dict] = []
for m in FOREST_MAPS:
    r = _load(m)
    if r:
        all_rows.extend(r)
    else:
        print(f"  [WARN] {m} : données manquantes")

# ── Test n°1A — Séparation PC1 par carte ─────────────────────────────────────

print(f"\n{'═'*62}")
print("  TEST 1A — Séparation PC1 suivi vs attaque par carte")
print(f"{'═'*62}")
hdr = f"  {'Carte':12s}  {'n_s':>4}  {'PC1(sui)':>9}  {'n_a':>4}  {'PC1(att)':>9}  {'delta':>9}"
print(hdr)
print(f"  {'-'*58}")

for m in FOREST_MAPS:
    rows = [r for r in all_rows if r["map"] == m]
    sui  = [r["pc1"] for r in rows if r["label"] == "suivi"]
    att  = [r["pc1"] for r in rows if r["label"] == "attaque"]
    if not sui or not att:
        print(f"  {m:12s}  n_s={len(sui)}  n_a={len(att)}  — insuffisant")
        continue
    ms, ma = np.mean(sui), np.mean(att)
    delta  = ma - ms
    flag   = "  ← INVERSÉ" if delta < 0 else ""
    print(f"  {m:12s}  {len(sui):>4}  {ms:+9.3f}  {len(att):>4}  {ma:+9.3f}  {delta:+9.3f}{flag}")

# ── Test n°1B — Features ISOM structurelles par carte ────────────────────────

print(f"\n{'═'*62}")
print("  TEST 1B — Features ISOM (toutes jambes annotées valides)")
print(f"{'═'*62}")

col_w = 16
header = f"  {'Carte':12s}" + "".join(f"  {f[:14]:>{col_w}}" for f in FEATURES)
print(header)
print(f"  {'-'*( 14 + len(FEATURES)*(col_w+2) )}")

for m in FOREST_MAPS:
    rows = [r for r in all_rows if r["map"] == m]
    if not rows:
        continue
    line = f"  {m:12s}"
    for f in FEATURES:
        vals = [r[f] for r in rows]
        line += f"  {np.mean(vals):+6.3f}±{np.std(vals):.3f}".rjust(col_w + 2)
    print(line)

# ── Test n°2 — Jambes "attaque" Cerisy vs Grochot ────────────────────────────

print(f"\n{'═'*62}")
print("  TEST 2 — Jambes 'attaque' : Cerisy vs Grochot")
print(f"{'═'*62}")

cerisy_att  = [r for r in all_rows if r["map"] == "cerisy"  and r["label"] == "attaque"]
grochot_att = [r for r in all_rows if r["map"] == "grochot" and r["label"] == "attaque"]

print(f"  n(cerisy attaque)={len(cerisy_att)}   n(grochot attaque)={len(grochot_att)}")
print()
hdr2 = f"  {'Feature':28s}  {'Cerisy':>14}  {'Grochot':>14}  {'MW p':>7}"
print(hdr2)
print(f"  {'-'*66}")

for f in ["pc1"] + FEATURES:
    c = [r[f] for r in cerisy_att]
    g = [r[f] for r in grochot_att]
    if len(c) < 2 or len(g) < 2:
        continue
    _, p = mannwhitneyu(c, g, alternative="two-sided")
    sig  = " *" if p < 0.05 else ("  " if p >= 0.10 else " ~")
    mc, mg = np.mean(c), np.mean(g)
    print(f"  {f:28s}  {mc:+6.3f}±{np.std(c):.3f}  {mg:+6.3f}±{np.std(g):.3f}  {p:.4f}{sig}")

print()
