"""
Raster de coût — grille numpy modélisant les coûts de déplacement terrain.

Chaque cellule contient un coût relatif [1.0, ∞] :
  1.0  = vitesse pleine (terrain ouvert, route)
  inf  = infranchissable (zone interdite, eau profonde)

Construction :
  1. Créer un raster plein de coût DEFAULT_COST (forêt courante ou terrain ouvert).
  2. Pour chaque feature surfacique : remplir les cellules correspondantes.
  3. Pour chaque feature linéaire (chemin, mur) : « peindre » l'épaisseur du trait.

Le pathfinding sur raster utilise skimage.graph.route_through_array (Dijkstra).

Exemple :
    raster = CostRaster.build(features, bbox, resolution_m=5.0, environment=…)
    cost   = raster.path_cost(pt_a, pt_b)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

try:
    import numpy as np
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union
    _NP_OK = True
except ImportError:
    _NP_OK = False

try:
    from skimage.graph import route_through_array
    _SKIMAGE_OK = True
except ImportError:
    _SKIMAGE_OK = False

from ..controls.symbol_map import TerrainType
from ..controls.ocad_parser import SemanticFeature
from ..profiles import CourseEnvironment
from .terrain_types import TerrainCost, get_terrain_cost


# ---------------------------------------------------------------------------
# BoundingBox projetée
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BBox:
    """Enveloppe rectangulaire en coordonnées projetées (mètres)."""
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width_m(self) -> float:
        return self.max_x - self.min_x

    @property
    def height_m(self) -> float:
        return self.max_y - self.min_y

    def to_shapely(self) -> Any:
        return box(self.min_x, self.min_y, self.max_x, self.max_y)

    @classmethod
    def from_features(cls, features: list[SemanticFeature], buffer_m: float = 50.0) -> "BBox":
        """Calcule le bbox englobant toutes les features."""
        xs, ys = [], []
        for f in features:
            if f.geom is None:
                continue
            b = f.geom.bounds
            xs.extend([b[0], b[2]])
            ys.extend([b[1], b[3]])
        if not xs:
            return cls(0, 0, 1000, 1000)
        return cls(
            min(xs) - buffer_m, min(ys) - buffer_m,
            max(xs) + buffer_m, max(ys) + buffer_m,
        )


# ---------------------------------------------------------------------------
# CostRaster
# ---------------------------------------------------------------------------

class CostRaster:
    """
    Raster de coût de déplacement terrain.

    Attributes:
        data:          Tableau numpy (H, W) float32, coûts [1.0, ∞].
        bbox:          Enveloppe géographique (mètres).
        resolution_m:  Taille d'une cellule (mètres).
        environment:   Environnement cartographique.
    """

    def __init__(
        self,
        data: "np.ndarray",
        bbox: BBox,
        resolution_m: float,
        environment: CourseEnvironment,
    ) -> None:
        if not _NP_OK:
            raise ImportError("numpy et shapely sont requis.")
        self.data = data
        self.bbox = bbox
        self.resolution_m = resolution_m
        self.environment = environment

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        features: list[SemanticFeature],
        bbox: Optional[BBox] = None,
        *,
        resolution_m: float = 5.0,
        environment: CourseEnvironment = CourseEnvironment.FOREST,
        default_cost: float = 1.43,    # ≈ forêt courante (1/0.70)
    ) -> "CostRaster":
        """
        Construit le raster depuis les SemanticFeature.

        Pipeline :
          1. Crée un raster rempli à default_cost.
          2. Peint les zones surfaciques (Polygon/MultiPolygon).
          3. Peint les features linéaires avec une épaisseur (buffer).

        Args:
            features:     SemanticFeatures de la carte.
            bbox:         Enveloppe. Si None, calculée depuis les features.
            resolution_m: Résolution spatiale en mètres.
            environment:  Profil d'environnement.
            default_cost: Valeur initiale (terrain de base).

        Returns:
            CostRaster prêt pour le pathfinding.
        """
        if not _NP_OK:
            raise ImportError("numpy et shapely sont requis.")

        if bbox is None:
            bbox = BBox.from_features(features)

        cols = max(1, int(math.ceil(bbox.width_m / resolution_m)))
        rows = max(1, int(math.ceil(bbox.height_m / resolution_m)))

        data = np.full((rows, cols), default_cost, dtype=np.float32)

        r = cls(data, bbox, resolution_m, environment)

        # Peint zones surfaciques en premier (basse priorité)
        area_features = [f for f in features if f.is_area and not f.is_layout]
        for feat in area_features:
            cost = get_terrain_cost(feat.info.terrain_type, environment)
            r._paint_polygon(feat.geom, cost)

        # Peint features linéaires (haute priorité — chemins, murs)
        line_features = [f for f in features if f.is_linear and not f.is_layout]
        for feat in line_features:
            cost = get_terrain_cost(feat.info.terrain_type, environment)
            # Buffer = demi-largeur du trait (variable selon le type)
            buf = _line_buffer_m(feat.info.terrain_type, resolution_m)
            r._paint_line(feat.geom, cost, buffer_m=buf)

        return r

    # ------------------------------------------------------------------
    # Conversion coordonnées ↔ indices raster
    # ------------------------------------------------------------------

    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        """Convertit des coordonnées monde (m) en indices (row, col)."""
        col = int((x - self.bbox.min_x) / self.resolution_m)
        row = int((self.bbox.max_y - y) / self.resolution_m)   # Y inversé
        row = max(0, min(row, self.data.shape[0] - 1))
        col = max(0, min(col, self.data.shape[1] - 1))
        return row, col

    def cell_to_world(self, row: int, col: int) -> tuple[float, float]:
        """Convertit des indices raster en coordonnées monde."""
        x = self.bbox.min_x + col * self.resolution_m + self.resolution_m / 2
        y = self.bbox.max_y - row * self.resolution_m - self.resolution_m / 2
        return x, y

    # ------------------------------------------------------------------
    # Peinture
    # ------------------------------------------------------------------

    def _paint_polygon(self, geom: Any, cost: TerrainCost) -> None:
        """Remplit les cellules couvertes par un polygone."""
        if geom is None:
            return
        raster_cost = cost.to_raster_cost()

        # Bounding box du polygone en cellules
        b = geom.bounds
        r0, c0 = self.world_to_cell(b[0], b[3])   # min_x, max_y
        r1, c1 = self.world_to_cell(b[2], b[1])   # max_x, min_y
        r0, r1 = min(r0, r1), max(r0, r1) + 1
        c0, c1 = min(c0, c1), max(c0, c1) + 1

        rows_total, cols_total = self.data.shape
        for row in range(max(0, r0), min(rows_total, r1)):
            for col in range(max(0, c0), min(cols_total, c1)):
                wx, wy = self.cell_to_world(row, col)
                try:
                    if geom.contains(Point(wx, wy)):
                        self.data[row, col] = raster_cost
                except Exception:
                    pass

    def _paint_line(self, geom: Any, cost: TerrainCost, buffer_m: float) -> None:
        """Peint le buffer d'une feature linéaire."""
        if geom is None or buffer_m < 1e-9:
            return
        try:
            polygon = geom.buffer(buffer_m)
            self._paint_polygon(polygon, cost)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Pathfinding raster
    # ------------------------------------------------------------------

    def path_cost(self, a: Point, b: Point) -> Optional[float]:
        """
        Coût du chemin entre deux points via Dijkstra sur raster.

        Utilise skimage.graph.route_through_array si disponible.
        Retourne None si les points sont hors du raster.

        Le coût retourné est la somme des coûts des cellules traversées,
        multipliée par resolution_m pour obtenir un proxy de temps.
        """
        if not _SKIMAGE_OK:
            # Fallback : estimation directe (sans pathfinding)
            return self._direct_cost_estimate(a, b)

        row_a, col_a = self.world_to_cell(a.x, a.y)
        row_b, col_b = self.world_to_cell(b.x, b.y)

        if (row_a, col_a) == (row_b, col_b):
            return 0.0

        try:
            # Clip les infinis pour route_through_array
            safe_data = np.where(
                np.isinf(self.data), 1e9, self.data
            ).astype(np.float64)

            _, cost = route_through_array(
                safe_data,
                (row_a, col_a),
                (row_b, col_b),
                fully_connected=True,
            )
            return float(cost) * self.resolution_m
        except Exception:
            return None

    def _direct_cost_estimate(self, a: Point, b: Point) -> Optional[float]:
        """Estimation grossière sans pathfinding (somme de cellules sur le segment)."""
        dist = a.distance(b)
        if dist < 1e-9:
            return 0.0
        # Échantillonnage de N points sur le segment
        n_samples = max(2, int(dist / self.resolution_m) + 1)
        total_cost = 0.0
        for i in range(n_samples):
            t = i / (n_samples - 1)
            x = a.x + t * (b.x - a.x)
            y = a.y + t * (b.y - a.y)
            row, col = self.world_to_cell(x, y)
            c = self.data[row, col]
            if np.isinf(c):
                return None   # traversée interdite
            total_cost += c
        return (total_cost / n_samples) * dist

    def cost_at(self, x: float, y: float) -> float:
        """Valeur du raster en un point."""
        row, col = self.world_to_cell(x, y)
        return float(self.data[row, col])

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        h, w = self.data.shape
        return (
            f"CostRaster({w}×{h} @ {self.resolution_m}m, "
            f"bbox=[{self.bbox.min_x:.0f},{self.bbox.min_y:.0f},"
            f"{self.bbox.max_x:.0f},{self.bbox.max_y:.0f}])"
        )


# ---------------------------------------------------------------------------
# Helper : buffer d'une feature linéaire
# ---------------------------------------------------------------------------

def _line_buffer_m(terrain_type: TerrainType, resolution_m: float) -> float:
    """Buffer en mètres pour la peinture d'une feature linéaire."""
    _BUFFERS: dict[TerrainType, float] = {
        TerrainType.ROAD_PAVED:     6.0,
        TerrainType.ROAD_UNPAVED:   5.0,
        TerrainType.ROAD_FOREST:    4.0,
        TerrainType.PATH:           2.5,
        TerrainType.FOOTPATH:       2.0,
        TerrainType.NARROW_RIDE:    1.5,
        TerrainType.WALL:           0.5,
        TerrainType.FENCE:          0.5,
        TerrainType.STREAM:         2.0,
        TerrainType.STREAM_IMPASSABLE: 3.0,
        TerrainType.MARSH:          1.0,
        TerrainType.EARTHWALL:      1.5,
        TerrainType.CLIFF:          1.0,
    }
    return max(resolution_m * 0.5, _BUFFERS.get(terrain_type, resolution_m * 0.5))
