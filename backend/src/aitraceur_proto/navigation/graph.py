"""
Graphe de navigation — construit depuis les features linéaires OCAD.

Le graphe modélise le réseau de déplacement préférentiel :
  - FORÊT : chemins, sentiers, layons, cours d'eau (comme repère)
  - SPRINT : rues, ruelles, passages, escaliers, ponts

Nœuds  = extrémités et intersections de segments.
Arêtes = segments pondérés par (distance / vitesse) = temps normalisé.

Les features UNCROSSABLE (murs, clôtures, rivières infranchissables)
créent des barrières : elles ne génèrent pas d'arêtes traversables
mais sont stockées pour le pathfinding hybride (raster).

Exemple :
    graph = NavigationGraph.build(features, environment=CourseEnvironment.FOREST)
    path_cost = graph.shortest_path_cost(pt_a, pt_b, snap_dist=20.0)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Union

try:
    import networkx as nx
    from shapely.geometry import LineString, MultiLineString, Point
    from shapely.ops import split, unary_union
    _OK = True
except ImportError:
    _OK = False

from ..controls.symbol_map import SemanticCategory, TerrainType
from ..controls.ocad_parser import SemanticFeature
from ..profiles import CourseEnvironment
from .terrain_types import TerrainCost, get_terrain_cost, FOREST_COSTS


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_SNAP_PRECISION_M = 0.5       # Deux nœuds à moins de 0.5 m sont fusionnés
_DEFAULT_SNAP_DIST_M = 20.0   # Distance d'accrochage d'un Point au graphe


# ---------------------------------------------------------------------------
# NavigationGraph
# ---------------------------------------------------------------------------

class NavigationGraph:
    """
    Graphe de navigation pondéré pour le pathfinding entre candidats.

    Attributes:
        graph:       NetworkX Graph avec attributs sur les arêtes :
                     ``weight`` (temps normalisé), ``dist_m``, ``speed_factor``.
        barriers:    Union des géométries linéaires infranchissables
                     (murs, clôtures, rivières interdites).
        environment: Environnement de la carte (FOREST / SPRINT_URBAN).
    """

    def __init__(self) -> None:
        if not _OK:
            raise ImportError("networkx et shapely sont requis.")
        self.graph: "nx.Graph" = nx.Graph()
        self.barriers: Optional[Any] = None      # shapely geometry
        self.environment: CourseEnvironment = CourseEnvironment.FOREST
        self._node_index: dict[tuple[float, float], int] = {}
        self._next_nid: int = 0

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        features: list[SemanticFeature],
        environment: CourseEnvironment = CourseEnvironment.FOREST,
    ) -> "NavigationGraph":
        """
        Construit le graphe depuis une liste de SemanticFeature.

        Seules les features linéaires (chemins, sentiers, murs traversables, etc.)
        contribuent au graphe. Les zones interdites linéaires (murs, clôtures
        infranchissables) sont stockées comme barrières.

        Args:
            features:    Features issues de parse_geojson / parse_ocad_xml.
            environment: Environnement cartographique.

        Returns:
            NavigationGraph prêt pour le pathfinding.
        """
        g = cls()
        g.environment = environment

        barrier_geoms: list[Any] = []

        # Catégories linéaires pertinentes
        _LINEAR_CATEGORIES = {
            SemanticCategory.PATH.value,
            SemanticCategory.MANMADE.value,
            SemanticCategory.WATER.value,
        }

        for feat in features:
            if feat.is_layout or feat.is_area or feat.is_point:
                continue
            if feat.info.category.value not in _LINEAR_CATEGORIES:
                continue

            cost = get_terrain_cost(feat.info.terrain_type, environment)

            if cost.is_forbidden:
                # Barrière → stocke comme obstacle
                if feat.geom is not None:
                    barrier_geoms.append(feat.geom)
                continue

            # Ajout au graphe
            g._add_line_feature(feat.geom, cost)

        if barrier_geoms:
            g.barriers = unary_union(barrier_geoms)

        return g

    def _node_id(self, pt: tuple[float, float]) -> int:
        """Retourne l'ID de nœud pour un point (fusion si proche d'un existant)."""
        # Grille d'arrondi pour la fusion
        rounded = (
            round(pt[0] / _SNAP_PRECISION_M) * _SNAP_PRECISION_M,
            round(pt[1] / _SNAP_PRECISION_M) * _SNAP_PRECISION_M,
        )
        if rounded not in self._node_index:
            nid = self._next_nid
            self._next_nid += 1
            self._node_index[rounded] = nid
            self.graph.add_node(nid, x=rounded[0], y=rounded[1])
        return self._node_index[rounded]

    def _add_line_feature(
        self,
        geom: Any,           # LineString ou MultiLineString
        cost: TerrainCost,
    ) -> None:
        """Ajoute une feature linéaire comme suite d'arêtes dans le graphe."""
        if geom is None:
            return

        lines: list[Any]
        if geom.geom_type == "LineString":
            lines = [geom]
        elif geom.geom_type == "MultiLineString":
            lines = list(geom.geoms)
        else:
            return

        for line in lines:
            coords = list(line.coords)
            for i in range(len(coords) - 1):
                p0, p1 = coords[i], coords[i + 1]
                nid0 = self._node_id(p0)
                nid1 = self._node_id(p1)
                dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                weight = cost.to_edge_weight(dist)
                # Garde la meilleure arête si elle existe déjà
                existing = self.graph.get_edge_data(nid0, nid1)
                if existing is None or existing["weight"] > weight:
                    self.graph.add_edge(
                        nid0, nid1,
                        weight=weight,
                        dist_m=dist,
                        speed_factor=cost.speed_factor,
                    )

    # ------------------------------------------------------------------
    # Accès aux nœuds
    # ------------------------------------------------------------------

    def nearest_node(self, pt: Point, max_dist_m: float = _DEFAULT_SNAP_DIST_M) -> Optional[int]:
        """Retourne l'ID du nœud le plus proche de pt, dans max_dist_m."""
        best_nid: Optional[int] = None
        best_dist = float("inf")
        for nid, data in self.graph.nodes(data=True):
            d = math.hypot(data["x"] - pt.x, data["y"] - pt.y)
            if d < best_dist:
                best_dist = d
                best_nid = nid
        if best_dist <= max_dist_m:
            return best_nid
        return None

    def node_point(self, nid: int) -> Optional[Point]:
        """Retourne le Point d'un nœud."""
        data = self.graph.nodes.get(nid)
        if data:
            return Point(data["x"], data["y"])
        return None

    # ------------------------------------------------------------------
    # Pathfinding
    # ------------------------------------------------------------------

    def shortest_path_cost(
        self,
        a: Point,
        b: Point,
        snap_dist_m: float = _DEFAULT_SNAP_DIST_M,
    ) -> Optional[float]:
        """
        Coût du plus court chemin entre deux points dans le graphe.

        Le coût est un temps normalisé (distance / vitesse) — comparable
        entre profils si la vitesse de base est la même.

        Args:
            a, b:        Points source et destination (coordonnées projetées).
            snap_dist_m: Distance max pour accrocher les points au graphe.

        Returns:
            Coût du chemin, ou None si aucun chemin n'existe.
        """
        nid_a = self.nearest_node(a, snap_dist_m)
        nid_b = self.nearest_node(b, snap_dist_m)

        if nid_a is None or nid_b is None:
            return None
        if nid_a == nid_b:
            return 0.0

        try:
            cost = nx.astar_path_length(
                self.graph, nid_a, nid_b,
                heuristic=lambda u, v: math.hypot(
                    self.graph.nodes[u]["x"] - self.graph.nodes[v]["x"],
                    self.graph.nodes[u]["y"] - self.graph.nodes[v]["y"],
                ),
                weight="weight",
            )
            return float(cost)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def is_reachable(self, a: Point, b: Point, snap_dist_m: float = _DEFAULT_SNAP_DIST_M) -> bool:
        """True si b est accessible depuis a dans le graphe."""
        return self.shortest_path_cost(a, b, snap_dist_m) is not None

    def crosses_barrier(self, a: Point, b: Point) -> bool:
        """True si le segment direct a→b coupe une barrière infranchissable."""
        if self.barriers is None:
            return False
        try:
            segment = LineString([(a.x, a.y), (b.x, b.y)])
            return segment.crosses(self.barriers) or self.barriers.contains(segment)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"NavigationGraph(nodes={self.graph.number_of_nodes()}, "
            f"edges={self.graph.number_of_edges()}, "
            f"env={self.environment.value})"
        )
