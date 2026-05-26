"""
Visualisation manifold PC1-PC2 — dataset v2.

Usage: python backend/scripts/plot_manifold.py [path/to/intent_legs_a8b_v2.csv]

Figure 2x2 :
  A  PC1-PC2 par carte (stanne/crohot), forme = TD
  B  PC1-PC2 par TD (3/4/5), forme = carte
  C  PC1-PC2 colorié par fitness (RdYlGn)
  D  PC1 -> fitness, 4 droites de régression (stanne_TD3, crohot_TD3, crohot_TD4, crohot_TD5)

Output : backend/debug/manifold_v2.png
"""

import sys
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_CSV = "backend/debug/intent_legs_a8b_v2.csv"
OUTPUT_PNG  = "backend/debug/manifold_v2.png"

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

MAP_COLORS  = {"stanne": "steelblue",  "crohot": "darkorange"}
TD_COLORS   = {3: "tab:green", 4: "tab:orange", 5: "tab:red"}
TD_MARKERS  = {3: "o", 4: "^", 5: "D"}
MAP_MARKERS = {"stanne": "o", "crohot": "s"}
GROUP_STYLE = {
    "stanne_3":  dict(color="tab:green",  marker="o", ls="--", label="stanne TD3"),
    "crohot_3":  dict(color="tab:green",  marker="s", ls="-",  label="crohot TD3"),
    "crohot_4":  dict(color="tab:orange", marker="s", ls="-",  label="crohot TD4"),
    "crohot_5":  dict(color="tab:red",    marker="s", ls="-",  label="crohot TD5"),
}


# ── Utilities ─────────────────────────────────────────────────────────────────

def load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_pca(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    Xc = X - X.mean(axis=0)
    _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    ev  = S ** 2 / max(len(X) - 1, 1)
    evr = ev / ev.sum()
    return evr, Xc @ Vt.T


# ── Load + PCA global + agrégation circuit ────────────────────────────────────

def load_circuits(csv_path: str) -> tuple[dict, np.ndarray]:
    rows    = load_csv(csv_path)
    all_cols = AFFORDANCE_COLS + INTENT_COLS

    feat_rows, meta_rows = [], []
    for r in rows:
        try:
            vec = [float(r[c]) for c in all_cols]
        except (ValueError, KeyError):
            continue
        fit_raw = r.get("fitness_total", "")
        if fit_raw in ("", None):
            continue
        try:
            fitness = float(fit_raw)
        except ValueError:
            continue
        feat_rows.append(vec)
        meta_rows.append({
            "circuit_id": r.get("circuit_id", ""),
            "td":         int(r.get("td", 0)),
            "map":        r.get("map_name", ""),
            "fitness":    fitness,
        })

    X    = np.array(feat_rows, dtype=float)
    evr, scores = run_pca(X)
    pc12 = scores[:, :2]

    circ: dict = {}
    for pc, m in zip(pc12, meta_rows):
        cid = m["circuit_id"]
        if cid not in circ:
            circ[cid] = {"td": m["td"], "map": m["map"],
                         "fitness": m["fitness"], "pcs": []}
        circ[cid]["pcs"].append(pc)

    cids    = list(circ.keys())
    pc_arr  = np.array([np.mean(circ[c]["pcs"], axis=0) for c in cids])
    fit_arr = np.array([circ[c]["fitness"]               for c in cids])
    td_arr  = np.array([circ[c]["td"]                    for c in cids], dtype=int)
    map_arr = np.array([circ[c]["map"]                   for c in cids])

    return {"pc": pc_arr, "fit": fit_arr, "td": td_arr, "map": map_arr}, evr


# ── Panel A — PC1-PC2 par carte ───────────────────────────────────────────────

def panel_a(ax: plt.Axes, data: dict, evr: np.ndarray) -> None:
    pc, td, maps = data["pc"], data["td"], data["map"]

    for map_name, color in MAP_COLORS.items():
        for td_val, marker in TD_MARKERS.items():
            mask = (maps == map_name) & (td == td_val)
            if not mask.any():
                continue
            ax.scatter(pc[mask, 0], pc[mask, 1],
                       c=color, marker=marker, s=55, alpha=0.85,
                       edgecolors="white", linewidths=0.5)

    # Centroïdes TD3 par carte
    for map_name, color in MAP_COLORS.items():
        mask = (maps == map_name) & (td == 3)
        if not mask.any():
            continue
        cx, cy = pc[mask, 0].mean(), pc[mask, 1].mean()
        ax.scatter(cx, cy, c=color, marker="+", s=200,
                   linewidths=2.5, zorder=5)
        ax.annotate(f"{map_name}\nTD3 centroid",
                    xy=(cx, cy), xytext=(5, 5), textcoords="offset points",
                    fontsize=7, color=color)

    # Légende carte (couleur) + TD (forme)
    legend_map  = [mpatches.Patch(color=c, label=m) for m, c in MAP_COLORS.items()]
    legend_td   = [plt.Line2D([0], [0], marker=TD_MARKERS[t], color="gray",
                              linestyle="None", markersize=7, label=f"TD{t}")
                   for t in (3, 4, 5)]
    ax.legend(handles=legend_map + legend_td, fontsize=7, loc="best")
    ax.set_xlabel(f"PC1 ({evr[0]:.1%} var)", fontsize=9)
    ax.set_ylabel(f"PC2 ({evr[1]:.1%} var)", fontsize=9)
    ax.set_title("A — PC1-PC2 par carte", fontsize=10)
    ax.axhline(0, lw=0.4, color="gray"); ax.axvline(0, lw=0.4, color="gray")


# ── Panel B — PC1-PC2 par TD ──────────────────────────────────────────────────

def panel_b(ax: plt.Axes, data: dict, evr: np.ndarray) -> None:
    pc, td, maps = data["pc"], data["td"], data["map"]

    for td_val, color in TD_COLORS.items():
        for map_name, marker in MAP_MARKERS.items():
            mask = (td == td_val) & (maps == map_name)
            if not mask.any():
                continue
            filled = (map_name == "crohot")
            ax.scatter(pc[mask, 0], pc[mask, 1],
                       c=color if filled else "none",
                       edgecolors=color, marker=marker, s=55, alpha=0.85,
                       linewidths=1.2)

    legend_td  = [mpatches.Patch(color=TD_COLORS[t], label=f"TD{t}")
                  for t in (3, 4, 5)]
    legend_map = [plt.Line2D([0], [0], marker=MAP_MARKERS[m],
                             color="gray", linestyle="None", markersize=7,
                             markerfacecolor="gray" if m == "crohot" else "none",
                             markeredgecolor="gray", label=m)
                  for m in ("stanne", "crohot")]
    ax.legend(handles=legend_td + legend_map, fontsize=7, loc="best")
    ax.set_xlabel(f"PC1 ({evr[0]:.1%} var)", fontsize=9)
    ax.set_ylabel(f"PC2 ({evr[1]:.1%} var)", fontsize=9)
    ax.set_title("B — PC1-PC2 par TD", fontsize=10)
    ax.axhline(0, lw=0.4, color="gray"); ax.axvline(0, lw=0.4, color="gray")


# ── Panel C — PC1-PC2 par fitness ─────────────────────────────────────────────

def panel_c(ax: plt.Axes, data: dict, evr: np.ndarray) -> None:
    pc, fit = data["pc"], data["fit"]
    sc = ax.scatter(pc[:, 0], pc[:, 1], c=fit, cmap="RdYlGn",
                    s=55, alpha=0.9, edgecolors="white", linewidths=0.5)
    plt.colorbar(sc, ax=ax, label="fitness_total", shrink=0.85, pad=0.02)

    # Annoter min/max
    i_min, i_max = int(fit.argmin()), int(fit.argmax())
    for i, lbl in [(i_min, f"min\n{fit[i_min]:.2f}"),
                   (i_max, f"max\n{fit[i_max]:.2f}")]:
        ax.annotate(lbl, xy=(pc[i, 0], pc[i, 1]),
                    xytext=(5, 5), textcoords="offset points", fontsize=7)

    ax.set_xlabel(f"PC1 ({evr[0]:.1%} var)", fontsize=9)
    ax.set_ylabel(f"PC2 ({evr[1]:.1%} var)", fontsize=9)
    ax.set_title("C — PC1-PC2 par fitness", fontsize=10)
    ax.axhline(0, lw=0.4, color="gray"); ax.axvline(0, lw=0.4, color="gray")


# ── Panel D — PC1 -> fitness, 4 groupes ───────────────────────────────────────

def panel_d(ax: plt.Axes, data: dict) -> None:
    pc1, fit, td, maps = data["pc"][:, 0], data["fit"], data["td"], data["map"]

    groups = {
        "stanne_3": (maps == "stanne") & (td == 3),
        "crohot_3": (maps == "crohot") & (td == 3),
        "crohot_4": (maps == "crohot") & (td == 4),
        "crohot_5": (maps == "crohot") & (td == 5),
    }

    for key, mask in groups.items():
        if not mask.any():
            continue
        style = GROUP_STYLE[key]
        x, y  = pc1[mask], fit[mask]
        ax.scatter(x, y, color=style["color"], marker=style["marker"],
                   s=50, alpha=0.8, zorder=3)

        if len(x) >= 2:
            coeffs = np.polyfit(x, y, 1)
            slope, intercept = coeffs[0], coeffs[1]
            x_line = np.linspace(x.min(), x.max(), 60)
            ax.plot(x_line, np.polyval(coeffs, x_line),
                    color=style["color"], ls=style["ls"], lw=1.5,
                    label=f"{style['label']}  slope={slope:+.1f}")

            # Annoter la pente au milieu de la droite
            xm = float(x.mean())
            ym = float(slope * xm + intercept)
            ax.annotate(f"slope={slope:+.1f}",
                        xy=(xm, ym), xytext=(4, 4), textcoords="offset points",
                        fontsize=7, color=style["color"])

    ax.legend(fontsize=7, loc="best")
    ax.set_xlabel("PC1 (mean / circuit)", fontsize=9)
    ax.set_ylabel("fitness_total", fontsize=9)
    ax.set_title("D — PC1 -> fitness par (carte, TD)", fontsize=10)
    ax.axhline(ax.get_ylim()[0] if ax.get_ylim()[0] != 0 else 0,
               lw=0, color="none")  # force autoscale
    ax.axvline(0, lw=0.4, color="gray")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(csv_path: str) -> None:
    print(f"Chargement {csv_path} ...")
    data, evr = load_circuits(csv_path)
    n = len(data["pc"])
    n_s = int((data["map"] == "stanne").sum())
    n_c = int((data["map"] == "crohot").sum())
    print(f"  {n} circuits  (stanne={n_s}, crohot={n_c})")
    print(f"  Variance expliquee : PC1={evr[0]:.3f}  PC2={evr[1]:.3f}")

    fig, axes = plt.subplots(2, 2, figsize=(14, 10.5))
    fig.suptitle(
        f"Manifold PC1-PC2 — dataset v2  ({n} circuits, 4 x (carte, TD))\n"
        f"PC1={evr[0]:.1%} var  |  PC2={evr[1]:.1%} var",
        fontsize=11, y=0.995,
    )

    panel_a(axes[0, 0], data, evr)
    panel_b(axes[0, 1], data, evr)
    panel_c(axes[1, 0], data, evr)
    panel_d(axes[1, 1], data)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUTPUT_PNG, dpi=120, bbox_inches="tight")
    print(f"\nSauvegarde : {OUTPUT_PNG}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    main(path)
