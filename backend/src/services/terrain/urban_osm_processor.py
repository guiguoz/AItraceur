# =============================================
# Processeur OSM pour environnement urbain
# Sprint 8: Support Ville/Sprint
# =============================================

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# =============================================
# Types de données
# =============================================
@dataclass
class UrbanFeature:
    """Une caractéristique urbaine."""

    feature_type: str  # "building", "fence", "stair", "obstacle"
    location: Tuple[float, float]
    properties: Dict = field(default_factory=dict)


@dataclass
class UrbanRunnability:
    """Carte de runnability urbaine."""

    grid: List[List[float]]  # Grille de runnability (0-1)
    resolution: float  # mètres par cellule
    bounding_box: Dict

    # Stats
    paved_percentage: float = 0.0
    obstacle_count: int = 0
    avg_speed_mpm: float = 200.0


# =============================================
# Processeur urbain
# =============================================
class UrbanOSMProcessor:
    """
    Traite les données OSM pour un environnement urbain/sprint.

    Calcule la runnability en ville en fonction:
    - Type de surface (asphalte, pavés, terre)
    - Obstacles (murs, clôtures, escaliers)
    - Mobilier urbain
    - Trafic (routes)
    """

    # Vitesses de base en m/min pour urbain
    URBAN_SPEEDS = {
        # Surfaces
        "asphalt": 300,  # Route asphaltée
        "paved": 250,  # Pavés
        "concrete": 280,  # Béton
        "gravel": 150,  # Gravier
        "grass": 120,  # Herbe
        "dirt": 100,  # Terre
        # Chemins
        "footway": 200,  # Trottoir
        "path": 150,  # Sentier
        "steps": 80,  # Escaliers
        # Obstacles
        "wall": 0,  # Mur infranchissable
        "fence": 10,  # Clôture
        "hedge": 20,  # Haie
        "building": 0,  # Bâtiment
        # Eau
        "water": 0,
        "stream": 10,
    }

    # Distances de sécurité (m)
    SAFETY_DISTANCES = {
        "primary_road": 50,
        "secondary_road": 30,
        "tertiary_road": 20,
        "residential_road": 10,
        "railway": 30,
        "private": 5,
    }

    def __init__(self):
        """Initialise le processeur."""
        self.osm_data = None

    def load_osm_data(self, osm_data: Dict):
        """Charge les données OSM."""
        self.osm_data = osm_data

    def calculate_runnability(
        self,
        bounding_box: Dict,
        resolution: float = 5.0,  # 5m pour urbain
    ) -> UrbanRunnability:
        """
        Calcule la runnability urbaine.

        Args:
            bounding_box: {min_x, min_y, max_x, max_y}
            resolution: Résolution de la grille en mètres

        Returns:
            UrbanRunnability
        """
        # Dimensions de la grille
        width = int((bounding_box["max_x"] - bounding_box["min_x"]) / resolution)
        height = int((bounding_box["max_y"] - bounding_box["min_y"]) / resolution)

        # Initialiser la grille (forêt par défaut = runnability moyenne)
        grid = [[0.5 for _ in range(width)] for _ in range(height)]

        # Appliquer les modifiers
        if self.osm_data:
            # Routes (forte runnability)
            self._apply_roads(grid, bounding_box, resolution)

            # Bâtiments (zéro runnability)
            self._apply_buildings(grid, bounding_box, resolution)

            # Obstacles (faible runnability)
            self._apply_barriers(grid, bounding_box, resolution)

            # Zones vertes
            self._apply_green_areas(grid, bounding_box, resolution)

        # Calculer les statistiques
        paved, obstacle_count = self._calculate_stats(grid)

        return UrbanRunnability(
            grid=grid,
            resolution=resolution,
            bounding_box=bounding_box,
            paved_percentage=paved,
            obstacle_count=obstacle_count,
            avg_speed_mpm=self._calculate_avg_speed(grid),
        )

    def _apply_roads(
        self,
        grid: List[List[float]],
        bounding_box: Dict,
        resolution: float,
    ):
        """Applique les routes à la grille."""
        roads = self.osm_data.get("roads", [])

        for road in roads:
            road_type = road.get("type", "unclassified")
            points = road.get("points", [])

            # Déterminer la vitesse
            speed = self.URBAN_SPEEDS.get(road_type, 150)
            runnability = speed / 300  # Normaliser (max 300)

            # Appliquer à chaque point
            for point in points:
                gx = int((point[0] - bounding_box["min_x"]) / resolution)
                gy = int((point[1] - bounding_box["min_y"]) / resolution)

                if 0 <= gx < len(grid[0]) and 0 <= gy < len(grid):
                    grid[gy][gx] = max(grid[gy][gx], runnability)

    def _apply_buildings(
        self,
        grid: List[List[float]],
        bounding_box: Dict,
        resolution: float,
    ):
        """Applique les bâtiments à la grille."""
        buildings = self.osm_data.get("buildings", [])

        for building in buildings:
            # Obtenir le centre ou les points
            center = building.get("center", building.get("points", [[0, 0]])[0])

            # Taille estimée (ou depuis les tags)
            height = building.get("height", 10)  # défaut 10m
            width = building.get("width", 10)

            # Rayon en cellules
            radius = int(max(width, height) / resolution) + 1

            gx = int((center[0] - bounding_box["min_x"]) / resolution)
            gy = int((center[1] - bounding_box["min_y"]) / resolution)

            # Marquer comme infranchissable
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, ny = gx + dx, gy + dy
                    if 0 <= nx < len(grid[0]) and 0 <= ny < len(grid):
                        grid[ny][nx] = 0.0

    def _apply_barriers(
        self,
        grid: List[List[float]],
        bounding_box: Dict,
        resolution: float,
    ):
        """Applique les barrières à la grille."""
        barriers = self.osm_data.get("barriers", [])

        for barrier in barriers:
            barrier_type = barrier.get("type", "wall")
            points = barrier.get("points", [])

            # Vitesse selon le type
            speed = self.URBAN_SPEEDS.get(barrier_type, 10)
            runnability = speed / 300

            for point in points:
                gx = int((point[0] - bounding_box["min_x"]) / resolution)
                gy = int((point[1] - bounding_box["min_y"]) / resolution)

                if 0 <= gx < len(grid[0]) and 0 <= gy < len(grid):
                    # Réduire la runnability autour des barrières
                    for dy in range(-1, 2):
                        for dx in range(-1, 2):
                            nx, ny = gx + dx, gy + dy
                            if 0 <= nx < len(grid[0]) and 0 <= ny < len(grid):
                                grid[ny][nx] = min(grid[ny][nx], runnability)

    def _apply_green_areas(
        self,
        grid: List[List[float]],
        bounding_box: Dict,
        resolution: float,
    ):
        """Applique les zones vertes."""
        green_areas = self.osm_data.get("green_areas", [])

        for area in green_areas:
            area_type = area.get("type", "park")
            points = area.get("points", [])

            if not points:
                continue

            # Runnability selon le type
            if area_type == "park":
                runnability = 0.7
            elif area_type == "garden":
                runnability = 0.5
            else:
                runnability = 0.4

            # Appliquer à la zone (approximation par centroid)
            center = points[0]  # Simplifié
            gx = int((center[0] - bounding_box["min_x"]) / resolution)
            gy = int((center[1] - bounding_box["min_y"]) / resolution)

            if 0 <= gx < len(grid[0]) and 0 <= gy < len(grid):
                grid[gy][gx] = runnability

    def _calculate_stats(self, grid: List[List[float]]) -> Tuple[float, int]:
        """Calcule les statistiques."""
        total_cells = len(grid) * len(grid[0])
        paved_cells = sum(1 for row in grid for cell in row if cell > 0.7)
        obstacle_cells = sum(1 for row in grid for cell in row if cell < 0.1)

        paved_pct = (padded_cells / total_cells * 100) if total_cells > 0 else 0

        return paved_pct, obstacle_cells

    def _calculate_avg_speed(self, grid: List[List[float]]) -> float:
        """Calcule la vitesse moyenne."""
        all_cells = [cell for row in grid for cell in row]
        if not all_cells:
            return 200.0

        avg = sum(all_cells) / len(all_cells)
        return avg * 300  # Convertir en m/min

    def get_safety_zones(self) -> List[Dict]:
        """
        Retourne les zones de sécurité à éviter.

        Pour sprint: routes à fort trafic, zones privées, voies ferrées.
        """
        zones = []

        # Routes dangereuses
        roads = self.osm_data.get("roads", [])
        for road in roads:
            road_type = road.get("type", "")

            if road_type in ["motorway", "trunk", "primary"]:
                distance = self.SAFETY_DISTANCES.get("primary_road", 50)
                zones.append(
                    {
                        "type": "road_dangerous",
                        "severity": "high",
                        "distance": distance,
                        "points": road.get("points", []),
                    }
                )

        # Zones privées
        restricted = self.osm_data.get("restricted", [])
        for zone in restricted:
            zones.append(
                {
                    "type": "private",
                    "severity": "high",
                    "distance": 5,
                    "points": zone.get("points", []),
                }
            )

        return zones

    def get_control_valid_positions(
        self,
        bounding_box: Dict,
        min_distance_from_obstacles: float = 5.0,
    ) -> List[Tuple[float, float]]:
        """
        Trouve les positions valides pour les postes en sprint.

        Args:
            bounding_box: Zone de recherche
            min_distance: Distance minimale aux obstacles

        Returns:
            Liste de positions valides (x, y)
        """
        # Calculer la runnability
        runnability = self.calculate_runnability(bounding_box, resolution=5.0)

        valid_positions = []

        # Chercher les points avec bonne runnability
        for gy, row in enumerate(runnability.grid):
            for gx, value in enumerate(row):
                # Bon pour un poste?
                if 0.3 <= value <= 0.9:  # Ni trop facile, ni infranchissable
                    x = bounding_box["min_x"] + gx * runnability.resolution
                    y = bounding_box["min_y"] + gy * runnability.resolution
                    valid_positions.append((x, y))

        return valid_positions


# =============================================
# Détecteur de positions pour urbain
# =============================================
class UrbanControlDetector:
    """
    Détecte les positions valides pour les postes en environnement urbain.

    Suit les règles ISSprOM 2019.
    """

    # Règles ISSprOM pour les postes
    ISSPROM_RULES = {
        "min_distance_between_controls": 25,  # m
        "min_distance_from_obstacles": 3,  # m
        "max_distance_from_path": 50,  # m - poste pas trop loin du chemin
        "forbidden_locations": [
            "private",
            "military",
            "construction",
        ],
    }

    def __init__(self):
        """Initialise le détecteur."""
        self.processor = UrbanOSMProcessor()

    def load_osm_data(self, osm_data: Dict):
        """Charge les données OSM."""
        self.processor.load_osm_data(osm_data)

    def find_valid_positions(
        self,
        bounding_box: Dict,
        num_positions: int = 20,
    ) -> List[Dict]:
        """
        Trouve des positions valides pour les postes.

        Args:
            bounding_box: Zone de recherche
            num_positions: Nombre de positions souhaitées

        Returns:
            Liste de positions valides
        """
        # Obtenir toutes les positions valides
        positions = self.processor.get_control_valid_positions(bounding_box)

        if not positions:
            return []

        # Filtrer selon les règles ISSprOM
        valid = []

        for pos in positions:
            if self._is_valid_position(pos, bounding_box):
                valid.append(
                    {
                        "x": pos[0],
                        "y": pos[1],
                        "reason": "valid",
                    }
                )

                if len(valid) >= num_positions:
                    break

        return valid

    def _is_valid_position(
        self,
        position: Tuple[float, float],
        bounding_box: Dict,
    ) -> bool:
        """Vérifie si une position est valide."""
        # Vérifier qu'elle est dans la bounding box
        if not (
            bounding_box["min_x"] <= position[0] <= bounding_box["max_x"]
            and bounding_box["min_y"] <= position[1] <= bounding_box["max_y"]
        ):
            return False

        # Vérifier la distance aux obstacles
        # (simplifié - dans la réalité, calculer depuis OSM)

        return True

    def check_sprint_rules(
        self,
        controls: List[Dict],
        category: str = "sprint",
    ) -> List[Dict]:
        """
        Vérifie qu'un circuit sprint respecte les règles ISSprOM.

        Args:
            controls: Liste des postes
            category: Catégorie du circuit

        Returns:
            Liste des problèmes détectés
        """
        issues = []

        # Vérifier distance minimale entre postes
        for i in range(len(controls)):
            for j in range(i + 1, len(controls)):
                dist = self._calculate_distance(
                    (controls[i]["x"], controls[i]["y"]),
                    (controls[j]["x"], controls[j]["y"]),
                )

                if dist < self.ISSPROM_RULES["min_distance_between_controls"]:
                    issues.append(
                        {
                            "type": "controls_too_close",
                            "severity": "high",
                            "description": f"Postes {controls[i]['order']} et {controls[j]['order']} trop proches: {dist:.0f}m",
                            "control_ids": [controls[i]["id"], controls[j]["id"]],
                        }
                    )

        return issues

    def _calculate_distance(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
    ) -> float:
        """Calcule la distance."""
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)
