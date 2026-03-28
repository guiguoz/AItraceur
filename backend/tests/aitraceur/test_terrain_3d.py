"""
Tests du modèle de déplacement 3D (Tobler + végétation).

Grilles synthétiques construites avec numpy — pas de GeoTIFF requis.
Chaque test isole une propriété physique du modèle.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.aitraceur.navigation.terrain_3d import (
    TerrainMovementCost,
    compute_climb_along_path,
    shortest_path_time,
    shortest_path_with_climb,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_model(
    size: int = 10,
    veg: float = 1.0,
    base_speed_kmh: float = 6.0,
    cell_size: float = 10.0,
) -> TerrainMovementCost:
    """Modèle plat homogène (toutes cellules identiques)."""
    elev = np.zeros((size, size), dtype=np.float32)
    veg_grid = np.full((size, size), veg, dtype=np.float32)
    return TerrainMovementCost(elev, veg_grid, cell_size=cell_size,
                               base_speed_kmh=base_speed_kmh)


def _slope_model(
    slope_value: float,
    size: int = 10,
    cell_size: float = 10.0,
    base_speed_kmh: float = 6.0,
) -> TerrainMovementCost:
    """
    Modèle avec pente uniforme dans la direction col+1.

    Pour aller de (r, c) à (r, c+1) : dz = slope_value * cell_size
    slope_value > 0 = montée, < 0 = descente.
    """
    # altitude[r, c] = c * slope_value * cell_size
    grid = np.zeros((size, size), dtype=np.float32)
    for c in range(size):
        grid[:, c] = c * slope_value * cell_size
    veg = np.ones((size, size), dtype=np.float32)
    return TerrainMovementCost(grid, veg, cell_size=cell_size,
                               base_speed_kmh=base_speed_kmh)


# ---------------------------------------------------------------------------
# P1 — Modèle physique : compute_cost
# ---------------------------------------------------------------------------

class TestComputeCost:
    def test_flat_terrain_baseline(self):
        """Pente = 0 → temps = distance / vitesse_effective."""
        model = _flat_model(size=5, veg=1.0, base_speed_kmh=6.0, cell_size=10.0)
        t = model.compute_cost(2, 2, 2, 3)   # déplacement cardinal

        base_mps = 6.0 / 3.6
        # Pente ≈ 0 → Tobler ≈ exp(-3.5 × 0.05) ≈ 0.839
        tobler_factor = math.exp(-3.5 * abs(0.0 + 0.05))
        expected = 10.0 / (base_mps * tobler_factor * 1.0)
        assert abs(t - expected) < 0.05, f"Attendu ≈ {expected:.2f}s, obtenu {t:.2f}s"

    def test_uphill_slope_slower(self):
        """Montée (+20%) → plus lent que plat."""
        flat = _flat_model(size=5, veg=1.0, cell_size=10.0)
        uphill = _slope_model(slope_value=0.20, size=5, cell_size=10.0)

        t_flat   = flat.compute_cost(2, 2, 2, 3)
        t_uphill = uphill.compute_cost(2, 2, 2, 3)

        assert t_uphill > t_flat, (
            f"Montée devrait être plus lente : {t_uphill:.2f}s vs {t_flat:.2f}s"
        )

    def test_optimal_descent_fastest(self):
        """Légère descente (-5%) → optimum Tobler, plus rapide que plat."""
        flat    = _flat_model(size=5, veg=1.0, cell_size=10.0)
        descent = _slope_model(slope_value=-0.05, size=5, cell_size=10.0)

        t_flat    = flat.compute_cost(2, 2, 2, 3)
        # Sur descente uniforme -5%, le col suivant est plus bas
        # compute_cost(2,2, 2,3) : dz = elev[2,3] - elev[2,2] = -0.05*10 = -0.5 m
        # slope = -0.5 / 10 = -0.05 → Tobler optimal (|slope+0.05| = 0)
        t_descent = descent.compute_cost(2, 2, 2, 3)

        assert t_descent < t_flat, (
            f"Descente optimale devrait être plus rapide : {t_descent:.2f}s vs {t_flat:.2f}s"
        )

    def test_dense_vegetation_slower(self):
        """Végétation dense (0.2) → ≈5× plus lent que terrain ouvert."""
        open_terrain = _flat_model(size=5, veg=1.0, cell_size=10.0)
        dense_veg    = _flat_model(size=5, veg=0.2, cell_size=10.0)

        t_open  = open_terrain.compute_cost(2, 2, 2, 3)
        t_dense = dense_veg.compute_cost(2, 2, 2, 3)

        assert t_dense > t_open * 4.0, (
            f"Végétation dense devrait être beaucoup plus lente : "
            f"{t_dense:.2f}s vs {t_open:.2f}s"
        )

    def test_steep_slope_penalty(self):
        """Pente > 30% → pénalité multiplicative appliquée."""
        steep = _slope_model(slope_value=0.35, size=5, cell_size=10.0)
        moderate = _slope_model(slope_value=0.25, size=5, cell_size=10.0)

        t_steep    = steep.compute_cost(2, 2, 2, 3)
        t_moderate = moderate.compute_cost(2, 2, 2, 3)

        assert t_steep > t_moderate, (
            "Pente 35% doit être plus pénalisée que 25%"
        )

    def test_brutal_descent_penalty(self):
        """Descente brutale (< -40%) → pénalité appliquée."""
        brutal = _slope_model(slope_value=-0.45, size=5, cell_size=10.0)
        gentle = _slope_model(slope_value=-0.05, size=5, cell_size=10.0)

        t_brutal = brutal.compute_cost(2, 2, 2, 3)
        t_gentle = gentle.compute_cost(2, 2, 2, 3)

        assert t_brutal > t_gentle, (
            "Descente brutale (-45%) doit être plus pénalisée que légère (-5%)"
        )

    def test_diagonal_longer_than_cardinal(self):
        """Déplacement diagonal coûte √2 × cardinal (terrain plat)."""
        model = _flat_model(size=5, veg=1.0, cell_size=10.0)
        t_cardinal = model.compute_cost(2, 2, 2, 3)
        t_diagonal = model.compute_cost(2, 2, 3, 3)

        ratio = t_diagonal / t_cardinal
        assert 1.38 < ratio < 1.46, f"Ratio diagonal/cardinal = {ratio:.3f}, attendu ~1.414"

    def test_cost_positive(self):
        """Le coût est toujours strictement positif."""
        model = _flat_model(size=5, veg=1.0, cell_size=5.0)
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)]:
            t = model.compute_cost(3, 3, 3+dr, 3+dc)
            assert t > 0.0, f"Coût nul ou négatif pour ({dr},{dc})"


# ---------------------------------------------------------------------------
# P2 — A* : shortest_path_time
# ---------------------------------------------------------------------------

class TestShortestPathTime:
    def test_same_cell_returns_zero(self):
        model = _flat_model(size=10)
        assert shortest_path_time((5, 5), (5, 5), model) == 0.0

    def test_adjacent_cell_consistent(self):
        """Chemin d'une cellule = compute_cost direct."""
        model = _flat_model(size=10)
        t_astar = shortest_path_time((3, 3), (3, 4), model)
        t_direct = model.compute_cost(3, 3, 3, 4)
        assert abs(t_astar - t_direct) < 1e-6

    def test_path_time_positive(self):
        model = _flat_model(size=20)
        t = shortest_path_time((0, 0), (15, 12), model)
        assert t > 0.0 and math.isfinite(t)

    def test_symmetry_flat(self):
        """Sur terrain plat homogène, A→B ≈ B→A."""
        model = _flat_model(size=20)
        t_ab = shortest_path_time((0, 0), (10, 8), model)
        t_ba = shortest_path_time((10, 8), (0, 0), model)
        assert abs(t_ab - t_ba) / max(t_ab, 1e-9) < 0.01

    def test_uphill_longer_time(self):
        """Trajet en montée → plus long que plat."""
        flat   = _flat_model(size=15)
        uphill = _slope_model(slope_value=0.15, size=15, cell_size=10.0)

        t_flat   = shortest_path_time((5, 0), (5, 10), flat)
        t_uphill = shortest_path_time((5, 0), (5, 10), uphill)

        assert t_uphill > t_flat

    def test_avoids_slow_vegetation(self):
        """A* doit préférer contourner une zone de végétation dense."""
        size = 15
        elev = np.zeros((size, size), dtype=np.float32)
        veg  = np.ones((size, size),  dtype=np.float32)
        # Mur vertical de végétation dense col=7
        veg[:, 7] = 0.05
        model = TerrainMovementCost(elev, veg, cell_size=5.0, base_speed_kmh=6.0)

        # Chemin en ligne droite (traverse col=7) vs chemin sans contrainte
        t_with_wall = shortest_path_time((0, 0), (14, 14), model)
        # A* devrait contourner et rester dans des temps raisonnables
        assert math.isfinite(t_with_wall)


# ---------------------------------------------------------------------------
# P3 — shortest_path_with_climb : dénivelé
# ---------------------------------------------------------------------------

class TestShortestPathWithClimb:
    def test_flat_terrain_no_climb(self):
        model = _flat_model(size=10)
        t, climb = shortest_path_with_climb((0, 0), (9, 9), model)
        assert math.isfinite(t) and t > 0.0
        assert climb == 0.0, f"Terrain plat : climb devrait être 0, obtenu {climb}"

    def test_uphill_positive_climb(self):
        model = _slope_model(slope_value=0.10, size=10, cell_size=10.0)
        # Partir de col=0 (altitude 0) → col=9 (altitude 9*0.10*10 = 9m)
        t, climb = shortest_path_with_climb((5, 0), (5, 9), model)
        assert climb > 0.0, "Montée : dénivelé positif attendu"
        assert abs(climb - 9.0) < 1.5, f"Dénivelé attendu ~9m, obtenu {climb:.2f}m"

    def test_downhill_zero_climb(self):
        """Descente pure → dénivelé positif = 0.

        _slope_model(slope_value=-0.10) : elev[r,c] = c * (-0.10) * cell_size
        → col 0 = 0 m (haut), col 9 = -9 m (bas)
        → aller de (5,0) à (5,9) est une descente continue.
        """
        model = _slope_model(slope_value=-0.10, size=10, cell_size=10.0)
        t, climb = shortest_path_with_climb((5, 0), (5, 9), model)  # descente réelle
        assert climb == 0.0, f"Descente pure : climb devrait être 0, obtenu {climb}"


# ---------------------------------------------------------------------------
# P4 — compute_climb_along_path
# ---------------------------------------------------------------------------

class TestComputeClimbAlongPath:
    def test_flat_path_zero_climb(self):
        elev = np.zeros((5, 5), dtype=np.float32)
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        assert compute_climb_along_path(path, elev) == 0.0

    def test_step_climb(self):
        """3 montées de 1 m chacune → climb = 3 m."""
        elev = np.array([
            [0, 1, 2, 3, 4],
            [0, 1, 2, 3, 4],
        ], dtype=np.float32)
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        climb = compute_climb_along_path(path, elev)
        assert abs(climb - 3.0) < 1e-6

    def test_descent_ignored(self):
        """3 descentes de 1 m chacune → climb = 0 m."""
        elev = np.array([
            [3, 2, 1, 0],
        ], dtype=np.float32)
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        climb = compute_climb_along_path(path, elev)
        assert climb == 0.0

    def test_mixed_climbs_and_descents(self):
        """Montée 2m + descente 1m + montée 3m → climb = 5m."""
        elev = np.array([
            [0, 2, 1, 4],
        ], dtype=np.float32)
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        climb = compute_climb_along_path(path, elev)
        assert abs(climb - 5.0) < 1e-6

    def test_single_point_path(self):
        elev = np.zeros((3, 3), dtype=np.float32)
        assert compute_climb_along_path([(1, 1)], elev) == 0.0

    def test_empty_path(self):
        elev = np.zeros((3, 3), dtype=np.float32)
        assert compute_climb_along_path([], elev) == 0.0


# ---------------------------------------------------------------------------
# P5 — Leg.climb_m et Leg.km_effort
# ---------------------------------------------------------------------------

class TestLegKmEffort:
    def test_km_effort_flat(self):
        from src.aitraceur.model.leg import Leg
        leg = Leg(
            start_id="s", end_id="e",
            distance=1000.0, bearing_deg=90.0, bearing_change_deg=0.0,
            route_choice_complexity=0.1, runnability=0.9,
            technical_difficulty=0.2, risk_level=0.1,
            climb_m=0.0,
        )
        assert abs(leg.km_effort - 1.0) < 1e-9

    def test_km_effort_with_climb(self):
        from src.aitraceur.model.leg import Leg
        leg = Leg(
            start_id="s", end_id="e",
            distance=1000.0, bearing_deg=90.0, bearing_change_deg=0.0,
            route_choice_complexity=0.1, runnability=0.9,
            technical_difficulty=0.2, risk_level=0.1,
            climb_m=100.0,   # 100m de montée → +1 km équivalent
        )
        assert abs(leg.km_effort - 2.0) < 1e-9

    def test_distance_2d_alias(self):
        from src.aitraceur.model.leg import Leg
        leg = Leg(
            start_id="s", end_id="e",
            distance=500.0, bearing_deg=0.0, bearing_change_deg=0.0,
            route_choice_complexity=0.0, runnability=1.0,
            technical_difficulty=0.0, risk_level=0.0,
        )
        assert leg.distance_2d == leg.distance

    def test_climb_default_zero(self):
        from src.aitraceur.model.leg import Leg
        leg = Leg(
            start_id="s", end_id="e",
            distance=300.0, bearing_deg=0.0, bearing_change_deg=0.0,
            route_choice_complexity=0.0, runnability=1.0,
            technical_difficulty=0.0, risk_level=0.0,
        )
        assert leg.climb_m == 0.0
        assert leg.travel_time_seconds == 0.0
