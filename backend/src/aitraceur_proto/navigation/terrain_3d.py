"""
Modèle de déplacement 3D : pente (loi de Tobler) + végétation.

Le coût entre deux cellules est un temps en secondes, physiquement crédible
pour la course d'orientation :
  - plat, terrain ouvert (veg=1.0)     : ~6 km/h → ~1 s / 1,67 m
  - légère descente (-5%) : optimum Tobler, légèrement plus rapide
  - montée à 20%         : ≈ 40 % plus lent
  - végétation dense (0.2): 5× plus lent

Le pathfinding A* calcule les voisins à la volée (pas de graphe pré-construit).
L'heuristique euclidienne / vitesse_max est admissible.

Contraintes respectées :
  ✗ pas de skimage.graph
  ✗ pas de matrice NxN d'arêtes
  ✓ heapq + voisins lazy
  ✓ NumPy pour les grilles (accès O(1))

Exemple :
    model = TerrainMovementCost(elev_grid, veg_grid, cell_size=5.0)
    dt = model.compute_cost(10, 20, 11, 20)      # une cellule vers le bas
    t  = shortest_path_time((0, 0), (50, 30), model)
"""
from __future__ import annotations

import heapq
import math
from typing import List, Optional, Tuple

try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False


# ---------------------------------------------------------------------------
# Directions 8-connexes : (drow, dcol, dist_factor)
# ---------------------------------------------------------------------------

_DIRS: List[Tuple[int, int, float]] = [
    (-1,  0, 1.000),   # Nord
    (+1,  0, 1.000),   # Sud
    ( 0, -1, 1.000),   # Ouest
    ( 0, +1, 1.000),   # Est
    (-1, -1, 1.4142),  # NW
    (-1, +1, 1.4142),  # NE
    (+1, -1, 1.4142),  # SW
    (+1, +1, 1.4142),  # SE
]


# ---------------------------------------------------------------------------
# TerrainMovementCost
# ---------------------------------------------------------------------------

class TerrainMovementCost:
    """
    Coût de déplacement entre deux cellules voisines (secondes).

    Attributs construits à l'init :
        elevation_grid:  (H, W) float32 — altitudes en m.
        vegetation_grid: (H, W) float32 — facteur vitesse [0–1].
                         1.0 = terrain ouvert, 0.2 = végétation dense.
        cell_size:       Résolution spatiale en m.
        base_speed_mps:  Vitesse de base en m/s (convertie depuis km/h).
    """

    def __init__(
        self,
        elevation_grid: "np.ndarray",
        vegetation_grid: "np.ndarray",
        cell_size: float,
        base_speed_kmh: float = 6.0,
    ) -> None:
        if not _NP_OK:
            raise ImportError("numpy est requis.")

        self.elevation_grid: "np.ndarray" = elevation_grid
        self.vegetation_grid: "np.ndarray" = vegetation_grid
        self.cell_size: float = cell_size
        self.base_speed_mps: float = base_speed_kmh / 3.6

        # Vitesse max théorique pour l'heuristique A* (Tobler slope=0 → speed=base)
        # On ajoute 5% de marge pour garantir l'admissibilité.
        self._max_speed_mps: float = self.base_speed_mps * 1.05

    # ------------------------------------------------------------------
    # Calcul de coût cellule à cellule
    # ------------------------------------------------------------------

    def compute_cost(self, r1: int, c1: int, r2: int, c2: int) -> float:
        """
        Temps de déplacement (secondes) entre deux cellules voisines.

        Modèle physique :
          1. distance 2D : cell_size × 1 (cardinal) ou × √2 (diagonal)
          2. pente       : slope = dz / distance
          3. Tobler      : speed = base_mps × exp(-3.5 × |slope + 0.05|)
          4. végétation  : actual_speed = speed × veg_factor
          5. pénalités   : montée > 30% ou descente < -40%

        Args:
            r1, c1: Cellule source.
            r2, c2: Cellule destination (voisine directe).

        Returns:
            Temps en secondes ≥ 0.
        """
        h, w = self.elevation_grid.shape
        is_diagonal = (r2 != r1) and (c2 != c1)
        distance = self.cell_size * (1.4142 if is_diagonal else 1.0)

        # Clamp des indices pour éviter les débordements
        r1_s = max(0, min(r1, h - 1))
        c1_s = max(0, min(c1, w - 1))
        r2_s = max(0, min(r2, h - 1))
        c2_s = max(0, min(c2, w - 1))

        dz = float(self.elevation_grid[r2_s, c2_s]) - float(self.elevation_grid[r1_s, c1_s])
        slope = dz / distance  # positif = montée, négatif = descente

        # Loi de Tobler : vitesse optimale à slope ≈ -0.05 (5% descente)
        speed = self.base_speed_mps * math.exp(-3.5 * abs(slope + 0.05))

        # Facteur végétation (clamp bas à 5% pour éviter division par zéro)
        veg = float(self.vegetation_grid[r1_s, c1_s])
        actual_speed = speed * max(0.05, veg)

        travel_time = distance / max(0.1, actual_speed)

        # Pénalité montée raide (> 30%)
        if slope > 0.30:
            travel_time *= 1.0 + (slope - 0.30) * 10.0

        # Pénalité descente brutale (< -40%) — risque de chute / glissade
        elif slope < -0.40:
            travel_time *= 1.0 + (abs(slope) - 0.40) * 5.0

        return travel_time

    @property
    def max_speed_mps(self) -> float:
        """Vitesse maximale théorique (m/s) utilisée par l'heuristique A*."""
        return self._max_speed_mps

    @property
    def shape(self) -> Tuple[int, int]:
        return self.elevation_grid.shape  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# A* interne (retourne temps + chemin)
# ---------------------------------------------------------------------------

def _astar(
    start: Tuple[int, int],
    end: Tuple[int, int],
    cost_model: TerrainMovementCost,
) -> Tuple[float, List[Tuple[int, int]]]:
    """
    A* 8-connexe sur grille.

    Retourne (temps_secondes, chemin) où le chemin est une liste de (row, col).
    Retourne (math.inf, []) si aucun chemin n'existe.

    Propriétés :
      - Heuristique admissible : dist_euclidienne / vitesse_max
      - Voisins calculés à la volée — pas de graphe pré-construit
      - came_from tracé pour reconstruction du chemin (utile pour climb_m)
    """
    if start == end:
        return 0.0, [start]

    h, w = cost_model.shape
    r_end, c_end = end
    cell = cost_model.cell_size
    max_spd = cost_model.max_speed_mps

    def heuristic(r: int, c: int) -> float:
        dist = math.hypot((r - r_end) * cell, (c - c_end) * cell)
        return dist / max_spd

    # Priority queue : (f, g, row, col)
    open_heap: List[Tuple[float, float, int, int]] = []
    heapq.heappush(open_heap, (heuristic(*start), 0.0, start[0], start[1]))

    g_costs: dict[Tuple[int, int], float] = {start: 0.0}
    came_from: dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}

    while open_heap:
        _f, g, r, c = heapq.heappop(open_heap)

        if (r, c) == end:
            # Reconstruction du chemin
            path: List[Tuple[int, int]] = []
            node: Optional[Tuple[int, int]] = (r, c)
            while node is not None:
                path.append(node)
                node = came_from.get(node)
            path.reverse()
            return g, path

        if g > g_costs.get((r, c), math.inf):
            continue

        for dr, dc, _dist_factor in _DIRS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < h and 0 <= nc < w):
                continue

            edge_cost = cost_model.compute_cost(r, c, nr, nc)
            new_g = g + edge_cost

            if new_g < g_costs.get((nr, nc), math.inf):
                g_costs[(nr, nc)] = new_g
                came_from[(nr, nc)] = (r, c)
                f_new = new_g + heuristic(nr, nc)
                heapq.heappush(open_heap, (f_new, new_g, nr, nc))

    return math.inf, []


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def shortest_path_time(
    start: Tuple[int, int],
    end: Tuple[int, int],
    cost_model: TerrainMovementCost,
) -> float:
    """
    Temps de déplacement optimal (secondes) entre deux cellules.

    Utilise A* avec heuristique admissible (distance euclidienne / vitesse_max).

    Args:
        start:      Cellule de départ (row, col).
        end:        Cellule d'arrivée (row, col).
        cost_model: Modèle de coût TerrainMovementCost.

    Returns:
        Temps en secondes. math.inf si chemin inexistant.
    """
    time_s, _path = _astar(start, end, cost_model)
    return time_s


def shortest_path_with_climb(
    start: Tuple[int, int],
    end: Tuple[int, int],
    cost_model: TerrainMovementCost,
) -> Tuple[float, float]:
    """
    Retourne (temps_secondes, dénivelé_positif_m) du chemin optimal.

    Utile pour alimenter Leg.travel_time_seconds et Leg.climb_m.

    Args:
        start:      Cellule de départ (row, col).
        end:        Cellule d'arrivée (row, col).
        cost_model: Modèle de coût TerrainMovementCost.

    Returns:
        Tuple (temps_s, climb_m). (math.inf, 0.0) si chemin inexistant.
    """
    time_s, path = _astar(start, end, cost_model)
    if not path:
        return time_s, 0.0
    climb = compute_climb_along_path(path, cost_model.elevation_grid)
    return time_s, climb


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def compute_climb_along_path(
    path: List[Tuple[int, int]],
    elevation_grid: "np.ndarray",
) -> float:
    """
    Dénivelé positif cumulé le long d'un chemin (mètres).

    Seules les montées sont comptabilisées (descentes ignorées),
    conformément à la définition IOF du « dénivelé positif ».

    Args:
        path:           Séquence de (row, col) du chemin.
        elevation_grid: Grille d'altitudes (H, W).

    Returns:
        Dénivelé positif total en mètres.
    """
    h, w = elevation_grid.shape
    climb = 0.0
    for i in range(1, len(path)):
        r1, c1 = path[i - 1]
        r2, c2 = path[i]
        r1 = max(0, min(r1, h - 1))
        c1 = max(0, min(c1, w - 1))
        r2 = max(0, min(r2, h - 1))
        c2 = max(0, min(c2, w - 1))
        dz = float(elevation_grid[r2, c2]) - float(elevation_grid[r1, c1])
        if dz > 0.0:
            climb += dz
    return climb
