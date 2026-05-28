"""
benchmark_lri.py -- A/B diversity experiment: GA standard vs GA+LRI.

Mesure si la post-selection LRI modifie la distribution geometrique des circuits
dans l'espace PC1/PC2. Experience sur la geometrie, pas sur la qualite d'optimisation.

Conditions :
  A           : latent_regime=None       (baseline GA, sans LRI)
  B-open      : latent_regime="open"     (post-selection azimutale)
  B-handrail  : latent_regime="handrail" (post-selection lineaire)

4 niveaux par run (meme seed -> population/pool identiques entre conditions) :
  population  : population finale GA (n=POP_SIZE)
  top_k       : top-K par fitness (sans diversite PC)
  pool        : _lri_diverse_pool() = top_k + diversite geometrique PC
  selected    : circuit final (LRI pour B, argmax fitness pour A)

Protocole deux passes :
  Passe 1 : 60 runs sans redundancy_rate, collecte pcs population condition A
  Passe 2 : calcul eps = 0.5 * median(pairwise_A), post-traitement CSV

Usage :
  python backend/scripts/benchmark_lri.py
  python backend/scripts/benchmark_lri.py --n_seeds 5     # test rapide
  python backend/scripts/benchmark_lri.py --expected_hash <hash>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pathlib
import random
import subprocess
import sys
import time
from collections import Counter
from itertools import combinations
from typing import Optional

import numpy as np

# ── Chemins ──────────────────────────────────────────────────────────────────

_ROOT    = pathlib.Path(__file__).parent.parent.parent
_BACKEND = _ROOT / "backend"

sys.path.insert(0, str(_BACKEND / "src"))

from services.generation.genetic_algo import GeneticAlgorithm, GenerationConfig  # noqa: E402
from services.generation.lri_model import get_lri_model                           # noqa: E402
from services.generation.perceptual_model import build_segment_index              # noqa: E402
from services.ocad.geojson_extractor import extract_line_segments                 # noqa: E402

# ── Constantes ────────────────────────────────────────────────────────────────

OCD_PATH = (
    r"E:\RunningRaid\Cartographie\fichiers OCAD et jpg"
    r"\O12_2019-05-25_Grand-Crohot-Nord_ech-15000.ocd10.ocd"
)

N_SEEDS   = 20
TD        = 4      # TD4 : variabilite maximale entre regimes
POP_SIZE  = 30     # reduit pour benchmark (~8s/run)
GENS      = 40
TOP_K     = 20     # top-K fitness avant greedy diversity
N_DIVERSE = 10     # circuits geometriquement diversifies ajoutes au pool

DISTANCES = {3: 4000, 4: 6000, 5: 9000}
CONTROLS  = {3: 11,   4: 15,   5: 20}
CT_TYPE   = {3: "md", 4: "ld", 5: "ld"}

CONDITIONS = [(None, "A"), ("open", "B-open"), ("handrail", "B-handrail")]

OUTPUT_DIR = _ROOT / "output"

# ── Node.js OCD parser ───────────────────────────────────────────────────────

_NODE_EXTRACT = r"""
const proj4 = require('proj4');
const { readOcad, ocadToGeoJson } = require('ocad2geojson');
proj4.defs('EPSG:2154', '+proj=lcc +lat_0=46.5 +lon_0=3 +lat_1=44 +lat_2=49 +x_0=700000 +y_0=6600000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs');
(async () => {
    const ocadFile = await readOcad(process.argv[2]);
    const crs = ocadFile.getCrs();
    const code = crs && crs.code;
    let converter = null;
    if (code && code !== 4326) {
        const ep = 'EPSG:' + code;
        if (proj4.defs(ep)) {
            const fwd = proj4(ep, 'WGS84');
            converter = (xy) => fwd.forward(xy);
        }
    }
    const xs = [], ys = [];
    function reproj(coords) {
        if (typeof coords[0] === 'number') {
            const pt = converter ? converter([coords[0], coords[1]]) : [coords[0], coords[1]];
            xs.push(pt[0]); ys.push(pt[1]);
            return pt;
        }
        return coords.map(reproj);
    }
    const geojson = ocadToGeoJson(ocadFile);
    const allFeatures = geojson.features.map(f => {
        if (!f.geometry || !f.geometry.coordinates) return f;
        return { ...f, geometry: { ...f.geometry, coordinates: reproj(f.geometry.coordinates) } };
    });
    if (xs.length === 0) { process.stderr.write('No coords extracted\n'); process.exit(1); }
    xs.sort((a, b) => a - b); ys.sort((a, b) => a - b);
    const p = (arr, q) => arr[Math.max(0, Math.min(arr.length - 1, Math.floor(arr.length * q)))];
    const bbox = [p(xs, 0.01), p(ys, 0.01), p(xs, 0.99), p(ys, 0.99)];
    const lineFeats = allFeatures.filter(f =>
        f.geometry && (f.geometry.type === 'LineString' || f.geometry.type === 'MultiLineString')
    );
    console.log(JSON.stringify({ bbox, features: lineFeats }));
})().catch(e => { process.stderr.write(e.message + '\n'); process.exit(1); });
"""


def _parse_ocd_data(ocd_path: str) -> tuple[dict, list]:
    tile_dir = _BACKEND / "tile-service"
    tmp = tile_dir / "_benchmark_lri_tmp.js"
    tmp.write_text(_NODE_EXTRACT, encoding="utf-8")
    try:
        r = subprocess.run(
            ["node", str(tmp), ocd_path],
            capture_output=True, text=True, cwd=str(tile_dir), timeout=60,
        )
    finally:
        tmp.unlink(missing_ok=True)

    if r.returncode != 0:
        raise RuntimeError(f"node parse failed: {r.stderr[:400]}")

    result = json.loads(r.stdout.strip())
    raw_bbox = result["bbox"]
    if not raw_bbox or len(raw_bbox) != 4:
        raise ValueError(f"Bounds invalides: {raw_bbox}")

    min_lon, min_lat, max_lon, max_lat = raw_bbox
    margin = 0.001
    bbox = {
        "min_x": min_lon - margin,
        "max_x": max_lon + margin,
        "min_y": min_lat - margin,
        "max_y": max_lat + margin,
    }
    return bbox, result.get("features", [])


# ── Helpers metriques ─────────────────────────────────────────────────────────

def _regime_entropy(regimes: list[str]) -> float:
    if not regimes:
        return float("nan")
    counts = Counter(regimes)
    n = len(regimes)
    return -sum((v / n) * math.log(v / n) for v in counts.values() if v > 0)


def _project_circuits(circuits, ga: GeneticAlgorithm, lri) -> np.ndarray:
    """Project circuits to (n_valid, 2) PC space."""
    pcs = []
    for c in circuits:
        feats = ga._aggregate_circuit_features(c)
        if feats is not None:
            pcs.append(lri.project(feats))
    return np.array(pcs) if pcs else np.empty((0, 2))


def _compute_geometry(pcs: np.ndarray, eps: float) -> dict:
    """Geometric metrics for a set of PC projections. eps=0 -> redundancy_rate=nan."""
    n = len(pcs)
    nan = float("nan")

    if n < 2:
        return {
            "n_valid_lri": n, "pr": nan, "pc1_fraction": nan,
            "hull_area": nan, "hull_area_norm": nan,
            "pairwise_mean": nan, "pairwise_var": nan, "redundancy_rate": nan,
        }

    cov = np.cov(pcs.T)
    eigvals = np.linalg.eigvalsh(cov)
    cov_trace = float(eigvals.sum())
    if cov_trace < 1e-12:
        pr, pc1_fraction = 1.0, 1.0
    else:
        pr = float(cov_trace ** 2 / (eigvals ** 2).sum())
        pc1_fraction = float(eigvals.max() / cov_trace)

    hull_area = 0.0
    if n >= 3 and np.linalg.matrix_rank(pcs - pcs.mean(axis=0)) >= 2:
        try:
            from scipy.spatial import ConvexHull
            hull_area = float(ConvexHull(pcs).volume)  # volume = area en 2D
        except Exception:
            hull_area = 0.0
    hull_area_norm = hull_area / max(cov_trace, 1e-9)

    pairs = [(i, j) for i, j in combinations(range(n), 2)]
    dists = [float(np.linalg.norm(pcs[i] - pcs[j])) for i, j in pairs]
    pairwise_mean = float(np.mean(dists))
    pairwise_var  = float(np.var(dists))
    redundancy_rate = (
        float(np.mean([d < eps for d in dists])) if eps > 0 else nan
    )

    return {
        "n_valid_lri": n,
        "pr": pr,
        "pc1_fraction": pc1_fraction,
        "hull_area": hull_area,
        "hull_area_norm": hull_area_norm,
        "pairwise_mean": pairwise_mean,
        "pairwise_var": pairwise_var,
        "redundancy_rate": redundancy_rate,
    }


def _fitness_hash(population) -> int:
    return hash(tuple(sorted(round(c.fitness, 6) for c in population)))


# ── RunResult ─────────────────────────────────────────────────────────────────

def run_one(
    seed: int,
    condition: Optional[str],
    condition_label: str,
    bbox: dict,
    seg_index,
    lri,
    eps: float,
) -> tuple[list[dict], dict[str, np.ndarray], int]:
    """
    Execute one GA run.

    Returns:
        records        : list of CSV rows (one per level)
        pcs_by_level   : dict level -> (n_valid, 2) ndarray (for scatter + eps calibration)
        fitness_hash   : hash of sorted fitness values (population identity check)
    """
    random.seed(seed)
    np.random.seed(seed)

    center_x = (bbox["min_x"] + bbox["max_x"]) / 2
    center_y = (bbox["min_y"] + bbox["max_y"]) / 2
    start = end = (center_x, center_y)

    cfg = GenerationConfig(
        bounding_box=bbox,
        target_length_m=DISTANCES[TD],
        target_controls=CONTROLS[TD],
        circuit_type=CT_TYPE[TD],
        technical_level=TD,
        population_size=POP_SIZE,
        generations=GENS,
        heatmap_cache=None,
        elevation_cache=None,
        route_analyzer=None,
        segment_index=seg_index,
        ga_seed=seed,
        latent_regime=condition,
        benchmark_mode=True,
        timeout_seconds=120.0,
    )
    assert cfg.segment_index is not None, "seg_index absent du cfg avant init GA"

    t0 = time.time()
    ga = GeneticAlgorithm(cfg)
    assert ga._seg_index is not None, (
        "ga._seg_index est None apres init — _aggregate_circuit_features() retournera None."
        " Verifier que ocad_line_segments est non-vide."
    )
    ga.generate(start, end)
    elapsed = time.time() - t0

    population_snapshot = list(ga.population)
    top_k = population_snapshot[:TOP_K]
    pool = ga._lri_diverse_pool(top_k=TOP_K, n_diverse=N_DIVERSE)
    pre_lri_circuit = max(population_snapshot, key=lambda c: c.fitness)
    selected = ga.best_solution

    lri_changed = (selected is not None) and (selected is not pre_lri_circuit)

    print(
        f"  [{condition_label:<11} seed={seed:2d}] {elapsed:.1f}s "
        f"fitness={pre_lri_circuit.fitness:.1f}  lri_changed={lri_changed}"
    )

    # ── Projeter chaque niveau ────────────────────────────────────────────────
    pcs_by_level: dict[str, np.ndarray] = {}
    for level_name, circs in [
        ("population", population_snapshot),
        ("top_k", top_k),
        ("pool", pool),
    ]:
        pcs_by_level[level_name] = _project_circuits(circs, ga, lri)

    # PC pour selected (pre + post LRI)
    pre_feats = ga._aggregate_circuit_features(pre_lri_circuit)
    post_feats = ga._aggregate_circuit_features(selected) if selected else None
    pre_pc  = lri.project(pre_feats)  if pre_feats  is not None else None
    post_pc = lri.project(post_feats) if post_feats is not None else None

    if post_pc is not None:
        pcs_by_level["selected"] = np.array([post_pc])
    else:
        pcs_by_level["selected"] = np.empty((0, 2))

    # ── Regimes ──────────────────────────────────────────────────────────────
    regimes_by_level: dict[str, list[str]] = {}
    for lvl, pcs in pcs_by_level.items():
        regimes_by_level[lvl] = [lri.assign_regime(pc) for pc in pcs]

    # Chaine d'entropie
    entropy_topk = _regime_entropy(regimes_by_level["top_k"])
    entropy_pool = _regime_entropy(regimes_by_level["pool"])
    entropy_gain_pool = (
        entropy_pool - entropy_topk
        if not math.isnan(entropy_pool) and not math.isnan(entropy_topk)
        else float("nan")
    )

    # selection_alignment + regime_pressure (niveau pool comme reference)
    pool_regimes = regimes_by_level["pool"]
    mode_regime = Counter(pool_regimes).most_common(1)[0][0] if pool_regimes else ""
    pre_regime  = lri.assign_regime(pre_pc)  if pre_pc  is not None else ""
    post_regime = lri.assign_regime(post_pc) if post_pc is not None else ""
    selection_alignment = int(post_regime == mode_regime) if post_regime else float("nan")
    regime_pressure     = int(pre_regime  == mode_regime) if pre_regime  else float("nan")

    push_dist = (
        float(np.linalg.norm(post_pc - pre_pc))
        if pre_pc is not None and post_pc is not None
        else float("nan")
    )

    # ── Construire records CSV ────────────────────────────────────────────────
    records: list[dict] = []

    for level_name, circs in [
        ("population", population_snapshot),
        ("top_k", top_k),
        ("pool", pool),
    ]:
        pcs = pcs_by_level[level_name]
        geom = _compute_geometry(pcs, eps)
        regime_entropy_here = _regime_entropy(regimes_by_level[level_name])

        records.append({
            "condition": condition_label,
            "seed": seed,
            "level": level_name,
            "n_circuits": len(circs),
            **geom,
            "pool_entropy": regime_entropy_here,
            "entropy_gain_pool": round(entropy_gain_pool, 6) if level_name == "pool" else float("nan"),
            "selection_alignment": float("nan"),
            "regime_pressure": float("nan"),
            "pre_lri_regime": "",
            "post_lri_regime": "",
            "lri_changed_selection": "",
            "lri_push_distance": float("nan"),
        })

    # niveau selected
    sel_pcs = pcs_by_level["selected"]
    sel_geom = _compute_geometry(sel_pcs, eps)
    records.append({
        "condition": condition_label,
        "seed": seed,
        "level": "selected",
        "n_circuits": 1,
        **sel_geom,
        "pool_entropy": _regime_entropy(regimes_by_level["selected"]),
        "entropy_gain_pool": round(entropy_gain_pool, 6),
        "selection_alignment": selection_alignment,
        "regime_pressure": regime_pressure,
        "pre_lri_regime": pre_regime,
        "post_lri_regime": post_regime,
        "lri_changed_selection": lri_changed,
        "lri_push_distance": round(push_dist, 4),
    })

    return records, pcs_by_level, _fitness_hash(population_snapshot)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="LRI A/B diversity benchmark")
    parser.add_argument("--ocd_path", default=OCD_PATH)
    parser.add_argument("--expected_hash", default="", help="Expected seg_index hash (16 chars)")
    parser.add_argument("--n_seeds", type=int, default=N_SEEDS)
    args = parser.parse_args()

    n_seeds = args.n_seeds
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── LRI ──────────────────────────────────────────────────────────────────
    lri = get_lri_model()
    assert lri is not None, (
        "LRI model introuvable. Lancer d'abord: python backend/scripts/build_lri_model.py"
    )
    print(f"[benchmark] LRI loaded — regimes={lri.available_regimes}  v={lri.cluster_semantics_version}")

    # ── OCD + seg_index ──────────────────────────────────────────────────────
    print(f"[benchmark] Parsing OCD: {args.ocd_path}")
    bbox, features = _parse_ocd_data(args.ocd_path)
    center_lat = (bbox["min_y"] + bbox["max_y"]) / 2

    ocd_hash = hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()[:16]
    segments = extract_line_segments(features, center_lat=center_lat)
    seg_hash = hashlib.sha256(json.dumps(segments, sort_keys=True).encode()).hexdigest()[:16]

    if args.expected_hash and seg_hash != args.expected_hash:
        sys.exit(f"seg_index hash mismatch: got {seg_hash}, expected {args.expected_hash}")

    print(f"[benchmark] ocd_hash={ocd_hash}  seg_hash={seg_hash}  segments={len(segments)}")

    isom_sem_path = _BACKEND / "src" / "services" / "knowledge_base" / "isom_semantics.json"
    isom_sem = json.loads(isom_sem_path.read_text(encoding="utf-8")) if isom_sem_path.exists() else {}
    seg_index = build_segment_index(segments, isom_sem, center_lat)
    print(f"[benchmark] seg_index built — {seg_index.segment_count} segments")

    # ── Passe 1 : 60 runs sans redundancy_rate, collecte pcs_A ──────────────
    total_runs = len(CONDITIONS) * n_seeds
    print(f"\n=== Passe 1 : {total_runs} runs (eps=0 -> redundancy_rate=nan) ===")

    all_records: list[dict] = []
    all_pcs: dict[tuple, dict[str, np.ndarray]] = {}   # (cond_label, seed) -> pcs_by_level
    pop_hashes: dict[tuple, int] = {}                  # (cond_label, seed) -> fitness_hash

    for condition, label in CONDITIONS:
        print(f"\n-- condition {label} --")
        for seed in range(n_seeds):
            recs, pcs_by_level, fhash = run_one(
                seed, condition, label, bbox, seg_index, lri, eps=0.0
            )
            all_records.extend(recs)
            all_pcs[(label, seed)] = pcs_by_level
            pop_hashes[(label, seed)] = fhash

    # ── Valider identite population A == B pour les 3 premiers seeds ─────────
    print("\n[benchmark] Validation identite population A == B (seeds 0-2) :")
    for seed in range(min(3, n_seeds)):
        hA = pop_hashes.get(("A", seed))
        for _, label in CONDITIONS[1:]:
            hB = pop_hashes.get((label, seed))
            match = "OK" if hA == hB else "WARN mismatch"
            print(f"  seed={seed}  A vs {label} : {match}  (hA={hA}  hB={hB})")

    # ── Calculer eps depuis population condition A ────────────────────────────
    dists_A: list[float] = []
    pop_pcs_A = [all_pcs[("A", s)]["population"] for s in range(n_seeds) if len(all_pcs[("A", s)]["population"]) > 1]
    if pop_pcs_A:
        combined = np.vstack(pop_pcs_A)
        # Subsample 1/10 des paires pour vitesse (n peut etre grand)
        idx = list(range(len(combined)))
        step = max(1, len(combined) // 50)   # au plus ~50 points -> 1225 paires
        idx_sub = idx[::step]
        dists_A = [
            float(np.linalg.norm(combined[i] - combined[j]))
            for i, j in combinations(idx_sub, 2)
        ]
        eps = float(0.5 * np.median(dists_A)) if dists_A else 1.0
    else:
        eps = 1.0
    print(f"\n[benchmark] eps = {eps:.4f}  (n_dists_used={len(dists_A) if pop_pcs_A else 0})")

    # ── Passe 2 : mettre a jour redundancy_rate dans tous les records ─────────
    print("\n=== Passe 2 : post-traitement redundancy_rate ===")
    for rec in all_records:
        label = rec["condition"]
        seed  = rec["seed"]
        level = rec["level"]
        pcs = all_pcs.get((label, seed), {}).get(level, np.empty((0, 2)))
        n = len(pcs)
        if n >= 2:
            dists = [float(np.linalg.norm(pcs[i] - pcs[j])) for i, j in combinations(range(n), 2)]
            rec["redundancy_rate"] = float(np.mean([d < eps for d in dists]))

    # ── Ecrire CSV ────────────────────────────────────────────────────────────
    fieldnames = [
        "condition", "seed", "level", "n_circuits", "n_valid_lri",
        "pr", "pc1_fraction", "hull_area", "hull_area_norm",
        "pairwise_mean", "pairwise_var", "redundancy_rate",
        "pool_entropy", "entropy_gain_pool",
        "selection_alignment", "regime_pressure",
        "pre_lri_regime", "post_lri_regime", "lri_changed_selection", "lri_push_distance",
    ]
    csv_path = OUTPUT_DIR / "benchmark_lri_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_records)
    print(f"\n[benchmark] CSV -> {csv_path}  ({len(all_records)} rows)")

    # ── Scatter plot ──────────────────────────────────────────────────────────
    _plot_scatter(all_pcs, lri, n_seeds, OUTPUT_DIR)

    print(f"[benchmark] --expected_hash {seg_hash}  (pour reproductibilite)")


def _plot_scatter(
    all_pcs: dict,
    lri,
    n_seeds: int,
    output_dir: pathlib.Path,
) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from scipy.spatial import ConvexHull
    except ImportError:
        print("[benchmark] matplotlib/scipy absent — scatter non genere")
        return

    fig, ax = plt.subplots(figsize=(8, 6))

    cond_style = {
        "A":          {"color": "#888888", "marker": "o", "alpha": 0.55, "zorder": 2},
        "B-open":     {"color": "#1565C0", "marker": "^", "alpha": 0.75, "zorder": 3},
        "B-handrail": {"color": "#B71C1C", "marker": "s", "alpha": 0.75, "zorder": 3},
    }

    for label, style in cond_style.items():
        # Scatter des circuits selected (un point par seed)
        pcs_sel = []
        for seed in range(n_seeds):
            pcs = all_pcs.get((label, seed), {}).get("selected", np.empty((0, 2)))
            if len(pcs) == 1:
                pcs_sel.append(pcs[0])
        if not pcs_sel:
            continue
        arr = np.array(pcs_sel)
        ax.scatter(
            arr[:, 0], arr[:, 1],
            color=style["color"], marker=style["marker"],
            alpha=style["alpha"], s=50, zorder=style["zorder"],
            label=f"{label} selected (n={len(arr)})",
        )
        # Convex hull overlay pour les pools (tous seeds confondus)
        pcs_pool_all = []
        for seed in range(n_seeds):
            pcs = all_pcs.get((label, seed), {}).get("pool", np.empty((0, 2)))
            if len(pcs) >= 1:
                pcs_pool_all.append(pcs)
        if pcs_pool_all:
            pool_arr = np.vstack(pcs_pool_all)
            if len(pool_arr) >= 3 and np.linalg.matrix_rank(pool_arr - pool_arr.mean(0)) >= 2:
                try:
                    hull = ConvexHull(pool_arr)
                    verts = np.append(hull.vertices, hull.vertices[0])
                    ax.fill(
                        pool_arr[verts, 0], pool_arr[verts, 1],
                        alpha=0.07, color=style["color"],
                    )
                except Exception:
                    pass

    # Centroids LRI
    centroids = lri.cluster_centroids_pc
    for i, (cx, cy) in enumerate(centroids):
        regime = lri.regime_names.get(str(i), f"regime_{i}")
        ax.scatter(cx, cy, marker="*", s=400, color="gold", zorder=5,
                   edgecolors="black", linewidths=0.8)
        ax.annotate(regime, (cx, cy), textcoords="offset points",
                    xytext=(6, 6), fontsize=9, fontweight="bold")

    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.set_title(f"LRI benchmark TD{TD}  crohot  {n_seeds} seeds — circuits selected")
    ax.axhline(0, color="gray", lw=0.5, ls="--")
    ax.axvline(0, color="gray", lw=0.5, ls="--")
    ax.legend(loc="upper right", fontsize=9)
    plt.tight_layout()

    scatter_path = output_dir / "benchmark_lri_scatter.png"
    plt.savefig(scatter_path, dpi=120)
    plt.close()
    print(f"[benchmark] scatter -> {scatter_path}")


if __name__ == "__main__":
    main()
