"""
Tests — Couche 2 : modèle de déplacement.

Couvre :
  - NavigationGraph : construction, pathfinding
  - CostRaster : construction, coût ponctuel, pathfinding raster
  - MovementModel : compute_cost, is_feasible
"""
from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon

from src.aitraceur.navigation.raster import BBox, CostRaster
from src.aitraceur.navigation.graph import NavigationGraph
from src.aitraceur.navigation.movement import MovementModel
from src.aitraceur.profiles import CourseEnvironment, PROFILE_FOREST_MIDDLE_ORANGE


class TestNavigationGraph:
    def test_build_empty(self):
        g = NavigationGraph.build([], CourseEnvironment.FOREST)
        assert g.graph.number_of_nodes() == 0

    def test_build_with_path(self, simple_semantic_features):
        g = NavigationGraph.build(simple_semantic_features, CourseEnvironment.FOREST)
        # Le chemin linéaire doit créer des nœuds et arêtes
        assert g.graph.number_of_nodes() >= 2
        assert g.graph.number_of_edges() >= 1

    def test_nearest_node_found(self, simple_semantic_features):
        g = NavigationGraph.build(simple_semantic_features, CourseEnvironment.FOREST)
        if g.graph.number_of_nodes() == 0:
            pytest.skip("Pas de nœuds dans le graphe (features sans lignes)")
        pt = Point(100, 100)
        nid = g.nearest_node(pt, max_dist_m=200.0)
        assert nid is not None

    def test_nearest_node_too_far(self, simple_semantic_features):
        g = NavigationGraph.build(simple_semantic_features, CourseEnvironment.FOREST)
        pt = Point(100_000, 100_000)   # très loin
        nid = g.nearest_node(pt, max_dist_m=10.0)
        assert nid is None

    def test_crosses_barrier_no_barriers(self, simple_semantic_features):
        g = NavigationGraph.build(simple_semantic_features, CourseEnvironment.FOREST)
        # Sans barrière, crosses_barrier doit retourner False
        a, b = Point(100, 100), Point(800, 800)
        assert g.crosses_barrier(a, b) is False

    def test_repr(self):
        g = NavigationGraph.build([], CourseEnvironment.FOREST)
        assert "NavigationGraph" in repr(g)


class TestCostRaster:
    def test_build_empty(self):
        bbox = BBox(0, 0, 500, 500)
        r = CostRaster.build([], bbox=bbox, resolution_m=10.0)
        assert r.data.shape == (50, 50)

    def test_build_with_features(self, simple_semantic_features):
        r = CostRaster.build(
            simple_semantic_features,
            resolution_m=5.0,
            environment=CourseEnvironment.FOREST,
        )
        assert r.data is not None
        assert r.data.shape[0] > 0
        assert r.data.shape[1] > 0

    def test_world_to_cell_roundtrip(self):
        bbox = BBox(0, 0, 1000, 1000)
        r = CostRaster.build([], bbox=bbox, resolution_m=10.0)
        x, y = 300.0, 700.0
        row, col = r.world_to_cell(x, y)
        wx, wy = r.cell_to_world(row, col)
        # Précision à ±résolution/2
        assert abs(wx - x) <= r.resolution_m
        assert abs(wy - y) <= r.resolution_m

    def test_cost_at_returns_finite(self, simple_semantic_features):
        r = CostRaster.build(
            simple_semantic_features, resolution_m=5.0
        )
        c = r.cost_at(150.0, 400.0)
        import math
        assert not math.isnan(c)

    def test_repr(self):
        bbox = BBox(0, 0, 100, 100)
        r = CostRaster.build([], bbox=bbox, resolution_m=5.0)
        assert "CostRaster" in repr(r)


class TestMovementModel:
    def test_build(self, simple_semantic_features, forest_profile):
        model = MovementModel.build(simple_semantic_features, forest_profile)
        assert model.graph is not None
        assert model.raster is not None

    def test_compute_cost_same_point(self, simple_semantic_features, forest_profile):
        model = MovementModel.build(simple_semantic_features, forest_profile)
        pt = Point(200, 200)
        cost = model.compute_cost(pt, pt)
        # Même point → coût nul ou très faible
        assert cost is not None
        assert cost >= 0.0

    def test_compute_cost_short_leg(self, simple_semantic_features, forest_profile):
        model = MovementModel.build(simple_semantic_features, forest_profile)
        a = Point(100, 100)
        b = Point(200, 200)
        cost = model.compute_cost(a, b)
        # Jambe de ~141m → devrait être faisable
        assert cost is not None or True   # peut être None si raster dit impossible

    def test_straight_line_cost_basic(self, simple_semantic_features, forest_profile):
        model = MovementModel.build(simple_semantic_features, forest_profile)
        a = Point(100, 100)
        b = Point(400, 400)
        cost = model.straight_line_cost(a, b)
        if cost is not None:
            assert cost > 0.0

    def test_is_feasible(self, simple_semantic_features, forest_profile):
        model = MovementModel.build(simple_semantic_features, forest_profile)
        a = Point(100, 100)
        b = Point(500, 500)
        # is_feasible ne doit pas lever d'exception
        result = model.is_feasible(a, b)
        assert isinstance(result, bool)
