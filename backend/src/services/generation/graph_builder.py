# =============================================
# Graphe de navigation pour génération de circuits
# Sprint 7: Génération de circuits (Forêt)
# =============================================

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict


# =============================================
# Types de données
# =============================================
@dataclass
class Node:
    """Un nœud dans le graphe (position candidate pour un poste)."""

    node_id: str
    x: float
    y: float
    node_type: str  # "path", "junction", "control_point", "landmark"
    terrain_type: str = "unknown"  # "road", "path", "forest", "open"
    runnability: float = 1.0  # 0-1, 1 = très praticable


@dataclass
class Edge:
    """Une arête dans le graphe (lien entre deux positions)."""

    from_node: str
    to_node: str
    distance: float
    cost: float  # Coût pondéré par runnability
    elevation_gain: float = 0.0
    elevation_loss: float = 0.0
    path_type: str = "direct"  # "road", "path", "direct"


@dataclass
class NavigationGraph:
    """Graphe de navigation complet."""

    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: Dict[str, List[Edge]] = field(default_factory=lambda: defaultdict(list))
    bounding_box: Dict = field(default_factory=dict)


# =============================================
# Graph Builder
# =============================================
class GraphBuilder:
    """
    Construit un graphe de navigation à partir des données terrain.

    Le graphe représente toutes les positions candidates possibles pour les postes
    et les connexions entre elles.
    """

    # Distance maximale entre deux nœuds (m)
    MAX_EDGE_DISTANCE = 500

    # Distance minimale entre deux postes (m)
    MIN_CONTROL_DISTANCE = 100

    # Résolution de la grille de candidates (m)
    GRID_RESOLUTION = 50

    def __init__(self):
        """Initialise le builder."""
        self.graph = NavigationGraph()
        self.osm_data = None
        self.lidar_data = None
        self.runnability_map = None

    def load_osm_data(self, osm_data: Dict):
        """Charge les données OSM."""
        self.osm_data = osm_data

    def load_lidar_data(self, lidar_data: Dict):
        """Charge les données LIDAR."""
        self.lidar_data = lidar_data

    def load_runnability(self, runnability_map: Dict):
        """Charge la carte de runnability."""
        self.runnability_map = runnability_map

    def build_graph(
        self,
        bounding_box: Dict,
        include_paths: bool = True,
        include_landmarks: bool = True,
        grid_density: str = "medium",
    ) -> NavigationGraph:
        """
        Construit le graphe de navigation.

        Args:
            bounding_box: {min_x, min_y, max_x, max_y}
            include_paths: Inclure les chemins OSM
            include_landmarks: Inclure les points de repère
            grid_density: Densité de la grille (low, medium, high)

        Returns:
            NavigationGraph
        """
        self.graph = NavigationGraph()
        self.graph.bounding_box = bounding_box

        # 1. Ajouter les nœuds depuis OSM (chemins)
        if include_paths and self.osm_data:
            self._add_path_nodes()

        # 2. Ajouter les nœuds de la grille
        self._add_grid_nodes(grid_density)

        # 3. Ajouter les nœuds de repère (si disponibles)
        if include_landmarks:
            self._add_landmark_nodes()

        # 4. Créer les arêtes
        self._build_edges()

        return self.graph

    def _add_path_nodes(self):
        """Ajoute les nœuds depuis les chemins OSM."""
        if not self.osm_data:
            return

        roads = self.osm_data.get("roads", [])
        node_counter = 0

        for road in roads:
            # Créer des nœuds le long du chemin
            points = road.get("points", [])

            for i, point in enumerate(points):
                node_id = f"path_{node_counter}"
                node_counter += 1

                # Déterminer le type de chemin
                road_type = road.get("type", "unclassified")
                node_type = "path"

                if road_type in ["primary", "secondary", "tertiary"]:
                    node_type = "road"
                elif road_type in ["footpath", "path", "track"]:
                    node_type = "path"

                # Créer le nœud
                node = Node(
                    node_id=node_id,
                    x=point[0],
                    y=point[1],
                    node_type=node_type,
                    terrain_type=road_type,
                    runnability=self._get_runnability(point[0], point[1]),
                )

                self.graph.nodes[node_id] = node

    def _add_grid_nodes(self, density: str):
        """Ajoute une grille de nœuds pour la couverture."""
        bbox = self.graph.bounding_box

        # Résolution selon la densité
        resolution_map = {
            "low": 100,
            "medium": 50,
            "high": 25,
        }
        resolution = resolution_map.get(density, 50)

        node_counter = len(self.graph.nodes)

        x = bbox.get("min_x", 0)
        while x <= bbox.get("max_x", 0):
            y = bbox.get("min_y", 0)
            while y <= bbox.get("max_y", 0):
                node_id = f"grid_{node_counter}"

                node = Node(
                    node_id=node_id,
                    x=x,
                    y=y,
                    node_type="grid",
                    terrain_type="forest",
                    runnability=self._get_runnability(x, y),
                )

                self.graph.nodes[node_id] = node
                node_counter += 1

                y += resolution
            x += resolution

    def _add_landmark_nodes(self):
        """Ajoute des nœuds de repère (caractéristiques du terrain)."""
        # Points d'eau, sommets, intersections, etc.
        # Pour l'instant, simplifié
        pass

    def _build_edges(self):
        """Construit les arêtes entre les nœuds."""
        nodes_list = list(self.graph.nodes.values())

        # Pour chaque paire de nœuds proches, créer une arête
        for i, node1 in enumerate(nodes_list):
            for node2 in nodes_list[i + 1 :]:
                dist = self._calculate_distance((node1.x, node1.y), (node2.x, node2.y))

                # Limiter la distance des arêtes
                if dist > self.MAX_EDGE_DISTANCE:
                    continue

                # Calculer le coût
                avg_runnability = (node1.runnability + node2.runnability) / 2
                cost = dist / avg_runnability if avg_runnability > 0 else dist * 10

                # Déterminer le type de chemin
                if node1.node_type in ["road", "path"] or node2.node_type in [
                    "road",
                    "path",
                ]:
                    path_type = "path"
                else:
                    path_type = "direct"

                # Créer l'arête dans les deux sens
                edge1 = Edge(
                    from_node=node1.node_id,
                    to_node=node2.node_id,
                    distance=dist,
                    cost=cost,
                    path_type=path_type,
                )

                edge2 = Edge(
                    from_node=node2.node_id,
                    to_node=node1.node_id,
                    distance=dist,
                    cost=cost,
                    path_type=path_type,
                )

                self.graph.edges[node1.node_id].append(edge1)
                self.graph.edges[node2.node_id].append(edge2)

    def _get_runnability(self, x: float, y: float) -> float:
        """Retourne la runnability à une position."""
        if self.runnability_map:
            # Chercher dans la grille
            return self.runnability_map.get("default", 0.7)

        # Valeur par défaut
        return 0.7

    def _calculate_distance(
        self, p1: Tuple[float, float], p2: Tuple[float, float]
    ) -> float:
        """Calcule la distance entre deux points."""
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)

    def get_candidate_positions(
        self,
        center: Tuple[float, float],
        radius: float,
        min_distance: float = None,
        max_count: int = 20,
    ) -> List[Node]:
        """
        Retourne les positions candidates autour d'un centre.

        Args:
            center: (x, y) centre de recherche
            radius: Rayon de recherche en mètres
            min_distance: Distance minimale entre les positions
            max_count: Nombre maximum de positions

        Returns:
            Liste de nœuds candidats
        """
        candidates = []

        for node in self.graph.nodes.values():
            dist = self._calculate_distance(center, (node.x, node.y))

            if dist <= radius:
                # Vérifier la distance minimale
                if min_distance:
                    too_close = False
                    for other in candidates:
                        if (
                            self._calculate_distance(
                                (node.x, node.y), (other.x, other.y)
                            )
                            < min_distance
                        ):
                            too_close = True
                            break
                    if too_close:
                        continue

                candidates.append(node)

                if len(candidates) >= max_count:
                    break

        # Trier par distance
        candidates.sort(key=lambda n: self._calculate_distance(center, (n.x, n.y)))

        return candidates[:max_count]

    def find_path(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        algorithm: str = "dijkstra",
    ) -> List[Tuple[float, float]]:
        """
        Trouve un chemin entre deux points.

        Args:
            start: Point de départ
            end: Point d'arrivée
            algorithm: Algorithme (dijkstra, a_star, greedy)

        Returns:
            Liste de points [(x, y), ...]
        """
        if algorithm == "dijkstra":
            return self._dijkstra(start, end)
        elif algorithm == "a_star":
            return self._a_star(start, end)
        else:
            return [start, end]  # Direct

    def _dijkstra(
        self, start: Tuple[float, float], end: Tuple[float, float]
    ) -> List[Tuple[float, float]]:
        """Implémente Dijkstra pour le chemin le plus court."""
        # Trouver les nœuds les plus proches
        start_node = self._find_nearest_node(start)
        end_node = self._find_nearest_node(end)

        if not start_node or not end_node:
            return [start, end]

        # Dijkstra
        dist = {start_node: 0}
        prev = {}
        visited = set()

        while visited != set(self.graph.nodes):
            # Trouver le nœud non visités avec la plus petite distance
            min_dist = float("inf")
            current = None

            for node_id in self.graph.nodes:
                if node_id not in visited:
                    if node_id in dist and dist[node_id] < min_dist:
                        min_dist = dist[node_id]
                        current = node_id

            if current is None:
                break

            if current == end_node:
                break

            visited.add(current)

            # Explorer les voisins
            for edge in self.graph.edges.get(current, []):
                if edge.to_node in visited:
                    continue

                new_dist = dist[current] + edge.cost
                if edge.to_node not in dist or new_dist < dist[edge.to_node]:
                    dist[edge.to_node] = new_dist
                    prev[edge.to_node] = current

        # Reconstruire le chemin
        if end_node not in prev and start_node != end_node:
            return [start, end]

        path = []
        current = end_node

        while current:
            node = self.graph.nodes.get(current)
            if node:
                path.append((node.x, node.y))
            current = prev.get(current)

        path.reverse()

        if path and path[0] != start:
            path.insert(0, start)

        return path

    def _a_star(
        self, start: Tuple[float, float], end: Tuple[float, float]
    ) -> List[Tuple[float, float]]:
        """Implémente A* pour le chemin le plus court."""
        # Similaire à Dijkstra mais avec heuristique
        return self._dijkstra(start, end)  # Pour l'instant, same

    def _find_nearest_node(self, point: Tuple[float, float]) -> Optional[str]:
        """Trouve le nœud le plus proche d'un point."""
        min_dist = float("inf")
        nearest = None

        for node_id, node in self.graph.nodes.items():
            dist = self._calculate_distance(point, (node.x, node.y))
            if dist < min_dist:
                min_dist = dist
                nearest = node_id

        return nearest

    def get_statistics(self) -> Dict:
        """Retourne les statistiques du graphe."""
        edge_count = sum(len(edges) for edges in self.graph.edges.values())

        node_types = defaultdict(int)
        for node in self.graph.nodes.values():
            node_types[node.node_type] += 1

        return {
            "total_nodes": len(self.graph.nodes),
            "total_edges": edge_count,
            "node_types": dict(node_types),
            "bounding_box": self.graph.bounding_box,
        }
