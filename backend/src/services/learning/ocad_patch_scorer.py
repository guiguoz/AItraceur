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
            candidates.append((lng, lat))
        return candidates


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
            log.info("OcadPatchScorer: loaded patch_scorer_v2.pkl (17-dim visual model)")
            return cls(model)
        except Exception as exc:
            log.debug("OcadPatchScorer: could not load model (%s)", exc)
            return None

    # ------------------------------------------------------------------
    # API principale — mode image (v2)
    # ------------------------------------------------------------------

    def score_patch(self, img: Image.Image) -> Optional[float]:
        """
        Score un patch PIL Image 256×256.

        Extrait les 17 features visuelles et prédit la probabilité
        que ce patch représente un bon emplacement de poste.

        Args:
            img: Image PIL (n'importe quel mode, converti en RGB automatiquement).
                 Taille recommandée : 256×256 (redimensionné si nécessaire).

        Returns:
            Probabilité [0..1], ou None si l'extraction échoue.
        """
        try:
            vec = extract_features(img).reshape(1, -1)
            return float(self._model.predict_proba(vec)[0][1])
        except Exception as exc:
            log.debug("score_patch failed: %s", exc)
            return None

    def score_map_image(
        self,
        map_img: Image.Image,
        candidates: List[Dict],
        mpp: float = 0.5,
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

        Returns:
            Liste de dicts [{px, py, score, ...}] dans le même ordre que candidates.
            score = None si le patch ne peut pas être évalué.
        """
        map_w, map_h = map_img.size

        # FOV à l'entraînement : 256px × 0.5m/px = 128m de côté
        fov_m = 128.0
        crop_px = max(1, int(fov_m / mpp))   # taille du crop en pixels à cette résolution

        results = []
        for cand in candidates:
            px = int(cand["px"])
            py = int(cand["py"])
            r = crop_px // 2

            # Coordonnées du crop (peuvent déborder)
            x0, y0 = px - r, py - r
            x1, y1 = x0 + crop_px, y0 + crop_px

            # Intersection avec les limites de l'image
            ix0 = max(0, x0)
            iy0 = max(0, y0)
            ix1 = min(map_w, x1)
            iy1 = min(map_h, y1)

            if ix1 <= ix0 or iy1 <= iy0:
                # Candidat entièrement hors image
                results.append({**cand, "score": None})
                continue

            # Crop de la zone valide
            region = map_img.crop((ix0, iy0, ix1, iy1))

            # Padding blanc si le crop déborde
            if ix0 != x0 or iy0 != y0 or ix1 != x1 or iy1 != y1:
                padded = Image.new("RGB", (crop_px, crop_px), (255, 255, 255))
                paste_x = ix0 - x0
                paste_y = iy0 - y0
                padded.paste(region.convert("RGB"), (paste_x, paste_y))
                region = padded

            # Redimensionnement vers 256×256 (taille d'entraînement)
            if crop_px != 256:
                region = region.resize((256, 256), Image.LANCZOS)

            score = self.score_patch(region)
            results.append({**cand, "score": score})

        return results

    def build_heatmap_cache(
        self,
        map_img: Image.Image,
        bbox: tuple,
        mpp: float = 0.5,
        step_px: int = 20,
    ) -> "HeatmapCache":
        """
        Précompute une grille de scores V2 sur l'image carte entière.

        Appelle score_map_image() sur une grille régulière de positions,
        puis construit un HeatmapCache pour les lookups O(1) du GA.

        Args:
            map_img: Image PIL de la carte complète.
            bbox:    (min_lng, min_lat, max_lng, max_lat) WGS84 correspondant à l'image.
            mpp:     Mètres par pixel (default 0.5).
            step_px: Pas de grille en pixels (default 20 = tous les 10m à mpp=0.5).

        Returns:
            HeatmapCache prêt à l'emploi.
        """
        map_w, map_h = map_img.size
        xs = list(range(0, map_w, step_px))
        ys = list(range(0, map_h, step_px))
        candidates = [{"px": x, "py": y} for y in ys for x in xs]
        log.info(
            "HeatmapCache: scoring %d positions (step=%dpx, %dx%d grid)…",
            len(candidates), step_px, len(xs), len(ys),
        )
        results = self.score_map_image(map_img, candidates, mpp=mpp)
        scores_flat = np.array(
            [r["score"] if r["score"] is not None else 0.0 for r in results],
            dtype=np.float32,
        )
        scores_grid = scores_flat.reshape(len(ys), len(xs))
        log.info(
            "HeatmapCache: done — mean=%.3f, max=%.3f",
            float(scores_grid.mean()), float(scores_grid.max()),
        )
        return HeatmapCache(
            scores=scores_grid,
            bbox=bbox,
            step_px=step_px,
            map_w=map_w,
            map_h=map_h,
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
