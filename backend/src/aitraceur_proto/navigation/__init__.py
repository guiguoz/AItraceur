"""
Couche 2 — Modèle de déplacement.

Sous-modules :
    terrain_types — Tables de coûts terrain par profil
    graph         — NavigationGraph (réseau linéaire)
    raster        — CostRaster (grille de coût surfacique)
    movement      — MovementModel (combinaison graphe + raster + pathfinding)
"""
from .movement import MovementModel
from .graph import NavigationGraph
from .raster import CostRaster

__all__ = ["MovementModel", "NavigationGraph", "CostRaster"]
