"""
MovementModel — combinaison graphe + raster pour estimer le coût entre deux points.

Stratégie hybride :
  1. Si les deux points sont proches du graphe → utilise A* sur le graphe.
  2. Sinon → utilise le raster (Dijkstra sur grille).
  3. Dans tous les cas, refuse les traversées de barrières infranchissables.

Le coût retourné est un « temps relatif » (distance / vitesse) comparable
entre jambes. Il n'est pas en secondes réelles sans calibration de la vitesse.

Exemple :
    model = MovementModel.build(features, profile)
    cost = model.compute_cost(pt_a, pt_b)
    if cost is None:
        print("Jambe impossible (zone interdite)")
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

try:
    from shapely.geometry import Point
    _OK = True
except ImportError:
    _OK = False

from ..controls.ocad_parser import SemanticFeature
from ..profiles import CourseProfile, CourseEnvironment
from .graph import NavigationGraph, _DEFAULT_SNAP_DIST_M
from .raster import BBox, CostRaster


# ---------------------------------------------------------------------------
# MovementModel
# ---------------------------------------------------------------------------

class MovementModel:
    """
    Modèle de déplacement hybride (graphe + raster).

    Attributes:
        graph:    NavigationGraph (réseau linéaire).
        raster:   CostRaster (coût surfacique).
        profile:  Profil de course associé.
    """

    def __init__(
        self,
        graph: NavigationGraph,
        raster: CostRaster,
        profile: CourseProfile,
    ) -> None:
        self.graph = graph
        self.raster = raster
        self.profile = profile
        self._snap_dist = profile.movement.graph_buffer_m
        self._graph_ratio = profile.movement.max_leg_graph_ratio

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        features: list[SemanticFeature],
        profile: CourseProfile,
        bbox: Optional[BBox] = None,
    ) -> "MovementModel":
        """
        Construit le MovementModel complet depuis les features de la carte.

        Args:
            features: SemanticFeatures issues du parser.
            profile:  Profil de course (détermine résolution, vitesse, etc.).
            bbox:     Enveloppe optionnelle. Si None, dérivée des features.

        Returns:
            MovementModel prêt à l'emploi.
        """
        graph = NavigationGraph.build(features, profile.environment)
        raster = CostRaster.build(
            features,
            bbox=bbox,
            resolution_m=profile.movement.raster_resolution_m,
            environment=profile.environment,
        )
        return cls(graph, raster, profile)

    # ------------------------------------------------------------------
    # API principale
    # ------------------------------------------------------------------

    def compute_cost(
        self,
        a: Point,
        b: Point,
        *,
        force_raster: bool = False,
    ) -> Optional[float]:
        """
        Estime le coût de déplacement de a vers b.

        Le coût est un temps relatif normalisé (0 = même point, ∞ ou None = impossible).

        Stratégie :
          - Si le segment direct coupe une barrière : None.
          - Si les deux points sont dans le graphe ET la distance à vol d'oiseau
            est <= max_leg_graph_ratio × largeur de la zone → A* graphe.
          - Sinon → pathfinding raster.
          - Si les deux méthodes échouent → None.

        Args:
            a, b:          Points source et destination (coordonnées projetées, m).
            force_raster:  Si True, bypasse le graphe et utilise toujours le raster.

        Returns:
            Coût de déplacement (float ≥ 0) ou None.
        """
        if not _OK:
            raise ImportError("shapely est requis.")

        # Vérification barrière directe
        if self.graph.crosses_barrier(a, b):
            # Essayer quand même via le graphe (contournement possible)
            graph_cost = self._graph_cost(a, b)
            if graph_cost is not None:
                return graph_cost
            return None

        # Décision graphe vs raster
        direct_dist = a.distance(b)
        zone_width = self.raster.bbox.width_m

        use_graph = (
            not force_raster
            and direct_dist <= self._graph_ratio * zone_width
        )

        if use_graph:
            graph_cost = self._graph_cost(a, b)
            if graph_cost is not None:
                return graph_cost
            # Fallback raster si le graphe ne couvre pas la zone
            return self._raster_cost(a, b)

        # Raster prioritaire
        raster_cost = self._raster_cost(a, b)
        if raster_cost is not None:
            return raster_cost

        # Fallback graphe
        return self._graph_cost(a, b)

    def straight_line_cost(self, a: Point, b: Point) -> Optional[float]:
        """
        Coût en ligne droite (sans pathfinding).

        Utile pour les estimations rapides lors de la génération.
        Retourne None si le segment direct traverse une barrière.
        """
        if self.graph.crosses_barrier(a, b):
            return None
        dist = a.distance(b)
        # Coût moyen entre les deux points dans le raster
        cost_a = self.raster.cost_at(a.x, a.y)
        cost_b = self.raster.cost_at(b.x, b.y)
        avg_cost = (cost_a + cost_b) / 2.0
        if avg_cost == float("inf"):
            return None
        return dist * avg_cost

    def is_feasible(self, a: Point, b: Point) -> bool:
        """True si la jambe a→b est réalisable (pas totalement bloquée)."""
        return self.compute_cost(a, b) is not None

    # ------------------------------------------------------------------
    # Méthodes privées
    # ------------------------------------------------------------------

    def _graph_cost(self, a: Point, b: Point) -> Optional[float]:
        return self.graph.shortest_path_cost(a, b, snap_dist_m=self._snap_dist)

    def _raster_cost(self, a: Point, b: Point) -> Optional[float]:
        return self.raster.path_cost(a, b)

    def __repr__(self) -> str:
        return (
            f"MovementModel(profile={self.profile.id!r}, "
            f"graph={self.graph}, raster={self.raster})"
        )
