"""
atlas_generation.py — Campagne de génération empirique (Atlas).

Génère N_RUNS × Top-10 circuits sur 20-50 cartes Vikazimut (OSM-only).
Répond à la question centrale :
    "Une même carte produit-elle naturellement plusieurs familles de parcours ?"

Usage :
    cd backend
    python scripts/atlas_generation.py [--max-bboxes 30] [--n-runs 10] [--top-n 10]

Output :
    output/atlas/atlas_results.csv   — une ligne par circuit
    output/atlas/atlas_maps.json     — stats agrégées par carte (intra/inter-run distance)
"""
import sys
import os
import json
import csv
import math
import hashlib
import pathlib
import tempfile
import argparse
import time
import logging
from dataclasses import asdict
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np

log = logging.getLogger("atlas")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Chemins ────────────────────────────────────────────────────────────────────
_BACKEND_DIR = pathlib.Path(__file__).parent.parent
_VIKAZIMUT_INDEX = _BACKEND_DIR.parent / "vikazimut" / "index.json"
_OUTPUT_DIR = _BACKEND_DIR.parent / "output" / "atlas"

# ── Paramètres par défaut ──────────────────────────────────────────────────────
DEFAULT_MAX_BBOXES = 30
DEFAULT_N_RUNS = 10
DEFAULT_TOP_N = 10
MIN_AREA_KM2 = 0.05
MAX_AREA_KM2 = 3.0
MIN_DEDUP_DIST_KM = 5.0


# ── Haversine ─────────────────────────────────────────────────────────────────

def _haversine_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Distance Haversine en mètres entre (lng1, lat1) et (lng2, lat2)."""
    R = 6_371_000.0
    lng1, lat1 = p1
    lng2, lat2 = p2
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _legs_m(controls: list) -> np.ndarray:
    """Distances des jambes en mètres depuis une liste de (lng, lat)."""
    return np.array([_haversine_m(controls[i], controls[i + 1]) for i in range(len(controls) - 1)], dtype=float)


# ── Sélection des bboxes Vikazimut ───────────────────────────────────────────

def load_vikazimut_bboxes(max_bboxes: int) -> List[Dict]:
    """
    Charge et filtre les bboxes depuis vikazimut/index.json.
    Filtre : foot-O, ≥8 contrôles, aire 0.05-3 km², déduplication géographique.
    """
    raw = json.loads(_VIKAZIMUT_INDEX.read_text("utf-8"))
    candidates = []
    for entry in raw:
        if not entry.get("is_foot_o"):
            continue
        if entry.get("n_controls", 0) < 8:
            continue
        bounds = entry.get("bounds")
        if not bounds:
            continue
        n = bounds.get("north")
        s = bounds.get("south")
        east = bounds.get("east")
        w = bounds.get("west")
        if None in (n, s, east, w) or east == w or n == s:
            continue
        mid_lat = (n + s) / 2.0
        area_km2 = (east - w) * math.cos(math.radians(mid_lat)) * 111_320.0 * (n - s) * 111_320.0 / 1e6
        if not (MIN_AREA_KM2 <= area_km2 <= MAX_AREA_KM2):
            continue
        candidates.append({
            "id": entry["id"],
            "discipline": entry.get("discipline", ""),
            "n_controls": entry.get("n_controls", 0),
            "area_km2": round(area_km2, 3),
            "min_lng": w, "min_lat": s, "max_lng": east, "max_lat": n,
        })

    # Déduplication géographique (distance min 5 km)
    selected = []
    for b in candidates:
        if len(selected) >= max_bboxes:
            break
        cx = (b["min_lng"] + b["max_lng"]) / 2.0
        cy = (b["min_lat"] + b["max_lat"]) / 2.0
        lng_scale = math.cos(math.radians(cy)) * 111.32
        too_close = any(
            math.sqrt(((cx - (s["min_lng"] + s["max_lng"]) / 2) * lng_scale) ** 2 +
                      ((cy - (s["min_lat"] + s["max_lat"]) / 2) * 111.32) ** 2) < MIN_DEDUP_DIST_KM
            for s in selected
        )
        if not too_close:
            selected.append(b)

    log.info("Bboxes sélectionnées : %d / %d candidats", len(selected), len(candidates))
    return selected


# ── Construction des caches ───────────────────────────────────────────────────

def _fetch_mapant_image(bb_dict: dict, zoom: int = 15):
    """Assemble une image PIL depuis les tuiles MapAnt. Retourne (img, bbox_wgs84, mpp) ou None."""
    try:
        import io
        from PIL import Image as _PILImage
        from src.services.terrain.mapant_fetcher import (
            MapantFetcher, lat_lon_to_tile, tile_to_lat_lon, meters_per_pixel,
        )
        min_x = bb_dict["min_x"]
        min_y = bb_dict["min_y"]
        max_x = bb_dict["max_x"]
        max_y = bb_dict["max_y"]
        tx_min, ty_max = lat_lon_to_tile(min_y, min_x, zoom)
        tx_max, ty_min = lat_lon_to_tile(max_y, max_x, zoom)
        if (tx_max - tx_min + 1) * (ty_max - ty_min + 1) > 256:
            return None
        fetcher = MapantFetcher(zoom=zoom, use_cache=True)
        TILE_PX = 256
        n_cols = tx_max - tx_min + 1
        n_rows = ty_max - ty_min + 1
        canvas = _PILImage.new("RGB", (n_cols * TILE_PX, n_rows * TILE_PX), (255, 255, 255))
        for row, ty in enumerate(range(ty_min, ty_max + 1)):
            for col, tx in enumerate(range(tx_min, tx_max + 1)):
                tile_bytes = fetcher.fetch_tile(tx, ty, z=zoom)
                if tile_bytes:
                    canvas.paste(_PILImage.open(io.BytesIO(tile_bytes)).convert("RGB"), (col * TILE_PX, row * TILE_PX))
        lat_nw, lng_nw = tile_to_lat_lon(tx_min, ty_min, zoom)
        lat_se, lng_se = tile_to_lat_lon(tx_max + 1, ty_max + 1, zoom)
        bbox_wgs84 = (lng_nw, lat_se, lng_se, lat_nw)
        mpp = meters_per_pixel((min_y + max_y) / 2, zoom)
        return canvas, bbox_wgs84, mpp
    except Exception as exc:
        log.debug("MapAnt fetch failed: %s", exc)
        return None


def build_caches(bb_dict: dict, bbox_tuple: tuple) -> dict:
    """
    Construit HeatmapCache, ElevationCache, RouteAnalyzer pour une bbox.
    Retourne un dict avec les clés : heatmap_cache, elevation_cache, route_analyzer.
    """
    from src.services.terrain.osm_fetcher import extract_sprint_features
    from src.services.optimization.route_analyzer import RouteAnalyzer
    from src.services.terrain.lidar_manager import build_elevation_cache
    from src.services.learning.ocad_patch_scorer import HeatmapCache

    # OSM (disk-cached automatiquement par extract_sprint_features)
    t0 = time.perf_counter()
    osm = extract_sprint_features(bb_dict)
    ra = RouteAnalyzer(osm.get("highway_ways", []))
    log.info("  OSM + RouteAnalyzer: %.2fs (%d ways, %d nodes)", time.perf_counter() - t0, len(osm.get("highway_ways", [])), ra.node_count)

    # ElevationCache (disk-cached dans lidar_manager)
    t0 = time.perf_counter()
    ec = build_elevation_cache(bb_dict)
    log.info("  ElevationCache: %.2fs (%s)", time.perf_counter() - t0, "hit" if ec else "None")

    # HeatmapCache — disk cache via clé bbox
    hmc = None
    step_px = 20
    _key = hashlib.md5(f"atlas|{bbox_tuple}|{step_px}|cnn".encode()).hexdigest()[:12]
    _hmc_path = pathlib.Path(tempfile.gettempdir()) / f"aitraceur_hmc_{_key}"
    _hmc_npz = _hmc_path.with_suffix(".npz")

    if _hmc_npz.exists():
        t0 = time.perf_counter()
        hmc = HeatmapCache.load(_hmc_path)
        log.info("  HeatmapCache: %.2fs (disk hit)", time.perf_counter() - t0)
    else:
        t0 = time.perf_counter()
        result = _fetch_mapant_image(bb_dict)
        if result is not None:
            img, bbox_img, mpp = result
            try:
                from src.services.learning.ocad_patch_scorer import CnnPatchScorer
                cnn = CnnPatchScorer.load()
            except Exception:
                cnn = None
            hmc = HeatmapCache.build_from_image(img, bbox=bbox_img, mpp=mpp, step_px=step_px, cnn_scorer=cnn)
            hmc.save(_hmc_path)
            log.info("  HeatmapCache: %.2fs (built from MapAnt)", time.perf_counter() - t0)
        else:
            log.warning("  HeatmapCache: MapAnt indisponible → None")

    return {"heatmap_cache": hmc, "elevation_cache": ec, "route_analyzer": ra}


# ── Métriques dérivées ────────────────────────────────────────────────────────

def variety_score_from_controls(controls: list, hmc) -> Optional[float]:
    """Std des scores CNN aux milieux de jambes, normalisé (même que terme N fitness)."""
    if hmc is None or len(controls) < 2:
        return None
    scores = [hmc.query((controls[i][0] + controls[i + 1][0]) / 2.0,
                        (controls[i][1] + controls[i + 1][1]) / 2.0)
              for i in range(len(controls) - 1)]
    return float(np.std(scores))


def pairwise_mean_cosine(vectors: List[np.ndarray]) -> float:
    """Distance cosinus moyenne entre toutes les paires de vecteurs."""
    from src.services.generation.profiling.profile_distance import cosine_distance
    if len(vectors) < 2:
        return 0.0
    dists = [cosine_distance(vectors[i], vectors[j])
             for i in range(len(vectors))
             for j in range(i + 1, len(vectors))]
    return float(np.mean(dists)) if dists else 0.0


# ── Clustering K-Means ────────────────────────────────────────────────────────

def assign_family_ids(rows: List[dict], k: int = 4) -> None:
    """Assigne family_id à chaque ligne par K-Means sur les vecteurs profil."""
    try:
        from sklearn.cluster import KMeans
        from sklearn.impute import SimpleImputer

        vectors = [np.array(r["_profile_vector"], dtype=float) for r in rows]
        X = np.vstack(vectors)
        # Imputer NaN à la médiane avant K-Means
        imp = SimpleImputer(strategy="median")
        X_imp = imp.fit_transform(X)
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(X_imp)
        for row, label in zip(rows, labels):
            row["family_id"] = int(label)
    except Exception as exc:
        log.warning("K-Means clustering échoué : %s", exc)
        for row in rows:
            row["family_id"] = None


# ── Pipeline principal ────────────────────────────────────────────────────────

def run_atlas(max_bboxes: int, n_runs: int, top_n: int, k_clusters: int = 4) -> None:
    from src.services.generation.genetic_algo import GeneticAlgorithm, GenerationConfig
    from src.services.generation.profiling import (
        compute_course_profile, compute_map_profile, compute_exploitation_profile,
    )
    from src.services.generation.profiling.profile_distance import course_profile_vector, cosine_distance

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bboxes = load_vikazimut_bboxes(max_bboxes)

    all_rows: List[dict] = []
    map_stats: Dict[str, dict] = {}

    for bi, bbox_info in enumerate(bboxes):
        bbox_id = str(bbox_info["id"])
        log.info("\n[%d/%d] bbox %s  %.2f km²", bi + 1, len(bboxes), bbox_id, bbox_info["area_km2"])

        bb_dict = {
            "min_x": bbox_info["min_lng"], "min_y": bbox_info["min_lat"],
            "max_x": bbox_info["max_lng"], "max_y": bbox_info["max_lat"],
        }
        bbox_tuple = (bbox_info["min_lng"], bbox_info["min_lat"], bbox_info["max_lng"], bbox_info["max_lat"])

        try:
            caches = build_caches(bb_dict, bbox_tuple)
        except Exception as exc:
            log.warning("  SKIP bbox %s : %s", bbox_id, exc)
            continue

        hmc = caches["heatmap_cache"]
        ec = caches["elevation_cache"]
        ra = caches["route_analyzer"]

        # MapProfile (une fois par carte)
        mp = compute_map_profile(bbox_tuple, hmc, ec, ra)

        config = GenerationConfig(
            circuit_type="sprint",
            bounding_box={"min_x": bbox_info["min_lng"], "min_y": bbox_info["min_lat"],
                          "max_x": bbox_info["max_lng"], "max_y": bbox_info["max_lat"]},
            target_length_m=2200,
            target_controls=12,
            winning_time_min=12,
            technical_level=3,
            heatmap_cache=hmc,
            elevation_cache=ec,
            route_analyzer=ra,
            population_size=50,
            generations=80,
            timeout_seconds=60.0,
        )

        cx = (bbox_tuple[0] + bbox_tuple[2]) / 2.0
        cy = (bbox_tuple[1] + bbox_tuple[3]) / 2.0
        dx = (bbox_tuple[2] - bbox_tuple[0]) * 0.20
        start = (cx - dx, cy)
        end = (cx + dx, cy)

        run_centroids: List[np.ndarray] = []
        run_intra_dists: List[float] = []

        for run_idx in range(n_runs):
            t0 = time.perf_counter()
            try:
                ga = GeneticAlgorithm(config)
                result = ga.generate(start, end)
            except Exception as exc:
                log.warning("  run %d FAILED: %s", run_idx, exc)
                continue

            circuits = result.circuits[:top_n]
            run_vectors: List[np.ndarray] = []

            for rank, circuit in enumerate(circuits):
                controls = circuit.controls
                if len(controls) < 3:
                    continue
                legs = _legs_m(controls)
                try:
                    cp = compute_course_profile(controls, legs, bbox_tuple, hmc, ec, ra)
                    ep = compute_exploitation_profile(cp, mp, controls, legs, ec)
                except Exception as exc:
                    log.warning("  profile failed rank=%d: %s", rank, exc)
                    continue

                vec = course_profile_vector(cp)
                variety = variety_score_from_controls(controls, hmc)

                row = {
                    "bbox_id": bbox_id,
                    "run_id": run_idx,
                    "rank_in_run": rank,
                    "fitness": round(float(circuit.fitness), 4),
                    "has_heatmap": hmc is not None,
                    "has_elevation": ec is not None,
                    # Profil parcours
                    "map_coverage": cp.map_coverage,
                    "zone_balance": cp.zone_balance,
                    "variety_score": round(variety, 4) if variety is not None else None,
                    "alternation": cp.alternation,
                    "route_choice_density": cp.route_choice_density,
                    "narrative_shape": cp.narrative_shape,
                    "transition_count": cp.transition_count,
                    "transition_strength": cp.transition_strength,
                    # ExploitationProfile
                    "relief_ratio": ep.relief_used_ratio,
                    "route_choice_ratio": ep.route_choice_used_ratio,
                    "speed_ratio": ep.speed_used_ratio,
                    # MapProfile (identique par carte)
                    "map_speed_potential": mp.speed_potential,
                    "map_route_choice_potential": mp.route_choice_potential,
                    "map_micro_relief": mp.micro_relief_potential,
                    "navigation_complexity": mp.navigation_complexity,   # None si OSM
                    "visibility_complexity": mp.visibility_complexity,   # None si OSM
                    # Clustering (post)
                    "family_id": None,
                    "_profile_vector": vec.tolist(),
                }
                all_rows.append(row)
                run_vectors.append(vec)

            elapsed = time.perf_counter() - t0
            log.info("  run %2d: %d circuits en %.2fs", run_idx, len(circuits), elapsed)

            if run_vectors:
                run_intra_dists.append(pairwise_mean_cosine(run_vectors))
                run_centroids.append(np.nanmean(run_vectors, axis=0))

        # Stats par carte
        inter_run_dist = (
            pairwise_mean_cosine(run_centroids) if len(run_centroids) > 1 else 0.0
        )
        narrative_shapes = [r["narrative_shape"] for r in all_rows if r["bbox_id"] == bbox_id]
        shape_dist = {}
        for s in narrative_shapes:
            shape_dist[s] = shape_dist.get(s, 0) + 1

        map_stats[bbox_id] = {
            "bbox_id": bbox_id,
            "area_km2": bbox_info["area_km2"],
            "discipline": bbox_info["discipline"],
            "n_controls_ref": bbox_info["n_controls"],
            "runs_completed": len(run_intra_dists),
            "mean_intra_top10_dist": round(float(np.mean(run_intra_dists)), 4) if run_intra_dists else None,
            "std_intra_top10_dist": round(float(np.std(run_intra_dists)), 4) if run_intra_dists else None,
            "mean_interrun_dist": round(inter_run_dist, 4),
            "mean_map_coverage": round(float(np.mean([r["map_coverage"] for r in all_rows if r["bbox_id"] == bbox_id])), 4) if all_rows else None,
            "mean_zone_balance": round(float(np.mean([r["zone_balance"] for r in all_rows if r["bbox_id"] == bbox_id])), 4) if all_rows else None,
            "narrative_shape_dist": shape_dist,
            "map_speed_potential": mp.speed_potential,
            "map_route_choice_potential": mp.route_choice_potential,
            "map_micro_relief": mp.micro_relief_potential,
        }
        log.info("  → intra=%.3f inter=%.3f  shapes=%s",
                 map_stats[bbox_id].get("mean_intra_top10_dist") or 0,
                 inter_run_dist,
                 shape_dist)

    # K-Means clustering
    log.info("\nClustering K-Means k=%d sur %d circuits...", k_clusters, len(all_rows))
    assign_family_ids(all_rows, k=k_clusters)

    # CSV
    csv_path = _OUTPUT_DIR / "atlas_results.csv"
    _CSV_COLS = [
        "bbox_id", "run_id", "rank_in_run", "fitness",
        "has_heatmap", "has_elevation",
        "map_coverage", "zone_balance", "variety_score", "alternation", "route_choice_density",
        "narrative_shape", "transition_count", "transition_strength",
        "relief_ratio", "route_choice_ratio", "speed_ratio",
        "map_speed_potential", "map_route_choice_potential", "map_micro_relief",
        "navigation_complexity", "visibility_complexity",
        "family_id",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)
    log.info("CSV : %s (%d lignes)", csv_path, len(all_rows))

    # Vecteurs profil (npy)
    if all_rows:
        npy_path = _OUTPUT_DIR / "atlas_profiles.npy"
        np.save(str(npy_path), np.array([r["_profile_vector"] for r in all_rows], dtype=np.float32))
        log.info("Profils : %s", npy_path)

    # JSON stats par carte
    json_path = _OUTPUT_DIR / "atlas_maps.json"
    json_path.write_text(json.dumps(list(map_stats.values()), indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Maps stats : %s", json_path)

    # Résumé final
    log.info("\n=== Atlas terminé ===")
    log.info("Cartes : %d  Runs : %d  Circuits : %d", len(map_stats), len(all_rows) // max(top_n, 1), len(all_rows))
    if all_rows:
        families = [r["family_id"] for r in all_rows if r["family_id"] is not None]
        if families:
            from collections import Counter
            log.info("Familles : %s", dict(Counter(families)))


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Atlas — batch generation pour validation empirique")
    parser.add_argument("--max-bboxes", type=int, default=DEFAULT_MAX_BBOXES, help="Nombre max de cartes")
    parser.add_argument("--n-runs", type=int, default=DEFAULT_N_RUNS, help="Runs GA par carte")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Top-N circuits par run")
    parser.add_argument("--k-clusters", type=int, default=4, help="Nombre de familles K-Means")
    args = parser.parse_args()

    log.info("Atlas : max_bboxes=%d n_runs=%d top_n=%d k=%d",
             args.max_bboxes, args.n_runs, args.top_n, args.k_clusters)
    run_atlas(args.max_bboxes, args.n_runs, args.top_n, args.k_clusters)


if __name__ == "__main__":
    main()
