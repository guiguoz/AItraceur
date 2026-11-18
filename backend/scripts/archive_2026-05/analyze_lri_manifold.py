#!/usr/bin/env python3
"""
Caractérisation du support latent LRI — 6 cartes (3 forêts + 3 sprints).

Sorties :
  1. Loadings PCA — quelles features définissent open vs handrail
  2. Fingerprint intent par carte — diversité navigationnelle
  3. Géométrie distances 2D par carte — in-support vs hors support
  4. Figure PNG → output/analyze_lri_manifold.png
"""

import csv
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_SCRIPT  = pathlib.Path(__file__).parent
_BACKEND = _SCRIPT.parent
_ROOT    = _BACKEND.parent

# ── Modèle LRI ────────────────────────────────────────────────────────────

with open(_BACKEND / "data" / "lri_baseline.json") as f:
    lri = json.load(f)

feature_cols   = lri["feature_cols"]                      # 10 features
pca_components = np.array(lri["pca_components"])          # (2, 10)
centroids_pc   = np.array(lri["cluster_centroids_pc"])    # [[2.666,-0.196], [-1.714,0.126]]
variance_ratio = lri["pca_variance_ratio"]                # [0.647, 0.139]

c_dist       = float(np.linalg.norm(centroids_pc[0] - centroids_pc[1]))
midpoint_pc1 = float(np.mean(centroids_pc[:, 0]))

INTENT_LABELS = [
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
    "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
]

# ── Configuration des cartes ──────────────────────────────────────────────

# crohot : pas de benchmark CSV — intent uniquement depuis intent_legs.csv
BENCH_MAPS = {
    "airelles": ("output/benchmark_lri_airelles.csv", "output/benchmark_airelles.log"),
    "llose":    ("output/benchmark_lri_llose.csv",    "output/benchmark_llose.log"),
    "bayeux":   ("output/benchmark_lri_bayeux.csv",   "output/benchmark_bayeux.log"),
    "caen":     ("output/benchmark_lri_caen.csv",     "output/benchmark_caen.log"),
    "langrune": ("output/benchmark_lri_langrune.csv", "output/benchmark_langrune.log"),
}
MAP_TYPE = {
    "crohot": "forêt", "airelles": "forêt", "llose": "forêt",
    "bayeux": "sprint", "caen": "sprint", "langrune": "sprint",
}
COLORS = {
    "crohot":   "#2ca02c",
    "airelles": "#17becf",
    "llose":    "#98df8a",
    "bayeux":   "#d62728",
    "caen":     "#ff7f0e",
    "langrune": "#9467bd",
}

# ── 1. Géométrie depuis les CSVs benchmark ────────────────────────────────

def _load_csv(path):
    p = _ROOT / path
    if not p.exists():
        return []
    return list(csv.DictReader(open(p, encoding="utf-8")))

geo = {}

for name, (csv_path, _) in BENCH_MAPS.items():
    rows = _load_csv(csv_path)
    sel  = [r for r in rows if r["level"] == "selected"]

    # Condition A : régime naturel + PC1
    a_rows = [r for r in sel if r["condition"] == "A"]
    pc1_a  = [float(r["pc1_offset_from_boundary"]) + midpoint_pc1 for r in a_rows]

    nat_regs = []
    for pc1 in pc1_a:
        d_open = abs(pc1 - centroids_pc[0, 0])
        d_hrl  = abs(pc1 - centroids_pc[1, 0])
        nat_regs.append("open" if d_open < d_hrl else "handrail")
    natural_regime = max(set(nat_regs), key=nat_regs.count) if nat_regs else "?"

    # Condition B-open-w5 : distances 2D vraies
    b5 = [r for r in sel if r["condition"] == "B-open-w5"]
    dist_t  = [float(r["support_radius"]) * c_dist for r in b5 if r.get("support_radius")]
    margins = [float(r["margin"])          for r in b5 if r.get("margin")]
    supp_r  = [float(r["support_radius"]) for r in b5 if r.get("support_radius")]
    ent0    = [float(r["entropy_gen0"])    for r in a_rows if r.get("entropy_gen0")]

    geo[name] = {
        "natural_regime": natural_regime,
        "pc1_mean":   np.mean(pc1_a) if pc1_a else float("nan"),
        "pc1_vals":   pc1_a,
        "dist_t":     np.mean(dist_t)  if dist_t  else float("nan"),
        "supp_r":     np.mean(supp_r)  if supp_r  else float("nan"),
        "margin":     np.mean(margins) if margins  else float("nan"),
        "entropy_g0": np.mean(ent0)    if ent0     else float("nan"),
        "dist_t_vals":  dist_t,
        "margin_vals":  margins,
    }

# ── 2. Fingerprint intent ─────────────────────────────────────────────────

intent_frac = {}

# Crohot : depuis intent_legs.csv (scores continus → dominant = argmax par jambe)
crohot_csv = _BACKEND / "debug" / "intent_legs.csv"
if crohot_csv.exists():
    by_circuit = {}
    for row in csv.DictReader(open(crohot_csv, encoding="utf-8")):
        cid = row["circuit_id"]
        scores = {lbl: float(row.get(lbl, 0)) for lbl in INTENT_LABELS}
        by_circuit.setdefault(cid, []).append(scores)
    fracs = {lbl: [] for lbl in INTENT_LABELS}
    for legs in by_circuit.values():
        n = len(legs)
        dom = {lbl: 0 for lbl in INTENT_LABELS}
        for leg in legs:
            dom[max(leg, key=leg.get)] += 1
        for lbl in INTENT_LABELS:
            fracs[lbl].append(dom[lbl] / n)
    intent_frac["crohot"] = {lbl: float(np.mean(v)) for lbl, v in fracs.items()}

# Autres cartes : depuis les logs benchmark (dominant_hist)
for name, (_, log_path) in BENCH_MAPS.items():
    if log_path is None:
        continue
    p = _ROOT / log_path
    if not p.exists():
        continue
    fracs = {lbl: [] for lbl in INTENT_LABELS}
    for line in open(p, encoding="utf-8", errors="replace"):
        if "[intent_json]" not in line:
            continue
        try:
            d = json.loads(line.split("[intent_json]")[1])
        except Exception:
            continue
        n    = max(d.get("legs", 1), 1)
        hist = d.get("dominant_hist", {})
        for lbl in INTENT_LABELS:
            fracs[lbl].append(hist.get(lbl, 0) / n)
    if any(v for v in fracs.values()):
        intent_frac[name] = {lbl: float(np.mean(v)) for lbl, v in fracs.items()}

# ── Affichage 1 — Loadings PCA ────────────────────────────────────────────

print()
print("=" * 68)
print(f"  LOADINGS PCA  (PC1={variance_ratio[0]*100:.1f}%  PC2={variance_ratio[1]*100:.1f}%)")
print("  PC1+ → open (navigation autonome)   PC1- → handrail (guidé)")
print("=" * 68)
abs_pc1 = sorted(enumerate(pca_components[0]), key=lambda x: abs(x[1]), reverse=True)
ranks   = {i: r + 1 for r, (i, _) in enumerate(abs_pc1)}
print(f"  {'feature':<28}  {'PC1':>8}  {'PC2':>8}  {'rank|PC1|':>9}")
print("  " + "-" * 58)
for i, feat in enumerate(feature_cols):
    print(f"  {feat:<28}  {pca_components[0][i]:+8.3f}  {pca_components[1][i]:+8.3f}  #{ranks[i]}")

# ── Affichage 2 — Fingerprint intent ─────────────────────────────────────

LSHORT = ["HANDRAIL", "LINE_X", "ATTACK", "DIRECT", "RELIEF", "SAFETY"]
print()
print("=" * 78)
print("  FINGERPRINT INTENT — fraction des jambes avec cette étiquette dominante")
print("  (crohot = argmax score continu ; autres = dominant_hist / legs)")
print("=" * 78)
print(f"  {'carte':<10}  {'type':<7}", end="")
for s in LSHORT:
    print(f"  {s:>8}", end="")
print()
print("  " + "-" * 74)
for name in ["crohot"] + list(BENCH_MAPS):
    if name not in intent_frac:
        continue
    fracs = intent_frac[name]
    dominant = max(INTENT_LABELS, key=lambda l: fracs.get(l, 0))
    print(f"  {name:<10}  {MAP_TYPE.get(name, '?'):<7}", end="")
    for lbl in INTENT_LABELS:
        v = fracs.get(lbl, 0)
        marker = "*" if lbl == dominant else " "
        print(f"  {v:7.3f}{marker}", end="")
    print()
print("  (* = intent dominant sur cette carte)")

# ── Affichage 3 — Géométrie distances 2D ─────────────────────────────────

print()
print("=" * 90)
print("  GÉOMÉTRIE PC — distances 2D réelles (B-open-w5, target=open centroid)")
print(f"  c_dist={c_dist:.3f}  support_radius=dist_target/c_dist")
print(f"  Forêt baseline : support_radius 0.03–0.29  margin +4.0–+4.4  entropy_gen0 0.59–0.69")
print("=" * 90)
print(f"  {'carte':<10}  {'type':<7}  {'nat_regime':<11}  "
      f"{'PC1_mean':>9}  {'dist_target':>11}  {'supp_r':>7}  {'margin':>7}  {'ent_gen0':>9}")
print("  " + "-" * 82)
for name, g in geo.items():
    print(f"  {name:<10}  {MAP_TYPE[name]:<7}  {g['natural_regime']:<11}  "
          f"{g['pc1_mean']:+9.2f}  "
          f"{g['dist_t']:11.3f}  "
          f"{g['supp_r']:7.3f}  "
          f"{g['margin']:+7.3f}  "
          f"{g['entropy_g0']:9.3f}")

# Verdict Bayeux
b = geo.get("bayeux", {})
sr = b.get("supp_r", float("nan"))
if not np.isnan(sr):
    verdict = "HORS SUPPORT (dist_target >> baseline)" if sr > 1.0 else "DANS SUPPORT — régime homogène handrail"
    print(f"\n  Bayeux support_radius={sr:.3f}  → {verdict}")

# ── Figure ────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 3, figsize=(18, 6))
fig.suptitle("Caractérisation support latent LRI — 5 cartes benchmark", fontsize=13)

# Fig 1 : dist_target vs margin scatter
ax = axes[0]
for name, g in geo.items():
    if not g["dist_t_vals"]:
        continue
    mkr = "o" if MAP_TYPE[name] == "forêt" else "^"
    ax.scatter(g["dist_t_vals"], g["margin_vals"],
               color=COLORS[name], marker=mkr, s=120,
               label=f"{name} ({MAP_TYPE[name]})", zorder=5)
ax.axhline(0, color="gray", linestyle="--", lw=1)
ax.axvline(c_dist, color="gray", linestyle=":", lw=1, label=f"c_dist={c_dist:.2f}")
ax.set_xlabel("dist_target 2D  (support_radius × c_dist)")
ax.set_ylabel("margin  (dist_other − dist_target)")
ax.set_title("Distances 2D vraies (B-open-w5)")
ax.legend(fontsize=8)

# Fig 2 : PC1 strip plot (condition A)
ax = axes[1]
names_ord = list(geo.keys())
for i, name in enumerate(names_ord):
    g = geo[name]
    if not g["pc1_vals"]:
        continue
    ax.scatter([i] * len(g["pc1_vals"]), g["pc1_vals"],
               color=COLORS[name], s=80, zorder=5)
    ax.plot([i - 0.35, i + 0.35], [g["pc1_mean"]] * 2,
            color=COLORS[name], lw=2.5)
ax.axhline(centroids_pc[0, 0], color="steelblue", linestyle="--", lw=1.2,
           label=f"open  PC1={centroids_pc[0,0]:.2f}")
ax.axhline(centroids_pc[1, 0], color="tomato",    linestyle="--", lw=1.2,
           label=f"handrail PC1={centroids_pc[1,0]:.2f}")
ax.axhline(midpoint_pc1, color="gray", linestyle=":", lw=1)
ax.set_xticks(range(len(names_ord)))
ax.set_xticklabels(names_ord, rotation=30, ha="right")
ax.set_ylabel("PC1")
ax.set_title("PC1 distribution — condition A (régime naturel)")
ax.legend(fontsize=8)

# Fig 3 : intent fingerprint heatmap
ax = axes[2]
map_order = [n for n in ["crohot"] + list(BENCH_MAPS) if n in intent_frac]
matrix    = np.array([[intent_frac[n].get(lbl, 0) for lbl in INTENT_LABELS]
                      for n in map_order])
im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", vmin=0, vmax=0.8)
ax.set_xticks(range(len(INTENT_LABELS)))
ax.set_xticklabels(LSHORT, rotation=40, ha="right", fontsize=9)
ax.set_yticks(range(len(map_order)))
ax.set_yticklabels(map_order)
for i in range(len(map_order)):
    for j in range(len(INTENT_LABELS)):
        ax.text(j, i, f"{matrix[i,j]:.2f}", ha="center", va="center",
                fontsize=8, color="black" if matrix[i, j] < 0.5 else "white")
plt.colorbar(im, ax=ax, fraction=0.046)
ax.set_title("Fingerprint intent (fraction jambes dominantes)")

plt.tight_layout()
out_path = _ROOT / "output" / "analyze_lri_manifold.png"
plt.savefig(out_path, dpi=150)
print(f"\n  Figure → {out_path}")
