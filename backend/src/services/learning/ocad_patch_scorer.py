"""
OcadPatchScorer — Terrain quality scorer (visual model v2).

Charge le modèle XGBoost patch_scorer_v2.pkl (17 features visuelles).
Deux modes d'inférence :
  1. Image rasterisée (nouveau, recommandé) :
       score_patch(img)                  — score un patch PIL 256×256
       score_map_image(map_img, cands)   — fenêtre glissante sur carte complète
  2. Vecteur OSM (legacy, déprécié) :
       score_position(x, y, cand_pts)   — 7-dim via candidate_points OSM
       score_circuit(controls, cand_pts) — score moyen d'un circuit

Métriques modèle patch_scorer_v2.pkl (XGBoost, 12 368 patches, multi-clubs UK RG2) :
  AUC-ROC = 0.835  |  F1 = 0.678  |  Recall = 0.746
  Top features : ctr_white > ctr_yellow > ctr_green_dense > corner_density > brown_relief

Usage (mode image) :
    scorer = OcadPatchScorer.load()
    if scorer:
        results = scorer.score_map_image(map_img, candidates, mpp=0.5)
        # results = [{"px": 120, "py": 80, "score": 0.72}, ...]
"""
from __future__ import annotations

import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

from .patch_feature_extractor import extract_features

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HeatmapCache — grille précomputée de scores V2 pour lookups O(1) par le GA
# ---------------------------------------------------------------------------
@dataclass
class HeatmapCache:
    """
    Grille 2D de scores XGBoost V2 précomputée sur la carte entière.

    Permet au GA d'évaluer la qualité terrain de n'importe quelle position WGS84
    en O(1) via interpolation bilinéaire, sans inférence XGBoost à chaque fitness.

    Attributes:
        scores:   (H_grid, W_grid) float32 — scores [0, 1] sur grille régulière.
        bbox:     (min_lng, min_lat, max_lng, max_lat) WGS84.
        step_px:  Pas de la grille en pixels image source.
        map_w:    Largeur de l'image source en pixels.
        map_h:    Hauteur de l'image source en pixels.
    """

    scores: np.ndarray   # (H_grid, W_grid) float32
    bbox: tuple          # (min_lng, min_lat, max_lng, max_lat)
    step_px: int
    map_w: int
    map_h: int
    forbidden_mask: Optional[np.ndarray] = None  # (H_img, W_img) bool — zones interdites dilatées
    scores_std: float = 0.0      # écart-type de la grille — 0 si non calculé
    is_flat_signal: bool = False  # True si std < 0.05 (CNN non-informatif, fallback ISOM en GA)
    zone_labels: Optional[np.ndarray] = None  # (H_grid, W_grid) uint8 — 0/1/2 (pauvre/modérée/riche)
    n_zones: int = 0  # 0=non initialisé, 1=signal plat (fallback neutre), 3=segmentation active

    def query(self, lng: float, lat: float) -> float:
        """
        Score interpolé bilinéairement pour une position WGS84.

        Args:
            lng: Longitude WGS84.
            lat: Latitude WGS84.

        Returns:
            Score [0, 1]. Retourne 0.45 (neutre) si hors bbox.
        """
        min_lng, min_lat, max_lng, max_lat = self.bbox
        if max_lng == min_lng or max_lat == min_lat:
            return 0.45
        tx = (lng - min_lng) / (max_lng - min_lng)
        ty = 1.0 - (lat - min_lat) / (max_lat - min_lat)  # y inversé (image)
        H, W = self.scores.shape
        # Coordonnées grille flottantes
        gx = tx * (self.map_w / self.step_px)
        gy = ty * (self.map_h / self.step_px)
        # Clamp aux bords
        x0 = max(0, min(int(gx), W - 1))
        y0 = max(0, min(int(gy), H - 1))
        x1 = min(x0 + 1, W - 1)
        y1 = min(y0 + 1, H - 1)
        fx = gx - int(gx)
        fy = gy - int(gy)
        return float(
            self.scores[y0, x0] * (1 - fx) * (1 - fy)
            + self.scores[y0, x1] * fx * (1 - fy)
            + self.scores[y1, x0] * (1 - fx) * fy
            + self.scores[y1, x1] * fx * fy
        )

    def is_forbidden(self, lng: float, lat: float) -> bool:
        """True si (lng, lat) tombe dans la zone interdite dilatée (vert olive, eau + bâtiments absorbés)."""
        if self.forbidden_mask is None:
            return False
        min_lng, min_lat, max_lng, max_lat = self.bbox
        if max_lng == min_lng or max_lat == min_lat:
            return False
        px = int((lng - min_lng) / (max_lng - min_lng) * self.map_w)
        py = int((1.0 - (lat - min_lat) / (max_lat - min_lat)) * self.map_h)
        px = max(0, min(self.map_w - 1, px))
        py = max(0, min(self.map_h - 1, py))
        return bool(self.forbidden_mask[py, px])

    def get_top_candidates(
        self, top_percent: float = 0.20
    ) -> list[tuple[float, float]]:
        """
        Retourne les coordonnées WGS84 (lng, lat) des top_percent% meilleurs pixels.

        Utilisé par le GA pour le Smart Seeding : tirer les postes initiaux
        parmi les zones visuellement attractives plutôt qu'au hasard.

        Args:
            top_percent: Fraction de la grille à conserver (0.20 = top 20%).

        Returns:
            Liste de (lng, lat) — peut être grande, le GA échantillonne dedans.
        """
        min_lng, min_lat, max_lng, max_lat = self.bbox
        H, W = self.scores.shape
        threshold = float(np.percentile(self.scores, 100.0 * (1.0 - top_percent)))
        grid_ys, grid_xs = np.where(self.scores >= threshold)
        candidates = []
        for gy, gx in zip(grid_ys.tolist(), grid_xs.tolist()):
            lng = min_lng + (gx / max(W - 1, 1)) * (max_lng - min_lng)
            lat = max_lat - (gy / max(H - 1, 1)) * (max_lat - min_lat)
            # Exclure les positions en zone interdite (vert olive, eau, bâtiments)
            if self.forbidden_mask is not None and self.is_forbidden(lng, lat):
                continue
            candidates.append((lng, lat))
        return candidates

    def save(self, path: "Path") -> None:
        """Sérialise la HeatmapCache sur disque via np.savez_compressed."""
        from pathlib import Path as _Path
        _p = _Path(path).with_suffix(".npz")
        np.savez_compressed(
            str(_p),
            scores=self.scores,
            forbidden=self.forbidden_mask if self.forbidden_mask is not None else np.array([], dtype=bool),
            bbox=np.array(self.bbox, dtype=np.float64),
            step_px=np.array(self.step_px),
            map_w=np.array(self.map_w),
            map_h=np.array(self.map_h),
            zone_labels=self.zone_labels if self.zone_labels is not None else np.array([], dtype=np.uint8),
            n_zones=np.array(self.n_zones),
        )
        log.debug("HeatmapCache: sauvegardé → %s", _p)

    @classmethod
    def load(cls, path: "Path") -> "HeatmapCache":
        """Charge une HeatmapCache depuis disque. Lève FileNotFoundError si absent."""
        from pathlib import Path as _Path
        _p = _Path(path).with_suffix(".npz")
        d = np.load(str(_p), allow_pickle=False)
        fm = d["forbidden"] if d["forbidden"].ndim == 2 else None
        zl_arr = d["zone_labels"] if "zone_labels" in d else np.array([], dtype=np.uint8)
        zl = zl_arr if zl_arr.ndim == 2 else None
        nz = int(d["n_zones"]) if "n_zones" in d else 0
        scores = d["scores"].astype(np.float32)
        bbox = tuple(d["bbox"].tolist())
        is_flat = bool(d["is_flat_signal"]) if "is_flat_signal" in d else False
        # Recompute zones si absent (backward compat avec les fichiers pré-Couche 0)
        if nz == 0:
            try:
                zl, nz = _compute_zones(scores, bbox, is_flat)
            except Exception:
                pass
        return cls(
            scores=scores,
            bbox=bbox,
            step_px=int(d["step_px"]),
            map_w=int(d["map_w"]),
            map_h=int(d["map_h"]),
            forbidden_mask=fm,
            zone_labels=zl,
            n_zones=nz,
        )


# ---------------------------------------------------------------------------
# Legacy: feature names pour le mode OSM (7-dim, déprécié)
# ---------------------------------------------------------------------------
_LEGACY_FEATURE_NAMES = [
    "brown_relief", "green_dense", "green_light", "yellow_open",
    "blue_water", "black_detail", "white_forest",
]

_LEGACY_ISOM_MAP = {
    range(101, 200): "brown_relief",
    range(201, 300): "black_detail",
    range(301, 400): "blue_water",
}


def _isom_to_color(isom_code: int) -> str:
    """Map ISOM 2017 symbol code → ISOM colour class (mode legacy OSM)."""
    c = int(isom_code)
    if 101 <= c <= 199:
        return "brown_relief"
    if 201 <= c <= 299:
        return "black_detail"
    if 301 <= c <= 399:
        return "blue_water"
    if c in (401, 402):
        return "yellow_open"
    if c == 403:
        return "white_forest"
    if 404 <= c <= 407:
        return "green_light"
    if 408 <= c <= 420:
        return "green_dense"
    if 421 <= c <= 499:
        return "green_light"
    if 501 <= c <= 599:
        return "black_detail"
    return "white_forest"


class OcadPatchScorer:
    """
    Scorer visuel de terrain pour le placement de postes en CO.

    Charge patch_scorer_v2.pkl (17 features ISOM globales + centrales + géométriques).
    Pour l'inférence, utilise score_map_image() qui crop des patches 256×256
    depuis l'image rasterisée de la carte, à l'échelle de l'entraînement (128m FOV).
    """

    _MODEL_RELATIVE = Path("data") / "models" / "patch_scorer_v2.pkl"

    def __init__(self, model):
        self._model = model

    @classmethod
    def load(cls, base_dir: Optional[Path] = None) -> Optional["OcadPatchScorer"]:
        """
        Charge le modèle XGBoost depuis le disque.

        Args:
            base_dir: Répertoire racine backend. Auto-détecté depuis __file__ si None.

        Returns:
            OcadPatchScorer instance, ou None si le fichier modèle est absent.
        """
        try:
            import joblib

            if base_dir is None:
                # __file__ = backend/src/services/learning/ocad_patch_scorer.py
                # parents[3] = backend/
                base_dir = Path(__file__).parents[3]

            model_path = base_dir / cls._MODEL_RELATIVE
            if not model_path.exists():
                log.debug("OcadPatchScorer: model not found at %s", model_path)
                return None

            model = joblib.load(model_path)
            log.info("OcadPatchScorer: loaded patch_scorer_v2.pkl (18-dim visual model — V3 bi-mode)")
            return cls(model)
        except Exception as exc:
            log.debug("OcadPatchScorer: could not load model (%s)", exc)
            return None

    # ------------------------------------------------------------------
    # API principale — mode image (v2)
    # ------------------------------------------------------------------

    def score_patch(
        self,
        img: Image.Image,
        lng: float = 0.0,
        lat: float = 0.0,
        force_is_urban: Optional[int] = None,
    ) -> Optional[float]:
        """
        Score un patch PIL Image 256×256.

        Extrait les 18 features visuelles (+ géographiques) et prédit la probabilité
        que ce patch représente un bon emplacement de poste.

        Args:
            img: Image PIL (n'importe quel mode, converti en RGB automatiquement).
                 Taille recommandée : 256×256 (redimensionné si nécessaire).
            lng: Longitude WGS84
            lat: Latitude WGS84
            force_is_urban: 1 (urbain) ou 0 (forêt) pour forcer la feature is_urban.
                            None = détection automatique.

        Returns:
            Probabilité [0..1], ou None si l'extraction échoue.
        """
        try:
            vec = extract_features(img, lng, lat, force_is_urban=force_is_urban).reshape(1, -1)
            return float(self._model.predict_proba(vec)[0][1])
        except Exception as exc:
            log.debug("score_patch failed: %s", exc)
            return None

    def score_map_image(
        self,
        map_img: Image.Image,
        candidates: List[Dict],
        mpp: float = 0.5,
        worldfile: Optional[tuple[float, float, float, float, float, float]] = None,
        bbox: Optional[tuple[float, float, float, float]] = None,
        force_mode: Optional[str] = None,
    ) -> List[Dict]:
        """
        Score une liste de candidats sur l'image complète de la carte.

        Pour chaque candidat {px, py}, extrait un crop centré couvrant 128m réels,
        le redimensionne en 256×256 (comme à l'entraînement), et prédit le score.

        Args:
            map_img: Image PIL de la carte complète (en pixels).
            candidates: Liste de dicts avec au minimum {"px": int, "py": int}.
                        Chaque dict est enrichi en place avec {"score": float}.
            mpp: Mètres par pixel de l'image carte (default 0.5 = échelle entraînement).
                 Exemple : pour une carte 1:4000 rendue à 100 dpi → mpp ≈ 1.016.
            worldfile: Paramètres (A, D, B, E, C, F) pour conversion geographique (px → lng, lat).
                       Si None, cherche "worldfile" dans l'objet OcadPatchScorer s'il existe.
            force_mode: "sprint" → is_urban=1, "forest" → is_urban=0, None → auto.

        Returns:
            Liste de dicts [{px, py, score, ...}] dans le même ordre que candidates.
            score = None si le patch ne peut pas être évalué.
        """
        map_w, map_h = map_img.size
        wf = worldfile or getattr(self, "worldfile", None)
        force_is_urban: Optional[int] = {"sprint": 1, "forest": 0}.get(force_mode)  # type: ignore[arg-type]

        # FOV à l'entraînement : 256px × 0.5m/px = 128m de côté
        fov_m = 128.0
        crop_px = max(1, int(fov_m / mpp))   # taille du crop en pixels à cette résolution

        def _score_one(cand: Dict) -> Dict:
            px = int(cand["px"])
            py = int(cand["py"])
            r = crop_px // 2

            x0, y0 = px - r, py - r
            x1, y1 = x0 + crop_px, y0 + crop_px

            ix0 = max(0, x0)
            iy0 = max(0, y0)
            ix1 = min(map_w, x1)
            iy1 = min(map_h, y1)

            if ix1 <= ix0 or iy1 <= iy0:
                return {**cand, "score": None}

            region = map_img.crop((ix0, iy0, ix1, iy1))

            if ix0 != x0 or iy0 != y0 or ix1 != x1 or iy1 != y1:
                padded = Image.new("RGB", (crop_px, crop_px), (255, 255, 255))
                padded.paste(region.convert("RGB"), (ix0 - x0, iy0 - y0))
                region = padded

            if crop_px != 256:
                region = region.resize((256, 256), Image.LANCZOS)

            lng, lat = 0.0, 0.0
            if wf:
                A, D, B, E, C, F = wf
                lng = A * px + B * py + C
                lat = D * px + E * py + F
            elif bbox:
                min_lng, min_lat, max_lng, max_lat = bbox
                lng = min_lng + (px / map_w) * (max_lng - min_lng)
                lat = max_lat - (py / map_h) * (max_lat - min_lat)

            # ── Color Bouncer : filtre couleur interdit avant inférence XGBoost ─
            _cx, _cy = 128, 128
            _win = region.crop((_cx - 2, _cy - 2, _cx + 3, _cy + 3)).convert("RGB")
            _rgb = np.array(_win, dtype=float).mean(axis=(0, 1))
            _r, _g, _b = float(_rgb[0]), float(_rgb[1]), float(_rgb[2])
            _olive = (120 <= _r <= 210) and (150 <= _g <= 220) and (_b < 80) and (_g > _r)
            _water = (_b > 160) and (_r < 130) and (_g < 160)
            if _olive or _water:
                return {**cand, "score": 0.0}
            # ──────────────────────────────────────────────────────────────────
            return {**cand, "score": self.score_patch(region, lng, lat, force_is_urban=force_is_urban)}

        n_workers = min(os.cpu_count() or 4, 8)
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            results = list(executor.map(_score_one, candidates))

        return results

    def build_heatmap_cache(
        self,
        map_img: Image.Image,
        bbox: tuple,
        mpp: float = 0.5,
        step_px: int = 20,
        force_mode: Optional[str] = None,
        candidate_points: Optional[list] = None,
        cnn_scorer: Optional["CnnPatchScorer"] = None,
    ) -> "HeatmapCache":
        """
        Précompute une grille de scores sur l'image carte entière.

        Si cnn_scorer est fourni, utilise l'inférence CNN batch (ONNX) ;
        sinon fallback XGBoost via score_map_image().

        Args:
            map_img:    Image PIL de la carte complète.
            bbox:       (min_lng, min_lat, max_lng, max_lat) WGS84 correspondant à l'image.
            mpp:        Mètres par pixel (default 0.5).
            step_px:    Pas de grille en pixels (default 20 = tous les 10m à mpp=0.5).
            force_mode: "sprint" → is_urban forcé à 1, "forest" → 0, None → auto.
            cnn_scorer: CnnPatchScorer instance (ONNX) ou None → XGBoost.

        Returns:
            HeatmapCache prêt à l'emploi.
        """
        import time as _time
        map_w, map_h = map_img.size
        xs = list(range(0, map_w, step_px))
        ys = list(range(0, map_h, step_px))
        candidates = [{"px": x, "py": y} for y in ys for x in xs]
        mode_label = {"sprint": "Sprint/Urbain forcé", "forest": "Forêt forcé"}.get(force_mode or "", "Auto")
        scorer_label = "CNN ONNX" if cnn_scorer is not None else "XGBoost V3"
        log.info(
            "HeatmapCache: scoring %d positions (step=%dpx, %dx%d grid, mode=%s, scorer=%s)…",
            len(candidates), step_px, len(xs), len(ys), mode_label, scorer_label,
        )

        _t0 = _time.monotonic()

        if cnn_scorer is not None:
            # ── Branche CNN : extraction patches + inférence batch ONNX ───────
            # Stratégie "Dalle Globale" : construire les maps DEM une seule fois
            dem_elev = dem_slope = None
            if cnn_scorer._in_channels == 5 and cnn_scorer._srtm is not None and bbox is not None:
                try:
                    import time as _t2
                    _td0 = _t2.monotonic()
                    dem_elev, dem_slope = _build_dem_tiles(bbox, map_w, map_h, cnn_scorer._srtm)
                    log.info("HeatmapCache: DEM tiles construit en %.2fs", _t2.monotonic() - _td0)
                except Exception as exc:
                    log.warning("HeatmapCache: DEM tiles échoué (%s) → canaux DEM=0", exc)

            patches_with_dem = []
            for c in candidates:
                px, py = int(c["px"]), int(c["py"])
                patch = CnnPatchScorer.crop_patch(map_img, px, py, mpp)
                if dem_elev is not None:
                    r = max(1, int(CnnPatchScorer._FOV_M / mpp) // 2)
                    e_crop = dem_elev[max(0, py - r):py + r, max(0, px - r):px + r]
                    s_crop = dem_slope[max(0, py - r):py + r, max(0, px - r):px + r]
                else:
                    e_crop = s_crop = None
                patches_with_dem.append((patch, e_crop, s_crop))
            scores_flat = cnn_scorer.score_batch(patches_with_dem)
            scores_flat = scores_flat.astype(np.float32)
        else:
            # ── Branche XGBoost (comportement historique) ─────────────────────
            results = self.score_map_image(map_img, candidates, mpp=mpp, bbox=bbox, force_mode=force_mode)
            scores_flat = np.array(
                [r["score"] if r["score"] is not None else 0.0 for r in results],
                dtype=np.float32,
            )

        _elapsed = _time.monotonic() - _t0
        scores_grid = scores_flat.reshape(len(ys), len(xs))
        # ── Forbidden mask : vert olive + eau + dilatation → absorbe bâtiments enclavés ──
        _forbidden_mask = None
        try:
            from scipy.ndimage import binary_dilation
            _img_arr = np.array(map_img.convert("RGB"), dtype=np.float32)
            _r_ch, _g_ch, _b_ch = _img_arr[:, :, 0], _img_arr[:, :, 1], _img_arr[:, :, 2]
            _olive_px = (
                (_r_ch >= 120) & (_r_ch <= 210) &
                (_g_ch >= 150) & (_g_ch <= 220) &
                (_b_ch < 80) & (_g_ch > _r_ch)
            )
            _water_px = (_b_ch > 160) & (_r_ch < 130) & (_g_ch < 160)
            _raw_mask = _olive_px | _water_px
            _kernel_px = max(15, min(60, int(30.0 / mpp)))  # cap 60px max (~30m à mpp≥0.5)
            _struct = np.ones((_kernel_px, _kernel_px), dtype=bool)
            _forbidden_mask = binary_dilation(_raw_mask, structure=_struct).astype(bool)
        except Exception as _fm_err:
            log.warning("ForbiddenMask ÉCHEC scipy: %s — masque désactivé", _fm_err)
            _forbidden_mask = None
        # ─────────────────────────────────────────────────────────────────────────────────
        _pct_forbidden = float(_forbidden_mask.mean()) * 100 if _forbidden_mask is not None else 0.0
        _scores_std = float(scores_grid.std())
        _is_flat = _scores_std < 0.05
        log.info(
            "HeatmapCache: %s | grid=%dx%d step=%dpx mpp=%.2fm | "
            "mean=%.3f p50=%.3f p90=%.3f p99=%.3f std=%.4f | forbidden=%.1f%% | %.0f patches/s (%.2fs)",
            scorer_label,
            scores_grid.shape[1], scores_grid.shape[0], step_px, mpp,
            float(scores_grid.mean()),
            float(np.percentile(scores_grid, 50)),
            float(np.percentile(scores_grid, 90)),
            float(np.percentile(scores_grid, 99)),
            _scores_std,
            _pct_forbidden,
            len(candidates) / max(_elapsed, 1e-6), _elapsed,
        )
        if _is_flat:
            log.warning(
                "HeatmapCache: signal plat (std=%.4f < 0.05) — fallback ISOM activé en GA",
                _scores_std,
            )
        # ── Segmentation zones (Couche 0) ─────────────────────────────────────────────────
        _zone_labels, _n_zones = _compute_zones(scores_grid, bbox, _is_flat, candidate_points)
        _zone_method = "flat/neutre" if _n_zones == 1 else ("k-means CNN" if not _is_flat else "densité ISOM")
        log.info("HeatmapCache: zones=%d (%s)", _n_zones, _zone_method)
        # ─────────────────────────────────────────────────────────────────────────────────
        return HeatmapCache(
            scores=scores_grid,
            bbox=bbox,
            step_px=step_px,
            map_w=map_w,
            map_h=map_h,
            forbidden_mask=_forbidden_mask,
            scores_std=_scores_std,
            is_flat_signal=_is_flat,
            zone_labels=_zone_labels,
            n_zones=_n_zones,
        )

    # ------------------------------------------------------------------
    # API legacy — mode OSM (v1, déprécié)
    # ------------------------------------------------------------------

    @staticmethod
    def _haversine_m(p1: tuple, p2: tuple) -> float:
        """Haversine distance in metres between two (lng, lat) points."""
        R = 6_371_000.0
        lat1, lat2 = math.radians(p1[1]), math.radians(p2[1])
        dlat = math.radians(p2[1] - p1[1])
        dlng = math.radians(p2[0] - p1[0])
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _build_legacy_feature_vector(
        self,
        x: float,
        y: float,
        candidate_points: List[Dict],
        radius_m: float,
    ) -> Optional[np.ndarray]:
        """
        Construit un vecteur 17-dim depuis les candidate_points OSM.

        Les 7 premières dims sont les fractions ISOM pondérées par distance.
        Les 10 dims restantes (features centre + géométrie) sont mises à 0
        car non calculables depuis les vecteurs OSM.

        Retourne None si aucun candidat dans le rayon.
        """
        counts: dict[str, float] = {k: 0.0 for k in _LEGACY_FEATURE_NAMES}
        total = 0.0

        for cp in candidate_points:
            d = self._haversine_m((x, y), (cp["x"], cp["y"]))
            if d >= radius_m:
                continue
            isom = cp.get("isom")
            color = _isom_to_color(int(isom)) if isom is not None else "white_forest"
            weight = 1.0 - d / radius_m
            counts[color] += weight
            total += weight

        if total == 0.0:
            return None

        # 7 features OSM + 10 zeros (centre + géométrie non disponibles)
        global_vec = np.array(
            [counts[k] / total for k in _LEGACY_FEATURE_NAMES], dtype=np.float32
        )
        padding = np.zeros(10, dtype=np.float32)
        return np.concatenate([global_vec, padding]).reshape(1, -1)

    def score_position(
        self,
        x: float,
        y: float,
        candidate_points: List[Dict],
        radius_m: float = 64.0,
    ) -> Optional[float]:
        """
        [DÉPRÉCIÉ] Score via candidate_points OSM (7-dim + zeros).

        Préférer score_map_image() pour une inférence avec les 17 features visuelles.

        Args:
            x, y: Position WGS84 (longitude, latitude).
            candidate_points: Données OSM [{x, y, isom, ...}].
            radius_m: Rayon de contexte (default 64m).

        Returns:
            Probabilité [0..1] ou None si pas de données terrain.
            Fallback neutre recommandé : 0.45.
        """
        vec = self._build_legacy_feature_vector(x, y, candidate_points, radius_m)
        if vec is None:
            return None
        try:
            return float(self._model.predict_proba(vec)[0][1])
        except Exception as exc:
            log.debug("score_position (legacy) failed: %s", exc)
            return None

    def score_circuit(
        self,
        controls: List[tuple],
        candidate_points: List[Dict],
        radius_m: float = 64.0,
    ) -> float:
        """
        [DÉPRÉCIÉ] Score moyen d'un circuit via candidate_points OSM.

        Args:
            controls: Liste de positions (x, y) — départ + postes + arrivée.
            candidate_points: Données OSM pour le contexte terrain.
            radius_m: Rayon de contexte par poste.

        Returns:
            Probabilité moyenne [0..1], ou 0.45 (neutre) si pas de données.
        """
        if len(controls) < 3:
            return 0.45
        scores = []
        for pos in controls[1:-1]:  # exclure départ et arrivée
            s = self.score_position(pos[0], pos[1], candidate_points, radius_m)
            if s is not None:
                scores.append(s)
        return sum(scores) / len(scores) if scores else 0.45


# ---------------------------------------------------------------------------
# DEM helper — Dalle globale SRTM pour heatmap
# ---------------------------------------------------------------------------

def _build_dem_tiles(
    bbox_wgs84: tuple,
    map_w: int,
    map_h: int,
    srtm_data: object,
    sample: int = 64,
) -> tuple:
    """
    Construit elevation_map et slope_map pour toute la bbox carte.

    Stratégie vectorisée : 64×64 appels SRTM une fois, resize bilinéaire vers
    (map_h, map_w). Coût : ~4096 appels au lieu de N_patches × 256.

    Args:
        bbox_wgs84: (min_lon, min_lat, max_lon, max_lat)
        map_w, map_h: dimensions de l'image carte en pixels
        srtm_data: instance srtm.get_data()
        sample: résolution de la grille SRTM (64 suffisant pour 128m FOV)

    Returns:
        (elev_norm, slope_norm) — deux np.ndarray float32 (map_h, map_w) ∈ [0,1]
    """
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    lats = np.linspace(max_lat, min_lat, sample)
    lons = np.linspace(min_lon, max_lon, sample)
    grid = np.zeros((sample, sample), dtype=np.float32)
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            grid[i, j] = srtm_data.get_elevation(float(la), float(lo)) or 0.0

    gy, gx = np.gradient(grid)
    # cell_m = largeur réelle en mètres d'une cellule de la grille SRTM
    cell_m = 111320.0 * (max_lat - min_lat) / sample
    slope_deg = np.degrees(np.arctan(np.sqrt(gx**2 + gy**2) / max(cell_m, 1.0)))

    elev_img  = Image.fromarray(grid).resize((map_w, map_h), Image.Resampling.BILINEAR)
    slope_img = Image.fromarray(slope_deg.astype(np.float32)).resize((map_w, map_h), Image.Resampling.BILINEAR)
    elev_norm  = np.clip(np.array(elev_img,  dtype=np.float32) / 3000.0, 0.0, 1.0)
    slope_norm = np.clip(np.array(slope_img, dtype=np.float32) / 45.0,   0.0, 1.0)
    return elev_norm, slope_norm  # (map_h, map_w) chacun


# ---------------------------------------------------------------------------
# Zone segmentation helpers (Couche 0)
# ---------------------------------------------------------------------------

def _kmeans_1d(values: np.ndarray, k: int = 3, max_iter: int = 50) -> np.ndarray:
    """K-means 1D pur numpy — labels 0..k-1, forme identique à values."""
    flat = values.ravel().astype(np.float32)
    pcts = np.linspace(0.0, 100.0, k + 2)[1:-1]
    centroids = np.percentile(flat, pcts).astype(np.float32)
    labels = np.zeros(len(flat), dtype=np.int32)
    for _ in range(max_iter):
        dists = np.abs(flat[:, None] - centroids[None, :])  # (N, k)
        new_labels = dists.argmin(axis=1).astype(np.int32)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(k):
            mask = labels == j
            if mask.any():
                centroids[j] = flat[mask].mean()
    return labels.reshape(values.shape)


def _compute_zones(
    scores_grid: np.ndarray,
    bbox: tuple,
    is_flat_signal: bool,
    candidate_points: Optional[list] = None,
) -> "tuple[np.ndarray, int]":
    """
    Segmente la grille en 3 zones de richesse terrain (0=pauvre, 1=modérée, 2=riche).

    Branche 1 (normal)          : k-means 1D sur scores_grid.
    Branche 2 (signal plat + ISOM) : densité spatiale via histogram sur candidate_points.
    Fallback                    : zone_labels = 1 partout, n_zones = 1.

    Returns:
        (zone_labels, n_zones) — labels (H, W) uint8, n_zones = 1 ou 3.
    """
    H, W = scores_grid.shape

    def _sorted_labels(raw: np.ndarray, source: np.ndarray) -> np.ndarray:
        # Re-trier pour 0=pauvre (centroïde le plus bas) et 2=riche (le plus haut)
        centroids_val = np.array(
            [source[raw == j].mean() if (raw == j).any() else 0.0 for j in range(3)],
            dtype=np.float32,
        )
        centroids_val = np.nan_to_num(centroids_val, nan=0.0)  # cluster vide → 0
        rank = np.argsort(np.argsort(centroids_val))  # double argsort = rang ordinal
        return rank[raw].astype(np.uint8)

    if not is_flat_signal:
        raw = _kmeans_1d(scores_grid, k=3)
        return _sorted_labels(raw, scores_grid), 3

    if candidate_points and len(candidate_points) >= 9:
        try:
            min_lng, min_lat, max_lng, max_lat = bbox
            pts = np.array([[cp["x"], cp["y"]] for cp in candidate_points], dtype=np.float32)
            density, _, _ = np.histogram2d(
                pts[:, 0], pts[:, 1],  # lng, lat
                bins=[W, H],
                range=[[min_lng, max_lng], [min_lat, max_lat]],
            )
            density = density.T[::-1, :].astype(np.float32)  # (H, W), row 0 = max_lat
            if float(density.std()) > 0:
                raw = _kmeans_1d(density, k=3)
                return _sorted_labels(raw, density), 3
        except Exception:
            pass

    return np.ones((H, W), dtype=np.uint8), 1


# ---------------------------------------------------------------------------
# CnnPatchScorer — Inférence MobileNetV3-Small via ONNX (prod, pas de PyTorch)
# ---------------------------------------------------------------------------

class CnnPatchScorer:
    """
    Scorer CNN basé sur MobileNetV3-Small exporté en ONNX.

    Utilisé à la place de OcadPatchScorer (XGBoost) dans build_heatmap_cache()
    quand le fichier control_scorer_cnn.onnx est disponible.

    Avantage vs XGBoost : voit directement la structure spatiale de la carte
    (intersections, lisières, rochers…) sans features manuelles.
    AUC attendu : ~0.87–0.91 vs 0.807 XGBoost V3.

    Pas de dépendance PyTorch à runtime — onnxruntime seulement.
    """

    _MODEL_RELATIVE = Path("data") / "models" / "control_scorer_cnn.onnx"
    # Normalisation RGB (canaux 0-2)
    _MEAN_3 = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    _STD_3  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    # Normalisation 5 canaux (RGB + altitude + pente)
    _MEAN_5 = np.array([0.485, 0.456, 0.406, 0.5,  0.1 ], dtype=np.float32)
    _STD_5  = np.array([0.229, 0.224, 0.225, 0.25, 0.15], dtype=np.float32)

    # FOV identique à OcadPatchScorer (128m) — crop puis resize 224 pour MobileNetV3
    _FOV_M: float = 128.0
    _TARGET_PX: int = 224

    def __init__(self, session: object, srtm_data: object = None) -> None:
        self._session = session   # onnxruntime.InferenceSession
        self._srtm = srtm_data    # srtm.get_data() ou None (fallback 3ch)
        # Détecter le nombre de canaux attendus par le modèle ONNX
        try:
            in_shape = session.get_inputs()[0].shape  # [batch, C, 224, 224]
            self._in_channels = int(in_shape[1]) if len(in_shape) >= 2 else 3
        except Exception:
            self._in_channels = 3

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, base_dir: Optional[Path] = None) -> Optional["CnnPatchScorer"]:
        """
        Charge le modèle ONNX depuis data/models/control_scorer_cnn.onnx.

        Returns None si onnxruntime non installé ou modèle absent (fallback XGBoost).
        """
        try:
            import onnxruntime as ort  # type: ignore[import]
        except ImportError:
            log.debug("CnnPatchScorer: onnxruntime non installé — fallback XGBoost")
            return None

        model_path = (base_dir or Path(__file__).parents[3]) / cls._MODEL_RELATIVE
        if not model_path.exists():
            log.debug("CnnPatchScorer: modèle absent (%s) — fallback XGBoost", model_path)
            return None

        import os as _os
        _available = ort.get_available_providers()
        _providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if "CUDAExecutionProvider" in _available
            else ["CPUExecutionProvider"]
        )
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = _os.cpu_count() or 4
        opts.enable_mem_pattern = True
        session = ort.InferenceSession(str(model_path), sess_options=opts, providers=_providers)
        # Charger SRTM pour les modèles 5 canaux
        srtm_data = None
        try:
            in_shape = session.get_inputs()[0].shape
            in_ch = int(in_shape[1]) if len(in_shape) >= 2 else 3
        except Exception:
            in_ch = 3
        if in_ch == 5:
            try:
                import srtm, tempfile, os  # type: ignore[import]
                _srtm_cache = os.path.join(tempfile.gettempdir(), "srtm_cache")
                os.makedirs(_srtm_cache, exist_ok=True)
                srtm_data = srtm.get_data()
                log.info("CnnPatchScorer: srtm.py chargé (DEM 5 canaux actif)")
            except ImportError:
                log.warning("CnnPatchScorer: srtm.py absent (pip install srtm.py) → canaux DEM=0")
        log.info(
            "CnnPatchScorer: chargé %s (MobileNetV3-Small ONNX, %dch, provider=%s, threads=%d)",
            model_path.name, in_ch, session.get_providers()[0], opts.intra_op_num_threads,
        )
        return cls(session, srtm_data)

    # ------------------------------------------------------------------
    # Crop helper (statique — réutilisable depuis build_heatmap_cache)
    # ------------------------------------------------------------------

    @staticmethod
    def crop_patch(map_img: Image.Image, px: int, py: int, mpp: float) -> Image.Image:
        """
        Extrait un patch 224×224 centré sur (px, py) couvrant FOV_M=128m.

        Identique au crop de OcadPatchScorer mais resize en 224×224 BILINEAR
        (MobileNetV3 attend 224×224 ; BILINEAR préserve les symboles IOF vs NEAREST).
        """
        map_w, map_h = map_img.size
        crop_px = max(1, int(CnnPatchScorer._FOV_M / mpp))
        r = crop_px // 2
        x0, y0 = px - r, py - r
        x1, y1 = x0 + crop_px, y0 + crop_px

        ix0, iy0 = max(0, x0), max(0, y0)
        ix1, iy1 = min(map_w, x1), min(map_h, y1)

        if ix1 <= ix0 or iy1 <= iy0:
            return Image.new("RGB", (CnnPatchScorer._TARGET_PX, CnnPatchScorer._TARGET_PX), (255, 255, 255))

        region = map_img.crop((ix0, iy0, ix1, iy1))

        if ix0 != x0 or iy0 != y0 or ix1 != x1 or iy1 != y1:
            padded = Image.new("RGB", (crop_px, crop_px), (255, 255, 255))
            padded.paste(region.convert("RGB"), (ix0 - x0, iy0 - y0))
            region = padded

        return region.resize(
            (CnnPatchScorer._TARGET_PX, CnnPatchScorer._TARGET_PX),
            resample=Image.Resampling.BILINEAR,
        )

    # ------------------------------------------------------------------
    # Inférence batch
    # ------------------------------------------------------------------

    def score_batch(self, patches) -> np.ndarray:
        """
        Score une liste de patches via inférence ONNX batch.

        Args:
            patches: list de PIL.Image (3 canaux) OU list de (PIL.Image, elev_crop, slope_crop)
                     où elev_crop/slope_crop sont des np.ndarray float32 ∈ [0,1] ou None.

        Returns:
            np.ndarray shape (N,) — probabilités [0, 1].
        """
        from scipy.special import expit  # sigmoid numeriquement stable (no overflow)

        _BATCH = 64  # optimal CPU ONNX : ~3-5s pour 1600 patches
        results: list[np.ndarray] = []
        use_5ch = self._in_channels == 5

        for i in range(0, len(patches), _BATCH):
            chunk = patches[i : i + _BATCH]
            tensors = []
            for item in chunk:
                # Accepter les deux formes d'entrée
                if isinstance(item, tuple):
                    img, e_crop, s_crop = item
                else:
                    img, e_crop, s_crop = item, None, None

                arr = np.array(img.convert("RGB"), dtype=np.float32) / 255.0  # (224,224,3)

                if use_5ch:
                    # Canaux DEM : resize si fournis, sinon zéros
                    if e_crop is not None and s_crop is not None and e_crop.size > 0:
                        e224 = np.array(
                            Image.fromarray(e_crop).resize(
                                (self._TARGET_PX, self._TARGET_PX), Image.Resampling.BILINEAR
                            ), dtype=np.float32
                        )
                        s224 = np.array(
                            Image.fromarray(s_crop).resize(
                                (self._TARGET_PX, self._TARGET_PX), Image.Resampling.BILINEAR
                            ), dtype=np.float32
                        )
                    else:
                        e224 = np.zeros((self._TARGET_PX, self._TARGET_PX), dtype=np.float32)
                        s224 = np.zeros((self._TARGET_PX, self._TARGET_PX), dtype=np.float32)
                    arr5 = np.concatenate([arr, e224[..., None], s224[..., None]], axis=-1)  # (224,224,5)
                    arr5 = (arr5 - self._MEAN_5) / self._STD_5
                    tensors.append(arr5.transpose(2, 0, 1))  # (5,224,224)
                else:
                    arr3 = (arr - self._MEAN_3) / self._STD_3
                    tensors.append(arr3.transpose(2, 0, 1))  # (3,224,224)

            batch = np.stack(tensors, axis=0)  # (N, C, 224, 224)
            logits = self._session.run(["output"], {"input": batch})[0]  # (N, 1)
            results.append(expit(logits).ravel())

        return np.concatenate(results)
