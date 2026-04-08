#!/usr/bin/env python3
"""
benchmark_vikazimut.py — Benchmark CNN scorer vs vrais postes Vikazimut

Répond en une seule exécution (~10-15 min) à :
  - Le CNN voit-il les bons endroits ? (distance vrai→candidat CNN)
  - Les vrais postes sont-ils sur du relief intéressant ? (summit/depression/…)
  - Le CNN 5 canaux (DEM) est-il justifié ? (delta profil relief vrais vs CNN)
  - Performance variable selon le relief du terrain ? (plat / vallonné / montagneux)

Usage :
  cd backend
  python scripts/benchmark_vikazimut.py
  python scripts/benchmark_vikazimut.py --n 100 --step 30 --seed 99
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import numpy as np
from PIL import Image

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_DIR    = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


# ── Helpers géo ─────────────────────────────────────────────────────────────

def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_mpp(bounds: dict, img_w: int, img_h: int) -> float:
    lat_c = (bounds["north"] + bounds["south"]) / 2
    lng_c = (bounds["west"]  + bounds["east"])  / 2
    w_m = haversine_m(bounds["west"],  lat_c, bounds["east"], lat_c)
    h_m = haversine_m(lng_c, bounds["south"], lng_c, bounds["north"])
    return (w_m / img_w + h_m / img_h) / 2


def wgs84_to_px(lng: float, lat: float, bounds: dict,
                img_w: int, img_h: int) -> Tuple[int, int]:
    px = int((lng - bounds["west"])  / (bounds["east"]  - bounds["west"])  * img_w)
    py = int((bounds["north"] - lat) / (bounds["north"] - bounds["south"]) * img_h)
    return px, py


# ── Analyse DEM par parcours ─────────────────────────────────────────────────

class DemAnalyzer:
    """
    Construit une dalle d'élévation brute (non normalisée) via la stratégie
    'dalle globale' : 64×64 appels SRTM par parcours, puis interpolation numpy.
    """

    SAMPLE = 16  # grille SRTM (256 appels par parcours — suffisant pour relief)
    NEIGHBOR_RADIUS_DEG = 30 / 111_320  # ~30m en degrés

    def __init__(self, bbox: tuple, img_w: int, img_h: int, srtm_data) -> None:
        """bbox = (min_lng, min_lat, max_lng, max_lat)"""
        self.bbox    = bbox
        self.img_w   = img_w
        self.img_h   = img_h
        self._srtm   = srtm_data

        min_lng, min_lat, max_lng, max_lat = bbox
        lats = np.linspace(max_lat, min_lat, self.SAMPLE)
        lons = np.linspace(min_lng, max_lng, self.SAMPLE)

        # Grille brute (SAMPLE × SAMPLE), en mètres d'altitude
        self._raw = np.zeros((self.SAMPLE, self.SAMPLE), dtype=np.float32)
        for i, la in enumerate(lats):
            for j, lo in enumerate(lons):
                v = srtm_data.get_elevation(float(la), float(lo))
                self._raw[i, j] = float(v) if v else 0.0

        # Upsampler à la taille de l'image pour lookup O(1)
        self.elev_map: np.ndarray = np.array(
            Image.fromarray(self._raw).resize((img_w, img_h), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )

        # Pente en degrés
        cell_m = 111_320.0 * (max_lat - min_lat) / self.SAMPLE
        gy, gx = np.gradient(self._raw)
        slope_raw = np.degrees(np.arctan(np.sqrt(gx ** 2 + gy ** 2) / max(cell_m, 1.0)))
        self.slope_map: np.ndarray = np.array(
            Image.fromarray(slope_raw.astype(np.float32)).resize(
                (img_w, img_h), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )

        # Relief du parcours = max - min élévation
        self.relief_m: float = float(self._raw.max() - self._raw.min())

    # ── Getters pixel ────────────────────────────────────────────────────────

    def elev_at(self, px: int, py: int) -> float:
        px = max(0, min(self.img_w - 1, px))
        py = max(0, min(self.img_h - 1, py))
        return float(self.elev_map[py, px])

    def slope_at(self, px: int, py: int) -> float:
        px = max(0, min(self.img_w - 1, px))
        py = max(0, min(self.img_h - 1, py))
        return float(self.slope_map[py, px])

    def roughness_at(self, px: int, py: int, radius_px: int = 15) -> float:
        """Écart-type des altitudes dans un voisinage carré (rugosité locale)."""
        x0 = max(0, px - radius_px)
        x1 = min(self.img_w, px + radius_px)
        y0 = max(0, py - radius_px)
        y1 = min(self.img_h, py + radius_px)
        patch = self.elev_map[y0:y1, x0:x1]
        return float(patch.std()) if patch.size > 0 else 0.0

    def classify(self, px: int, py: int, radius_px: int = 15) -> str:
        """
        Classifie le terrain en 5 catégories IOF :
          summit    — plus haut que tous ses voisins
          depression — plus bas que tous ses voisins
          saddle    — col (plus haut que 2 voisins opposés, plus bas que 2 autres)
          slope     — flanc de pente (pente > 5°)
          flat      — replat
        """
        center = self.elev_at(px, py)

        # 8 voisins à distance radius_px
        offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                   (0, 1), (1, -1), (1, 0), (1, 1)]
        neighbor_vals = [
            self.elev_at(px + dx * radius_px, py + dy * radius_px)
            for dy, dx in offsets
        ]
        n_higher = sum(1 for v in neighbor_vals if v > center + 1.0)
        n_lower  = sum(1 for v in neighbor_vals if v < center - 1.0)

        if n_higher == 0 and n_lower >= 4:
            return "summit"
        if n_lower == 0 and n_higher >= 4:
            return "depression"

        # Saddle : asymétrie dans les 4 directions cardinales
        card = [
            self.elev_at(px, py - radius_px),  # N
            self.elev_at(px, py + radius_px),  # S
            self.elev_at(px - radius_px, py),  # W
            self.elev_at(px + radius_px, py),  # E
        ]
        n_above = sum(1 for v in card if v > center + 1.0)
        n_below = sum(1 for v in card if v < center - 1.0)
        if n_above == 2 and n_below == 2:
            return "saddle"

        slope = self.slope_at(px, py)
        if slope > 5.0:
            return "slope"
        return "flat"

    # ── Canaux DEM normalisés pour CNN 5ch ──────────────────────────────────

    def dem_crop(self, px: int, py: int, crop_px: int) -> Tuple[np.ndarray, np.ndarray]:
        """Retourne (elev_norm, slope_norm) en crop_px × crop_px centré sur (px,py)."""
        r = crop_px // 2
        x0, y0 = max(0, px - r), max(0, py - r)
        x1, y1 = min(self.img_w, px + r), min(self.img_h, py + r)
        e_crop = self.elev_map[y0:y1, x0:x1]
        s_crop = self.slope_map[y0:y1, x0:x1]
        # Normaliser ([0,3000]→[0,1] et [0,45]→[0,1])
        return (np.clip(e_crop / 3000.0, 0, 1),
                np.clip(s_crop / 45.0,   0, 1))


# ── Profil de relief d'un ensemble de points ────────────────────────────────

class ReliefProfile(NamedTuple):
    summit:     float  # % points
    depression: float
    saddle:     float
    slope:      float
    flat:       float
    roughness:  float  # moyenne
    slope_deg:  float  # pente moyenne (°)


def build_profile(positions: List[Tuple[int, int]], dem: DemAnalyzer) -> ReliefProfile:
    if not positions:
        return ReliefProfile(0, 0, 0, 0, 0, 0, 0)
    cats = [dem.classify(px, py) for px, py in positions]
    n = len(cats)
    roughness = float(np.mean([dem.roughness_at(px, py) for px, py in positions]))
    slope_avg = float(np.mean([dem.slope_at(px, py)    for px, py in positions]))
    return ReliefProfile(
        summit     = cats.count("summit")     / n * 100,
        depression = cats.count("depression") / n * 100,
        saddle     = cats.count("saddle")     / n * 100,
        slope      = cats.count("slope")      / n * 100,
        flat       = cats.count("flat")       / n * 100,
        roughness  = roughness,
        slope_deg  = slope_avg,
    )


# ── Sélection des circuits ───────────────────────────────────────────────────

def select_courses(index_path: Path, n: int, seed: int) -> List[dict]:
    with open(index_path, encoding="utf-8") as f:
        all_courses = json.load(f)

    usable = [
        c for c in all_courses
        if c.get("is_foot_o")
        and c.get("map_jpg") and Path(c["map_jpg"]).exists()
        and c.get("bounds")
        and abs(c["bounds"].get("rotation", 0)) <= 0.15   # < ~9°
        and sum(1 for x in c.get("controls", []) if x.get("type") == "Control") >= 8
    ]

    sprint = [c for c in usable if c.get("discipline") in ("urbano", "sprint")]
    forest = [c for c in usable if c.get("discipline") in ("foresto", "")]
    rng    = random.Random(seed)
    n_each = n // 2
    sel = (rng.sample(sprint, min(n_each, len(sprint)))
           + rng.sample(forest, min(n - min(n_each, len(sprint)), len(forest))))

    print(f"Pool : {len(usable)} circuits usables ({len(sprint)} sprint, {len(forest)} forêt)")
    print(f"Échantillon : {len(sel)} circuits\n")
    return sel


# ── Catégorie de relief du parcours ─────────────────────────────────────────

def relief_category(relief_m: float) -> str:
    if relief_m < 30:
        return "plat"
    if relief_m < 100:
        return "vallonné"
    return "montagneux"


# ── Benchmark principal ──────────────────────────────────────────────────────

def run_benchmark(n: int = 50, seed: int = 42, step_px: int = 20, use_dem: bool = False) -> None:
    t0 = time.time()

    index_path = REPO_DIR / "vikazimut" / "index.json"
    if not index_path.exists():
        print(f"ERREUR : {index_path} introuvable")
        sys.exit(1)

    # ── Chargement CNN ───────────────────────────────────────────────────────
    print("Chargement CnnPatchScorer…")
    from src.services.learning.ocad_patch_scorer import CnnPatchScorer, _build_dem_tiles
    cnn = CnnPatchScorer.load(base_dir=BACKEND_DIR)
    if cnn is None:
        print("ERREUR : CnnPatchScorer non disponible")
        sys.exit(1)
    mode = f"{cnn._in_channels}ch"
    print(f"  Modèle chargé ({mode})\n")

    # ── Chargement SRTM (opt-in via --dem pour éviter blocage téléchargement HGT)
    srtm_data = None
    if use_dem:
        try:
            import srtm as _srtm
            import tempfile
            _cache = os.path.join(tempfile.gettempdir(), "srtm_cache")
            os.makedirs(_cache, exist_ok=True)
            srtm_data = _srtm.get_data()
            print("SRTM chargé (DEM actif)")
        except Exception as e:
            print(f"SRTM non disponible ({e}) — analyse relief désactivée")
    else:
        print("DEM désactivé (--dem pour activer l'analyse relief SRTM)")

    courses = select_courses(index_path, n=n, seed=seed)

    # ── Structures de résultats ──────────────────────────────────────────────
    results = []

    for i, course in enumerate(courses):
        cid    = course["id"]
        disc   = course.get("discipline") or "?"
        bounds = course["bounds"]
        bbox   = (bounds["west"], bounds["south"], bounds["east"], bounds["north"])
        real_controls = [c for c in course.get("controls", [])
                         if c.get("type") == "Control"]
        K = len(real_controls)

        print(f"[{i+1:02d}/{len(courses)}] #{cid} {disc:8s} K={K:2d}", end="  ", flush=True)

        try:
            map_img = Image.open(course["map_jpg"]).convert("RGB")
        except Exception as e:
            print(f"SKIP JPG : {e}")
            continue

        img_w, img_h = map_img.size
        mpp = compute_mpp(bounds, img_w, img_h)

        # ── DEM pour ce parcours (timeout 15s pour éviter blocage téléchargement HGT)
        dem: Optional[DemAnalyzer] = None
        if srtm_data is not None:
            def _build_dem():
                return DemAnalyzer(bbox, img_w, img_h, srtm_data)
            try:
                with ThreadPoolExecutor(max_workers=1) as _pool:
                    _fut = _pool.submit(_build_dem)
                    dem = _fut.result(timeout=15)
            except FuturesTimeoutError:
                print("(DEM timeout)", end="  ")
            except Exception as e:
                print(f"(DEM fail: {e})", end="  ")

        # ── Grille CNN ───────────────────────────────────────────────────────
        t_cnn = time.time()
        xs = range(0, img_w, step_px)
        ys = range(0, img_h, step_px)
        crop_px = max(1, int(CnnPatchScorer._FOV_M / mpp))

        # 1. Construire coords d'abord (rapide — pas de PIL)
        all_coords = [
            (bounds["west"]  + (px_g / img_w) * (bounds["east"]  - bounds["west"]),
             bounds["north"] - (py_g / img_h) * (bounds["north"] - bounds["south"]),
             px_g, py_g)
            for py_g in ys for px_g in xs
        ]

        # 2. Sous-échantillonner AVANT de cropper (évite PIL sur toute l'image)
        MAX_PATCHES = 2000
        if len(all_coords) > MAX_PATCHES:
            all_coords = random.sample(all_coords, MAX_PATCHES)

        # 3. Cropper seulement les positions sélectionnées
        patches = []
        coords  = []
        for lng, lat, px_g, py_g in all_coords:
            patch = CnnPatchScorer.crop_patch(map_img, px_g, py_g, mpp)
            if dem is not None and cnn._in_channels == 5:
                e_crop, s_crop = dem.dem_crop(px_g, py_g, crop_px)
                patches.append((patch, e_crop, s_crop))
            else:
                patches.append(patch)
            coords.append((lng, lat, px_g, py_g))

        print(f"patches={len(patches)}", end="  ", flush=True)
        try:
            scores = cnn.score_batch(patches)
        except Exception as e:
            print(f"SKIP score_batch : {e}")
            continue

        t_cnn = time.time() - t_cnn
        print(f"CNN={t_cnn:.1f}s", end="  ", flush=True)

        # ── Top-K CNN ────────────────────────────────────────────────────────
        grid = [(float(s), lng, lat, px_g, py_g)
                for s, (lng, lat, px_g, py_g) in zip(scores, coords)]
        grid.sort(reverse=True)
        top_k = [(lng, lat, px_g, py_g) for _, lng, lat, px_g, py_g in grid[:K]]

        # ── Positions pixel des vrais contrôles ─────────────────────────────
        real_px = []
        for ctrl in real_controls:
            px_c, py_c = wgs84_to_px(ctrl["lng"], ctrl["lat"], bounds, img_w, img_h)
            real_px.append((px_c, py_c))

        # ── Distance vrai→Top-K CNN ──────────────────────────────────────────
        distances = []
        matched_50 = matched_100 = 0
        for ctrl, (px_c, py_c) in zip(real_controls, real_px):
            min_d = min(haversine_m(ctrl["lng"], ctrl["lat"], lng, lat)
                        for lng, lat, *_ in top_k)
            distances.append(min_d)
            matched_50  += min_d <= 50
            matched_100 += min_d <= 100

        avg_d   = float(np.mean(distances))
        pct_50  = matched_50  / K * 100
        pct_100 = matched_100 / K * 100

        # Score CNN médian aux vraies positions
        true_scores = [float(scores[i_g])
                       for i_g, (_, _, px_g, py_g) in enumerate(coords)
                       if any(abs(px_g - px_c) <= step_px and abs(py_g - py_c) <= step_px
                              for px_c, py_c in real_px)]
        median_score = float(np.median(true_scores)) if true_scores else float("nan")

        # ── Profils relief ───────────────────────────────────────────────────
        relief_cat = "n/a"
        prof_real  = None
        prof_cnn   = None

        if dem is not None:
            relief_cat = relief_category(dem.relief_m)
            cnn_px = [(px_g, py_g) for _, _, px_g, py_g in top_k]
            prof_real = build_profile(real_px, dem)
            prof_cnn  = build_profile(cnn_px, dem)

        print(f"avg={avg_d:5.0f}m  @50m={pct_50:4.0f}%  score={median_score:.3f}"
              f"  relief={relief_cat}  [{t_cnn:.1f}s]")

        results.append({
            "id": cid, "discipline": disc, "K": K,
            "avg_dist_m": avg_d, "pct_50": pct_50, "pct_100": pct_100,
            "median_score": median_score,
            "relief_cat": relief_cat,
            "dem_relief_m": dem.relief_m if dem else None,
            "prof_real": prof_real,
            "prof_cnn":  prof_cnn,
        })

    # ── Rapport ──────────────────────────────────────────────────────────────
    total_t = time.time() - t0
    if not results:
        print("Aucun résultat.")
        return

    def mean_r(key):
        vals = [r[key] for r in results
                if r[key] is not None
                and not (isinstance(r[key], float) and math.isnan(r[key]))
                and (key != "avg_dist_m" or r[key] < 500)]  # filtrer distances aberrantes
        return float(np.mean(vals)) if vals else float("nan")

    print()
    print("=" * 65)
    print(f"=== BENCHMARK VIKAZIMUT ({len(results)} parcours, mode={mode}) ===")
    print("=" * 65)

    # ── Vision CNN ───────────────────────────────────────────────────────────
    print("\n--- Vision CNN ---")
    print(f"Distance moyenne vrai→candidat     : {mean_r('avg_dist_m'):.1f} m")
    print(f"Vrais contrôles avec candidat ≤50m : {mean_r('pct_50'):.1f}%")
    print(f"Vrais contrôles avec candidat ≤100m: {mean_r('pct_100'):.1f}%")
    print(f"Score CNN médian aux vraies pos.   : {mean_r('median_score'):.3f}")

    # ── Profil relief ────────────────────────────────────────────────────────
    real_profs = [r["prof_real"] for r in results if r["prof_real"] is not None]
    cnn_profs  = [r["prof_cnn"]  for r in results if r["prof_cnn"]  is not None]

    if real_profs:
        def avg_p(profs, attr):
            return float(np.mean([getattr(p, attr) for p in profs]))

        print("\n--- Profil Relief (vrais postes vs candidats CNN) ---")
        print(f"{'':16s}  {'Vrais':>8s}  {'CNN':>8s}  {'Delta':>8s}")
        for cat in ("summit", "depression", "saddle", "slope", "flat"):
            v = avg_p(real_profs, cat)
            c = avg_p(cnn_profs,  cat)
            print(f"  {cat:14s}  {v:7.1f}%  {c:7.1f}%  {v-c:+7.1f}%")
        print(f"  {'Rugosité moy.':14s}  {avg_p(real_profs,'roughness'):8.1f}  "
              f"{avg_p(cnn_profs,'roughness'):8.1f}")
        print(f"  {'Pente moy.':14s}  {avg_p(real_profs,'slope_deg'):7.1f}°  "
              f"{avg_p(cnn_profs,'slope_deg'):7.1f}°")

        # Verdict CNN 5 canaux
        delta_terrain = (
            (avg_p(real_profs, "summit") - avg_p(cnn_profs, "summit"))
            + (avg_p(real_profs, "depression") - avg_p(cnn_profs, "depression"))
        )
        justified = abs(delta_terrain) > 10.0
    else:
        delta_terrain = float("nan")
        justified = False
        print("\n(analyse relief non disponible — SRTM absent)")

    # ── Ventilation par catégorie de relief ──────────────────────────────────
    print("\n--- Ventilation par relief ---")
    print(f"{'':14s}  {'Plat':>10s}  {'Vallonné':>10s}  {'Montagneux':>10s}")

    for metric, label in [("avg_dist_m", "Dist. moy.(m)"),
                           ("pct_50",    "CNN <50m (%)"),
                           ("pct_100",   "CNN <100m(%)")]:
        row = ""
        for cat in ("plat", "vallonné", "montagneux"):
            sub = [r[metric] for r in results
                   if r["relief_cat"] == cat and r[metric] is not None]
            row += f"  {np.mean(sub):9.1f}" if sub else f"  {'n/a':>9s}"
        print(f"  {label:14s}{row}")

    if real_profs:
        # Summit % par catégorie
        row = ""
        for cat in ("plat", "vallonné", "montagneux"):
            sub = [r["prof_real"].summit for r in results
                   if r["relief_cat"] == cat and r["prof_real"] is not None]
            row += f"  {np.mean(sub):8.1f}%" if sub else f"  {'n/a':>9s}"
        print(f"  {'Summit%':14s}{row}")

    # ── Verdicts ─────────────────────────────────────────────────────────────
    print("\n--- Verdict ---")
    avg_global = mean_r("avg_dist_m")
    if avg_global < 50:
        cnn_verdict = "Excellent — CNN voit très bien les postes"
    elif avg_global < 100:
        cnn_verdict = "Bon — quelques ajustements suffisent"
    elif avg_global < 200:
        cnn_verdict = "Moyen — CNN partiel, GA compense"
    else:
        cnn_verdict = "Insuffisant — revoir architecture ou données"
    print(f"  CNN vision    : {avg_global:.0f}m avg → {cnn_verdict}")

    sc = mean_r("median_score")
    if sc > 0.60:
        sc_verdict = "threshold 0.5 bien calibré"
    elif sc > 0.45:
        sc_verdict = "threshold à baisser vers 0.40–0.45"
    else:
        sc_verdict = "CNN sous-évalue les vraies positions"
    print(f"  Threshold     : médiane={sc:.3f} → {sc_verdict}")

    if not math.isnan(delta_terrain):
        print(f"  CNN 5 canaux  : delta summit+depression={delta_terrain:+.1f}% → "
              f"{'JUSTIFIÉ ✓' if justified else 'non prioritaire (delta < 10%)'}")

    # Counts par catégorie
    cats = {c: sum(1 for r in results if r["relief_cat"] == c)
            for c in ("plat", "vallonné", "montagneux", "n/a")}
    print(f"  Répartition   : {cats}")

    print(f"\nTemps total : {total_t:.0f}s ({total_t/len(results):.1f}s/circuit)")


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Benchmark CNN vs vrais postes Vikazimut")
    p.add_argument("--n",    type=int, default=50, help="Nombre de circuits (défaut: 50)")
    p.add_argument("--step", type=int, default=64, help="Pas grille pixels  (défaut: 64)")
    p.add_argument("--seed", type=int, default=42, help="Seed aléatoire     (défaut: 42)")
    p.add_argument("--dem",  action="store_true",  help="Activer analyse relief SRTM (télécharge les tuiles HGT)")
    args = p.parse_args()
    run_benchmark(n=args.n, step_px=args.step, seed=args.seed, use_dem=args.dem)
