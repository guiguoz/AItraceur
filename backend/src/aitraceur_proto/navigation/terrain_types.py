"""
Tables de coûts terrain par profil.

Un coût terrain = facteur multiplicatif appliqué à la vitesse de base.
  coût = 1.0  → terrain idéal (route, terrain ouvert)
  coût = 0.5  → moitié moins rapide (végétation dense)
  coût = 0.0  → infranchissable (mur, zone interdite)

Ces coûts alimentent à la fois le raster (zones surfaciques) et le graphe
(arêtes linéaires).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..controls.symbol_map import TerrainType


# ---------------------------------------------------------------------------
# Coût de déplacement d'une arête/cellule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TerrainCost:
    """
    Coût de déplacement associé à un type de terrain.

    Attributes:
        speed_factor: Facteur [0–1] appliqué à la vitesse de base.
                      0.0 = infranchissable, 1.0 = vitesse pleine.
        is_forbidden: True → barrière absolue (pas de traversée).
        note:         Description courte.
    """
    speed_factor: float      # [0.0, 1.0]
    is_forbidden: bool = False
    note: str = ""

    def to_edge_weight(self, distance_m: float) -> float:
        """Poids d'arête = temps de parcours en secondes (vitesse normalisée)."""
        if self.is_forbidden or self.speed_factor < 1e-9:
            return float("inf")
        return distance_m / self.speed_factor

    def to_raster_cost(self) -> float:
        """Valeur raster : inverse du facteur vitesse (1 = optimal, ∞ = interdit)."""
        if self.is_forbidden or self.speed_factor < 1e-9:
            return float("inf")
        return 1.0 / self.speed_factor


# ---------------------------------------------------------------------------
# Table FORÊT (ISOM 2017)
# ---------------------------------------------------------------------------

FOREST_COSTS: dict[TerrainType, TerrainCost] = {
    # Landforms / relief — ne modifient pas directement la vitesse, mais
    # la pente issue des courbes de niveau est traitée séparément.
    TerrainType.KNOLL:          TerrainCost(1.00, note="butte"),
    TerrainType.DEPRESSION:     TerrainCost(0.90, note="dépression"),
    TerrainType.EARTHWALL:      TerrainCost(0.70, note="talus"),
    TerrainType.EARTHWALL_RUIN: TerrainCost(0.75, note="talus ruiné"),
    TerrainType.EROSION_GULLY:  TerrainCost(0.60, note="ravine"),
    TerrainType.CLIFF:          TerrainCost(0.30, note="falaise franchissable"),
    TerrainType.CLIFF_IMPASSABLE: TerrainCost(0.0, is_forbidden=True,
                                              note="falaise infranchissable"),

    # Rochers
    TerrainType.BOULDER:        TerrainCost(0.90, note="bloc"),
    TerrainType.BOULDER_CLUSTER: TerrainCost(0.75, note="amas rochers"),
    TerrainType.ROCKY_GROUND:   TerrainCost(0.70, note="terrain rocheux"),
    TerrainType.STONY_SLOW:     TerrainCost(0.55, note="pierreux lent"),
    TerrainType.STONY_FIGHT:    TerrainCost(0.30, note="pierreux difficile"),
    TerrainType.BARE_ROCK:      TerrainCost(0.85, note="roche nue"),

    # Végétation
    TerrainType.OPEN_LAND:      TerrainCost(1.00, note="terrain ouvert"),
    TerrainType.ROUGH_OPEN:     TerrainCost(0.80, note="terrain ouvert accidenté"),
    TerrainType.FOREST_GOOD:    TerrainCost(0.70, note="forêt courante"),
    TerrainType.SLOW_FOREST:    TerrainCost(0.45, note="forêt lente"),
    TerrainType.FIGHT:          TerrainCost(0.20, note="végétation difficile"),
    TerrainType.VEG_IMPASSABLE: TerrainCost(0.0, is_forbidden=True,
                                            note="végétation infranchissable"),
    TerrainType.ORCHARD:        TerrainCost(0.80, note="verger"),

    # Eau
    TerrainType.OPEN_WATER:     TerrainCost(0.0, is_forbidden=True, note="lac"),
    TerrainType.STREAM:         TerrainCost(0.80, note="ruisseau franchissable"),
    TerrainType.STREAM_IMPASSABLE: TerrainCost(0.0, is_forbidden=True,
                                               note="rivière infranchissable"),
    TerrainType.MARSH:          TerrainCost(0.40, note="marécage"),
    TerrainType.MARSH_IMPASSABLE: TerrainCost(0.0, is_forbidden=True,
                                              note="marécage infranchissable"),
    TerrainType.SPRING:         TerrainCost(0.90, note="source"),
    TerrainType.POND:           TerrainCost(0.0, is_forbidden=True, note="mare"),

    # Chemins & routes
    TerrainType.ROAD_PAVED:     TerrainCost(1.10, note="route asphaltée"),
    TerrainType.ROAD_UNPAVED:   TerrainCost(1.05, note="route non asphaltée"),
    TerrainType.ROAD_FOREST:    TerrainCost(1.00, note="chemin forestier"),
    TerrainType.PATH:           TerrainCost(0.95, note="sentier"),
    TerrainType.FOOTPATH:       TerrainCost(0.95, note="sentier piéton"),
    TerrainType.NARROW_RIDE:    TerrainCost(0.85, note="layon"),
    TerrainType.BRIDGE:         TerrainCost(1.00, note="pont"),
    TerrainType.RAILROAD:       TerrainCost(0.0, is_forbidden=True, note="voie ferrée"),
    TerrainType.CROSSING_POINT: TerrainCost(0.90, note="point franchissement"),

    # Construit
    TerrainType.BUILDING:       TerrainCost(0.0, is_forbidden=True, note="bâtiment"),
    TerrainType.SETTLEMENT:     TerrainCost(0.0, is_forbidden=True, note="zone construite"),
    TerrainType.PAVED_AREA:     TerrainCost(1.00, note="zone pavée"),
    TerrainType.WALL:           TerrainCost(0.0, is_forbidden=True, note="mur"),
    TerrainType.WALL_RUINED:    TerrainCost(0.50, note="mur ruiné"),
    TerrainType.FENCE:          TerrainCost(0.0, is_forbidden=True, note="clôture"),
    TerrainType.HEDGE:          TerrainCost(0.30, note="haie"),
    TerrainType.RUIN:           TerrainCost(0.60, note="ruine"),
    TerrainType.TOWER:          TerrainCost(1.00, note="tour"),
    TerrainType.PASSAGE:        TerrainCost(1.00, note="passage"),
    TerrainType.STAIRS:         TerrainCost(0.60, note="escaliers"),
    TerrainType.POWERLINE:      TerrainCost(0.90, note="ligne électrique"),

    # Interdit
    TerrainType.OUT_OF_BOUNDS:  TerrainCost(0.0, is_forbidden=True, note="hors-limites"),
    TerrainType.DANGEROUS_CROSSING: TerrainCost(0.0, is_forbidden=True,
                                                note="croisement dangereux"),
}

# ---------------------------------------------------------------------------
# Table SPRINT (ISSprOM 2019) — les différences vs forêt
# ---------------------------------------------------------------------------

SPRINT_COSTS: dict[TerrainType, TerrainCost] = {
    **FOREST_COSTS,   # Hérite de la table forêt

    # Overrides sprint
    TerrainType.OPEN_LAND:      TerrainCost(1.00, note="sol ouvert sprint"),
    TerrainType.FOREST_GOOD:    TerrainCost(0.80, note="parc sprint"),
    TerrainType.ROUGH_OPEN:     TerrainCost(0.85, note="terrain ouvert accidenté sprint"),
    TerrainType.SLOW_FOREST:    TerrainCost(0.60, note="végétation parc"),
    TerrainType.PAVED_AREA:     TerrainCost(1.10, note="zone pavée sprint"),
    TerrainType.ROAD_PAVED:     TerrainCost(1.15, note="route sprint"),
    TerrainType.PATH:           TerrainCost(1.05, note="sentier sprint"),
    TerrainType.WALL:           TerrainCost(0.0, is_forbidden=True, note="mur sprint"),
    TerrainType.FENCE:          TerrainCost(0.0, is_forbidden=True, note="clôture sprint"),
    TerrainType.BUILDING:       TerrainCost(0.0, is_forbidden=True, note="bâtiment sprint"),
    TerrainType.STAIRS:         TerrainCost(0.50, note="escaliers sprint"),
    TerrainType.PASSAGE:        TerrainCost(1.10, note="passage sprint"),
}

# Registre des tables par environnement
from ..profiles import CourseEnvironment

COST_TABLE_BY_ENV: dict[CourseEnvironment, dict[TerrainType, TerrainCost]] = {
    CourseEnvironment.FOREST: FOREST_COSTS,
    CourseEnvironment.SPRINT_URBAN: SPRINT_COSTS,
    CourseEnvironment.PARK: SPRINT_COSTS,
    CourseEnvironment.MIXED: FOREST_COSTS,
}

_DEFAULT_COST = TerrainCost(0.70, note="défaut (forêt courante)")


def get_terrain_cost(
    terrain_type: TerrainType,
    environment: CourseEnvironment,
) -> TerrainCost:
    """Retourne le TerrainCost pour un type de terrain et un environnement."""
    table = COST_TABLE_BY_ENV.get(environment, FOREST_COSTS)
    return table.get(terrain_type, _DEFAULT_COST)
