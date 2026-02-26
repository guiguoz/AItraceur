# =============================================
# RouteAI Integration - Path Finding & Map Processing
# Basé sur https://github.com/Jekblade/RouteAI
# =============================================

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import heapq


# =============================================
# Types de données
# =============================================
@dataclass
class GridNode:
    """Un nœud dans la grille de la carte."""

    x: int
    y: int
    cost: float = 1.0  # Co (basût de passageé sur la couleur)
    terrain_type: str = "unknown"  # "forest", "open", "path", "building"
    walkable: bool = True


@dataclass
class PathResult:
    """Résultat d'un calcul de chemin."""

    path: List[Tuple[float, float]]  # Liste des points (x, y)
    distance: float
    time_estimate: float
    method: str  # "dijkstra", "a_star", "best_first"


# =============================================
# Processeur de carte (MapConvert)
# =============================================
class MapProcessor:
    """
    Traite une image de carte pour créer une grille de navigation.

    Convertit une carte PNG en grille de pixels avec coûts de passage.
    """

    # Couleurs typiques ISOM (forêt)
    TERRAIN_COLORS = {
        # Végétation (verts)
        (34, 139, 34): ("dense_forest", 0.3),  # Forêt dense
        (50, 205, 50): ("light_forest", 0.5),  # Forêt légère
        (144, 238, 144): ("clear_forest", 0.7),  # Forêt dégagée
        # Terrain ouvert (jaunes)
        (255, 255, 224): ("open", 0.9),  # Terrain ouvert
        (255, 255, 0): ("rough_open", 0.8),  # Terrain difficle
        # Eau (bleu)
        (0, 0, 255): ("water", 0.1),  # Eau (infranchissable)
        (173, 216, 230): ("stream", 0.3),  # Ruisseau
        # Routes/Chemins (noir/blanc)
        (0, 0, 0): ("path", 1.0),  # Chemin
        (128, 128, 128): ("road", 1.0),  # Route
        (255, 255, 255): ("white", 0.9),  # Blanc
        # Bâtiments (gris)
        (100, 100, 100): ("building", 0.1),  # Bâtiment
        (150, 150, 150): ("wall", 0.1),  # Mur
    }

    # Pour sprint (ISSprOM)
    SPRINT_COLORS = {
        (50, 50, 50): ("building", 0.1),
        (200, 200, 200): ("pavement", 0.9),
        (255, 255, 255): ("open", 0.9),
        (0, 0, 0): ("fence", 0.1),
        (139, 69, 19): ("stair", 0.5),
    }

    def __init__(self):
        """Initialise le processeur."""
        self.grid: List[List[GridNode]] = []
        self.width: int = 0
        self.height: int = 0
        self.resolution: float = 1.0  # mètres par pixel

    def load_from_image(
        self,
        image_path: str,
        map_type: str = "forest",
    ) -> bool:
        """
        Charge une image et la convertit en grille.

        Args:
            image_path: Chemin vers l'image PNG
            map_type: Type de carte (forest, sprint)

        Returns:
            True si succès
        """
        try:
            from PIL import Image
            import numpy as np

            # Charger l'image
            img = Image.open(image_path)
            img = img.convert("RGB")

            self.width, self.height = img.size
            pixels = np.array(img)

            # Définir les couleurs selon le type
            colors = self.TERRAIN_COLORS if map_type == "forest" else self.SPRINT_COLORS

            # Créer la grille
            self.grid = []

            for y in range(self.height):
                row = []
                for x in range(self.width):
                    pixel = tuple(pixels[y, x])

                    # Trouver la couleur la plus proche
                    terrain, cost = self._find_nearest_color(pixel, colors)

                    node = GridNode(
                        x=x,
                        y=y,
                        cost=cost,
                        terrain_type=terrain,
                        walkable=cost > 0.1,  # walkable = coût > 0.1
                    )
                    row.append(node)

                self.grid.append(row)

            return True

        except Exception as e:
            print(f"Erreur chargement image: {e}")
            return False

    def load_from_osm(
        self,
        osm_data: Dict,
        bounding_box: Dict,
        resolution: float = 10.0,  # 10m par cellule
    ) -> bool:
        """
        Crée une grille depuis les données OSM.

        Args:
            osm_data: Données OSM
            bounding_box: {min_x, min_y, max_x, max_y}
            resolution: Résolution en mètres

        Returns:
            True si succès
        """
        # Calculer les dimensions
        width = int((bounding_box["max_x"] - bounding_box["min_x"]) / resolution)
        height = int((bounding_box["max_y"] - bounding_box["min_y"]) / resolution)

        self.width = width
        self.height = height
        self.resolution = resolution

        # Initialiser la grille (forêt par défaut)
        self.grid = []
        for y in range(height):
            row = []
            for x in range(width):
                # Coordonnées réelles
                real_x = bounding_box["min_x"] + x * resolution
                real_y = bounding_box["min_y"] + y * resolution

                node = GridNode(
                    x=x,
                    y=y,
                    cost=0.5,  # Forêt par défaut
                    terrain_type="forest",
                    walkable=True,
                )
                row.append(node)
            self.grid.append(row)

        return True

    def _find_nearest_color(
        self,
        pixel: Tuple[int, int, int],
        color_map: Dict,
    ) -> Tuple[str, float]:
        """Trouve la couleur la plus proche."""
        min_dist = float("inf")
        nearest = ("unknown", 0.5)

        for color, (terrain, cost) in color_map.items():
            dist = math.sqrt(
                (pixel[0] - color[0]) ** 2
                + (pixel[1] - color[1]) ** 2
                + (pixel[2] - color[2]) ** 2
            )
            if dist < min_dist:
                min_dist = dist
                nearest = (terrain, cost)

        return nearest

    def get_node(self, x: int, y: int) -> Optional[GridNode]:
        """Récupère un nœud."""
        if 0 <= y < self.height and 0 <= x < self.width:
            return self.grid[y][x]
        return None

    def get_neighbors(self, x: int, y: int) -> List[GridNode]:
        """Récupère les nœuds adjacents (8-connectivité)."""
        neighbors = []

        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue

                nx, ny = x + dx, y + dy
                node = self.get_node(nx, ny)

                if node and node.walkable:
                    # Coût diagonal = sqrt(2)
                    if dx != 0 and dy != 0:
                        node.cost *= 1.414
                    neighbors.append(node)

        return neighbors


# =============================================
# Path Finding (RouteAI的核心)
# =============================================
class PathFinder:
    """
    Algorithmes de recherche de chemin.

    Implémente Dijkstra, A*, Best-First Search.
    """

    def __init__(self, grid: MapProcessor = None):
        """
        Initialise le pathfinder.

        Args:
            grid: Grille de navigation
        """
        self.grid = grid

    def set_grid(self, grid: MapProcessor):
        """Définit la grille."""
        self.grid = grid

    def find_path(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        method: str = "a_star",
    ) -> Optional[PathResult]:
        """
        Trouve le chemin optimal.

        Args:
            start: (x, y) point de départ
            end: (x, y) point d'arrivée
            method: Algorithme (dijkstra, a_star, best_first)

        Returns:
            PathResult avec le chemin
        """
        if not self.grid:
            return None

        # Convertir en coordonnées grille
        start_node = self._world_to_grid(start[0], start[1])
        end_node = self._world_to_grid(end[0], end[1])

        if not start_node or not end_node:
            return None

        # Appliquer l'algorithme
        if method == "dijkstra":
            path = self._dijkstra(start_node, end_node)
        elif method == "a_star":
            path = self._a_star(start_node, end_node)
        elif method == "best_first":
            path = self._best_first(start_node, end_node)
        else:
            return None

        if not path:
            return None

        # Convertir en coordonnées réelles
        real_path = [(self._grid_to_world(n.x, n.y)) for n in path]

        # Calculer la distance
        distance = self._calculate_path_distance(real_path)

        # Estimer le temps (basé sur les coûts)
        time_estimate = self._estimate_time(path)

        return PathResult(
            path=real_path,
            distance=distance,
            time_estimate=time_estimate,
            method=method,
        )

    def find_path_with_waypoints(
        self,
        waypoints: List[Tuple[float, float]],
        method: str = "a_star",
    ) -> PathResult:
        """
        Trouve le chemin à travers plusieurs points de passage.

        Args:
            waypoints: Liste de points [(x1,y1), (x2,y2), ...]
            method: Algorithme

        Returns:
            Chemin complet
        """
        if not waypoints or len(waypoints) < 2:
            return None

        full_path = []
        total_distance = 0
        total_time = 0

        for i in range(len(waypoints) - 1):
            result = self.find_path(waypoints[i], waypoints[i + 1], method)

            if not result:
                return None

            # Ajouter le chemin (sauf le dernier point qui est le suivant)
            full_path.extend(result.path[:-1])
            total_distance += result.distance
            total_time += result.time_estimate

        # Ajouter le dernier point
        full_path.append(waypoints[-1])

        return PathResult(
            path=full_path,
            distance=total_distance,
            time_estimate=total_time,
            method=method,
        )

    def _world_to_grid(self, x: float, y: float) -> Optional[GridNode]:
        """Convertit coordonnées monde → grille."""
        if not self.grid:
            return None

        # Supposons que 0,0 monde = 0,0 grille
        # À ajuster selon le référentiel de la carte
        gx = int(x)
        gy = int(y)

        return self.grid.get_node(gx, gy)

    def _grid_to_world(self, x: int, y: int) -> Tuple[float, float]:
        """Convertit coordonnées grille → monde."""
        return (float(x), float(y))

    def _dijkstra(
        self,
        start: GridNode,
        end: GridNode,
    ) -> Optional[List[GridNode]]:
        """Algorithme de Dijkstra."""
        # Distance initiale
        distances = {start: 0}
        previous = {(start.x, start.y): None}
        visited = set()
        pq = [(0, start)]

        while pq:
            current_dist, current = heapq.heappop(pq)

            if current in visited:
                continue

            visited.add(current)

            if current_pos == (end.x, end.y):
                return self._reconstruct_path(previous, (end.x, end.y))

            # Explorer les voisins
            neighbors = self.grid.get_neighbors(current.x, current.y)

            for neighbor in neighbors:
                if neighbor in visited:
                    continue

                # Coût = distance × coût du terrain
                dist = current_dist + 1 * neighbor.cost

                if neighbor not in distances or dist < distances[neighbor]:
                    distances[neighbor] = dist
                    previous[neighbor_pos] = current_pos
                    heapq.heappush(pq, (dist, neighbor))

        return None

    def _a_star(
        self,
        start: GridNode,
        end: GridNode,
    ) -> Optional[List[GridNode]]:
        """Algorithme A*."""
        # f_score = g_score + h_score (heuristique)
        g_scores = {(start.x, start.y): 0}
        f_scores = {(start.x, start.y): self._heuristic(start, end)}
        previous = {(start.x, start.y): None}
        import itertools; counter = itertools.count(); open_set = [(f_scores[(start.x, start.y)], next(counter), (start.x, start.y))]

        while open_set:
            _, _, current_pos = heapq.heappop(open_set); current = self.grid.get_node(*current_pos)

            if current_pos == (end.x, end.y):
                return self._reconstruct_path(previous, (end.x, end.y))

            # Explorer les voisins
            neighbors = self.grid.get_neighbors(current.x, current.y)

            for neighbor in neighbors:
                # g_score temporaire
                neighbor_pos = (neighbor.x, neighbor.y); tentative_g = g_scores[current_pos] + 1 * neighbor.cost

                if neighbor_pos not in g_scores or tentative_g < g_scores[neighbor_pos]:
                    previous[neighbor_pos] = current_pos
                    g_scores[neighbor_pos] = tentative_g
                    f = tentative_g + self._heuristic(neighbor, end)
                    f_scores[neighbor_pos] = f
                    heapq.heappush(open_set, (f, next(counter), neighbor_pos))

        return None

    def _best_first(
        self,
        start: GridNode,
        end: GridNode,
    ) -> Optional[List[GridNode]]:
        """Best-First Search (seulement heuristique)."""
        previous = {(start.x, start.y): None}
        open_set = [(self._heuristic(start, end), start)]
        visited = set()

        while open_set:
            _, _, current_pos = heapq.heappop(open_set); current = self.grid.get_node(*current_pos)

            if current in visited:
                continue
            visited.add(current)

            if current_pos == (end.x, end.y):
                return self._reconstruct_path(previous, (end.x, end.y))

            neighbors = self.grid.get_neighbors(current.x, current.y)

            for neighbor in neighbors:
                if neighbor not in visited:
                    previous[neighbor_pos] = current_pos
                    heapq.heappush(open_set, (self._heuristic(neighbor, end), neighbor))

        return None

    def _heuristic(self, node: GridNode, goal: GridNode) -> float:
        """Heuristique (distance euclidienne)."""
        return math.sqrt((node.x - goal.x) ** 2 + (node.y - goal.y) ** 2)

    def _reconstruct_path(self, previous: Dict, end_pos: Tuple[int, int]) -> List[GridNode]:
        path = []
        current_pos = end_pos
        while current_pos:
            node = self.grid.get_node(*current_pos)
            if node: path.append(node)
            current_pos = previous.get(current_pos)
        path.reverse()
        return path
    def _old_reconstruct_path(
        self,
        previous: Dict,
        end: GridNode,
    ) -> List[GridNode]:
        """Reconstruit le chemin."""
        path = []
        current = end

        while current:
            path.append(current)
            current = previous.get(current)

        path.reverse()
        return path

    def _calculate_path_distance(self, path: List[Tuple[float, float]]) -> float:
        """Calcule la distance totale."""
        total = 0

        for i in range(len(path) - 1):
            dx = path[i + 1][0] - path[i][0]
            dy = path[i + 1][1] - path[i][1]
            total += math.sqrt(dx * dx + dy * dy) * self.grid.resolution

        return total

    def _estimate_time(self, path: List[GridNode]) -> float:
        """Estime le temps de parcours (en minutes)."""
        # Vitesse de base: 150 m/min (terrain moyen)
        base_speed = 150

        total_cost = 0
        for node in path:
            # Plus le coût est bas, plus c'est rapide
            total_cost += node.cost

        # Temps = distance / vitesse
        time_min = (len(path) * self.grid.resolution) / base_speed

        return time_min


# =============================================
# TSP Solver (pour Rogaining)
# =============================================
class TSPSolver:
    """
    Solveur du Problème du Voyageur de Commerce.

    Utilisé pour ordonner les postes en rogaining.
    """

    def __init__(self, path_finder: PathFinder = None):
        """Initialise le solveur."""
        self.path_finder = path_finder

    def solve(
        self,
        controls: List[Tuple[float, float]],
        start: Tuple[float, float] = None,
        method: str = "nearest",
    ) -> List[Tuple[float, float]]:
        """
        Résout le TSP pour les contrôles.

        Args:
            controls: Liste des points à visiter
            start: Point de départ (optionnel)
            method: Méthode (nearest, 2opt, greedy)

        Returns:
            Ordre optimal des points
        """
        if not controls:
            return []

        if start:
            points = [start] + controls
        else:
            points = controls

        if method == "nearest":
            return self._nearest_neighbor(points)
        elif method == "greedy":
            return self._greedy(points)
        elif method == "2opt":
            return self._2opt(points)
        else:
            return points

    def _nearest_neighbor(
        self, points: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """Plus proche voisin."""
        if not points:
            return []

        unvisited = set(points[1:])  # Tous sauf le départ
        current = points[0]
        path = [current]

        while unvisited:
            nearest = min(unvisited, key=lambda p: self._distance(current, p))
            path.append(nearest)
            unvisited.remove(nearest)
            current = nearest

        return path

    def _greedy(self, points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """Algorithme glouton (Minimum Spanning Tree)."""
        # Pour l'instant, utiliser nearest neighbor
        return self._nearest_neighbor(points)

    def _2opt(
        self, points: List[Tuple[float, float]], max_iter: int = 100
    ) -> List[Tuple[float, float]]:
        """2-opt optimization."""
        if len(points) < 4:
            return points

        # Commencer avec nearest neighbor
        path = self._nearest_neighbor(points)
        improved = True
        iterations = 0

        while improved and iterations < max_iter:
            improved = False
            iterations += 1

            for i in range(1, len(path) - 2):
                for j in range(i + 1, len(path)):
                    if j - i == 1:
                        continue

                    # Tester l'échange
                    new_path = path[:i] + path[i:j][::-1] + path[j:]

                    if self._total_distance(new_path) < self._total_distance(path):
                        path = new_path
                        improved = True

        return path

    def _distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Distance entre deux points."""
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _total_distance(self, path: List[Tuple[float, float]]) -> float:
        """Distance totale d'un chemin."""
        return sum(self._distance(path[i], path[i + 1]) for i in range(len(path) - 1))


# =============================================
# Factory
# =============================================
def create_pathfinder(
    grid: MapProcessor = None,
) -> PathFinder:
    """Crée un pathfinder configuré."""
    return PathFinder(grid)


def create_map_processor() -> MapProcessor:
    """Crée un processeur de carte."""
    return MapProcessor()
