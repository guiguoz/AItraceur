# =============================================
# Terrain Analyzer - Calcul de runnabilité
# Sprint 2: Intégration LIDAR & Terrain Forêt
# =============================================

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .lidar_manager import BoundingBox, LIDARData


# =============================================
# Constants pour la runnabilité
# =============================================

# Vitesses de référence en m/min selon le terrain (pour un coureur moyen)
# Source: Études physiologiques CO
SPEED_REFERENCE = {
    # Forêt - selon densité de végétation et pente
    "forest_flat_easy": 170,  # Forêt plate, peu de Vegetation
    "forest_flat_medium": 140,  # Forêt plate, végétation moyenne
    "forest_flat_hard": 100,  # Forêt plate, végétation dense
    "forest_slope_easy": 130,  # Forêt en pente douce (<10%)
    "forest_slope_medium": 100,  # Forêt en pente (10-20%)
    "forest_slope_hard": 70,  # Forêt en forte pente (>20%)
    # Hors forêt (clairières, routes)
    "open_flat": 180,  # Terrain ouvert plat
    "open_slope": 140,  # Terrain ouvert en pente
    # Chemins
    "path_flat": 200,  # Chemin plat
    "path_slope": 160,  # Chemin en pente
    # Route
    "road": 220,  # Route(goudron)
}

# Coefficients de ralentissement selon la pente
# Pourcentage de ralentissement par tranche de pente
SLOPE_PENALTY = {
    (0, 5): 1.0,  # 0-5%: pas de pénalité
    (5, 10): 0.90,  # 5-10%: 10% de ralentissement
    (10, 15): 0.80,  # 10-15%: 20% de ralentissement
    (15, 20): 0.70,  # 15-20%: 30% de ralentissement
    (20, 25): 0.60,  # 20-25%: 40% de ralentissement
    (25, 30): 0.50,  # 25-30%: 50% de ralentissement
    (30, 100): 0.40,  # >30%: 60% de ralentissement
}

# Coefficients selon la hauteur de végétation
VEGETATION_PENALTY = {
    (0, 0.5): 1.0,  # Sol nu/herbe courte: pas de pénalité
    (0.5, 1.0): 0.95,  # Herbe haute: 5% de ralentissement
    (1.0, 2.0): 0.85,  # Broussailles: 15% de ralentissement
    (2.0, 5.0): 0.70,  # Sous-bois: 30% de ralentissement
    (5.0, 10.0): 0.50,  # Forêt dense: 50% de ralentissement
    (10.0, 100.0): 0.40,  # Très grande forêt: 60% de ralentissement
}


# =============================================
# Structures de données
# =============================================
@dataclass
class TerrainPoint:
    """Un point avec ses caractéristiques de terrain."""

    x: float
    y: float
    elevation: float = 0.0  # Altitude (m)
    slope_percent: float = 0.0  # Pente (%)
    vegetation_height: float = 0.0  # Hauteur végétation (m)
    is_path: bool = False  # Sur un chemin?
    is_open: bool = True  # Terrain dégagé?

    @property
    def speed_factor(self) -> float:
        """Calcule le facteur de vitesse (0-1)."""
        # Facteur pente
        slope_factor = 1.0
        for (min_slope, max_slope), penalty in SLOPE_PENALTY.items():
            if min_slope <= self.slope_percent < max_slope:
                slope_factor = penalty
                break

        # Facteur végétation
        veg_factor = 1.0
        for (min_h, max_h), penalty in VEGETATION_PENALTY.items():
            if min_h <= self.vegetation_height < max_h:
                veg_factor = penalty
                break

        # Facteur chemin (bonus)
        path_factor = 1.3 if self.is_path else 1.0

        # Facteur ouvert (bonus)
        open_factor = 1.0 if self.is_open else 0.8

        return slope_factor * veg_factor * path_factor * open_factor

    @property
    def speed_mpm(self) -> float:
        """Vitesse estimée en m/min."""
        base_speed = SPEED_REFERENCE.get("forest_flat_medium", 140)
        return base_speed * self.speed_factor


@dataclass
class RunnabilityMap:
    """Carte de runnabilité pour une zone."""

    bounding_box: BoundingBox
    resolution: float = 10.0  # Résolution en mètres (10m = 100x100 pour 1km²)
    grid: List[List[float]] = field(default_factory=list)
    max_speed: float = 220.0  # Vitesse max sur route
    min_speed: float = 40.0  # Vitesse min en forêt dense
    created_at: str = ""


# =============================================
# Analyseur de terrain
# =============================================
class TerrainAnalyzer:
    """
    Analyseur de terrain pour calculer la runnabilité.

    Utilise les données LIDAR (DTM, DSM, végétation) pour estimer
    la vitesse de déplacement sur chaque point du terrain.
    """

    def __init__(self):
        """Initialise l'analyseur."""
        self.lidar_data: Optional[LIDARData] = None
        self.runnability_map: Optional[RunnabilityMap] = None

    def load_lidar_data(self, lidar_data: LIDARData) -> None:
        """
        Charge les données LIDAR.

        Args:
            lidar_data: Données LIDAR récupérées par le LIDARManager
        """
        self.lidar_data = lidar_data
        print(f"✓ Données LIDAR chargées: {len(lidar_data.tiles)} tuile(s)")

    def calculate_slope(
        self, x1: float, y1: float, x2: float, y2: float, elevation_diff: float
    ) -> float:
        """
        Calcule la pente entre deux points.

        Args:
            x1, y1: Coordonnées point 1
            x2, y2: Coordonnées point 2
            elevation_diff: Différence d'altitude

        Returns:
            Pente en pourcentage
        """
        # Distance horizontale
        distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

        if distance == 0:
            return 0.0

        # Pente en %
        slope = (elevation_diff / distance) * 100

        return abs(slope)

    def estimate_vegetation_height(self, dsm: float, dtm: float) -> float:
        """
        Estime la hauteur de végétation.

        Args:
            DSM: Digital Surface Model (sol + végétation)
            DTM: Digital Terrain Model (sol nu)

        Returns:
            Hauteur de végétation en mètres
        """
        height = dsm - dtm
        return max(0.0, height)

    def is_on_path(self, x: float, y: float, paths_data: Dict) -> bool:
        """
        Détermine si un point est sur un chemin.

        NOTE: En réalité, utiliserait les données OSM ou la carte OCAD.

        Args:
            x, y: Coordonnées du point
            paths_data: Données des chemins (à récupérer)

        Returns:
            True si sur un chemin
        """
        # Simulation: en réalité, vérifierait la distance aux chemins
        # Pour la démo, retourner False
        return False

    def is_open_terrain(self, vegetation_height: float) -> bool:
        """
        Détermine si le terrain est dégagé.

        Args:
            vegetation_height: Hauteur de végétation

        Returns:
            True si terrain dégagé (< 1m de végétation)
        """
        return vegetation_height < 1.0

    def calculate_point(
        self, x: float, y: float, dtm: float = 0, dsm: float = 0
    ) -> TerrainPoint:
        """
        Calcule les caractéristiques d'un point.

        Args:
            x, y: Coordonnées
            dtm: Altitude du sol nu
            dsm: Altitude surface (sol + végétation)

        Returns:
            TerrainPoint avec toutes les caractéristiques
        """
        veg_height = self.estimate_vegetation_height(dsm, dtm)

        # Pour la démo, on simule la pente
        # En réalité, calculerait à partir du DTM
        slope = 5.0  # Valeur simulée

        point = TerrainPoint(
            x=x,
            y=y,
            elevation=dtm,
            slope_percent=slope,
            vegetation_height=veg_height,
            is_path=self.is_on_path(x, y, {}),
            is_open=self.is_open_terrain(veg_height),
        )

        return point

    def generate_runnability_map(
        self, bbox: BoundingBox, resolution: float = 10.0
    ) -> RunnabilityMap:
        """
        Génère une carte de runnabilité pour une zone.

        Args:
            bbox: Emprise géographique
            resolution: Résolution de la grille en mètres

        Returns:
            RunnabilityMap avec les vitesses estimées
        """
        print(f"🗺️ Génération carte runnabilité {bbox.width}x{bbox.height}m...")

        # Calculer les dimensions de la grille
        width_cells = int(bbox.width / resolution) + 1
        height_cells = int(bbox.height / resolution) + 1

        grid: List[List[float]] = []

        # Pour chaque point de la grille
        for row in range(height_cells):
            grid_row = []
            y = bbox.min_y + row * resolution

            for col in range(width_cells):
                x = bbox.min_x + col * resolution

                # Calculer les caractéristiques du point
                # En réalité, lirait les rasters LIDAR
                point = self.calculate_point(x, y)

                # Stocker la vitesse
                grid_row.append(point.speed_mpm)

            grid.append(grid_row)

        # Créer la carte de runnabilité
        self.runnability_map = RunnabilityMap(
            bounding_box=bbox,
            resolution=resolution,
            grid=grid,
            max_speed=220.0,
            min_speed=min(min(row) for row in grid) if grid else 40.0,
        )

        print(f"✓ Carte générée: {width_cells}x{height_cells} points")

        return self.runnability_map

    def estimate_time(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        path_points: Optional[List[Tuple[float, float]]] = None,
    ) -> Dict[str, float]:
        """
        Estime le temps de parcours entre deux points.

        Args:
            start: Point de départ (x, y)
            end: Point d'arrivée (x, y)
            path_points: Points intermédiaires du chemin (optionnel)

        Returns:
            Dict avec distance, temps estimé, vitesse moyenne
        """
        if path_points is None:
            # Ligne droite
            path_points = [start, end]

        # Calculer la distance totale
        total_distance = 0.0
        for i in range(len(path_points) - 1):
            x1, y1 = path_points[i]
            x2, y2 = path_points[i + 1]
            dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            total_distance += dist

        # Estimer le temps moyen
        # Pour simplifier, utiliser la vitesse moyenne
        if self.runnability_map:
            avg_speed = (
                self.runnability_map.max_speed + self.runnability_map.min_speed
            ) / 2
        else:
            avg_speed = 140  # Vitesse par défaut

        time_minutes = total_distance / avg_speed

        return {
            "distance_meters": total_distance,
            "time_minutes": time_minutes,
            "average_speed_mpm": avg_speed,
            "path_type": "straight_line" if path_points is None else "optimal_route",
        }

    def find_optimal_route(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        obstacles: Optional[List[BoundingBox]] = None,
    ) -> List[Tuple[float, float]]:
        """
        Trouve un itinéraire optimal en tenant compte du terrain.

        NOTE: En réalité, utiliserait A* ou Dijkstra sur un graphe
        de navigation avec les coûts de runnabilité.

        Args:
            start: Point de départ
            end: Point d'arrivée
            obstacles: Zones à éviter

        Returns:
            Liste de points constituant l'itinéraire
        """
        # Simulation: retourne une ligne droite
        # En réalité, implémenterait un algorithme de routage
        return [start, end]


# =============================================
# Fonction utilitaire
# =============================================
def calculate_runnability_score(
    slope_percent: float,
    vegetation_height: float,
    is_path: bool = False,
    is_open: bool = True,
) -> float:
    """
    Calcule un score de runnabilité (0-1).

    Args:
        slope_percent: Pente en %
        vegetation_height: Hauteur végétation en m
        is_path: Est sur un chemin?
        is_open: Terrain dégagé?

    Returns:
        Score entre 0 (infranchissable) et 1 (optimal)
    """
    # Score de pente
    slope_score = 1.0
    for (min_s, max_s), penalty in SLOPE_PENALTY.items():
        if min_s <= slope_percent < max_s:
            slope_score = penalty
            break

    # Score de végétation
    veg_score = 1.0
    for (min_h, max_h), penalty in VEGETATION_PENALTY.items():
        if min_h <= vegetation_height < max_h:
            veg_score = penalty
            break

    # Bonus chemin
    path_bonus = 1.2 if is_path else 1.0

    # Bonus ouvert
    open_bonus = 1.1 if is_open else 1.0

    return min(1.0, slope_score * veg_score * path_bonus * open_bonus)
