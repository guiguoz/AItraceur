"""
ControlCandidate — représentation d'un emplacement potentiel de poste.

Chaque candidat est associé à un objet cartographique précis, qualifié par :
  - sa géométrie (Point shapely en coordonnées projetées, mètres)
  - son type sémantique (DetailType)
  - des scores de qualité intrinsèques (attractivité, lisibilité, isolation)
  - son niveau technique de base et les profils dans lesquels il est autorisé

Exemple :
    from shapely.geometry import Point
    c = ControlCandidate(
        id="c_42",
        geom=Point(452100.0, 6901200.0),
        detail_type=DetailType.BOULDER,
        attractiveness_score=0.90,
        readability_score=0.95,
        isolation_score=0.80,
        technical_level=2,
        allowed_profiles=frozenset({"FOREST_MD_ORANGE", "FOREST_LD_GREEN"}),
        source_sym=204,
        description_fr="Bloc rocheux",
    )
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, List, Optional

try:
    from shapely.geometry import Point
except ImportError:
    # Permet l'import du module même sans shapely installé
    Point = object  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# DetailType — type de détail géographique du poste
# ---------------------------------------------------------------------------

class DetailType(str, Enum):
    """
    Type précis du détail cartographique servant de poste.

    Sert à la fois à qualifier le ControlCandidate et à produire la
    description IOF (ex : "Boulder / Bloc rocheux").
    """
    # Relief
    KNOLL = "knoll"
    HILL_TOP = "hill_top"
    SADDLE = "saddle"
    DEPRESSION = "depression"
    PIT = "pit"
    REENTRANT = "reentrant"
    SPUR = "spur"
    EARTHWALL_END = "earthwall_end"
    EARTHWALL_CORNER = "earthwall_corner"
    EROSION_GULLY_END = "erosion_gully_end"
    BROKEN_GROUND = "broken_ground"

    # Rochers
    BOULDER = "boulder"
    BOULDER_CLUSTER = "boulder_cluster"
    CLIFF_FOOT = "cliff_foot"
    CLIFF_TOP = "cliff_top"
    ROCKY_GROUND_EDGE = "rocky_ground_edge"
    BARE_ROCK = "bare_rock"

    # Eau
    POND_EDGE = "pond_edge"
    STREAM_JUNCTION = "stream_junction"
    STREAM_SOURCE = "stream_source"
    STREAM_BEND = "stream_bend"
    MARSH_EDGE = "marsh_edge"
    SPRING = "spring"

    # Végétation
    VEG_BOUNDARY = "veg_boundary"
    CLEARING_CORNER = "clearing_corner"
    CLEARING_EDGE = "clearing_edge"

    # Chemins / routes
    PATH_JUNCTION = "path_junction"
    PATH_CROSSING = "path_crossing"
    PATH_BEND = "path_bend"
    PATH_END = "path_end"
    ROAD_JUNCTION = "road_junction"
    BRIDGE = "bridge"
    CROSSING_POINT = "crossing_point"

    # Éléments construits (forêt et sprint)
    BUILDING = "building"
    BUILDING_CORNER = "building_corner"
    RUIN = "ruin"
    RUIN_CORNER = "ruin_corner"
    WALL_CORNER = "wall_corner"
    WALL_END = "wall_end"
    WALL_JUNCTION = "wall_junction"
    FENCE_CORNER = "fence_corner"
    FENCE_END = "fence_end"
    FENCE_JUNCTION = "fence_junction"
    HEDGE_END = "hedge_end"
    TOWER = "tower"
    PILLAR = "pillar"
    PASSAGE = "passage"
    STAIRS = "stairs"
    GATE = "gate"
    MANHOLE = "manhole"
    PAVED_AREA_CORNER = "paved_area_corner"
    SPECIAL_OBJECT = "special_object"

    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# ControlCandidate
# ---------------------------------------------------------------------------

@dataclass
class ControlCandidate:
    """
    Emplacement potentiel d'un poste de course d'orientation.

    Attributes:
        id:                  Identifiant unique (ex : "c_204_42").
        geom:                Géométrie du centre du poste (Point shapely,
                             coordonnées projetées en mètres).
        detail_type:         Type de détail géographique (DetailType).
        attractiveness_score: Attractivité intrinsèque [0–1].
                              1 = poste idéal (très distinct, facile à identifier).
                              0 = pas recommandé.
        readability_score:   Lisibilité sur carte [0–1].
                              1 = symbole grand et non ambigu.
        isolation_score:     Isolement par rapport aux candidats voisins [0–1].
                              Calculé lors du filtrage (dépend du contexte).
        technical_level:     Niveau technique de base requis [1–5].
                              1 = Blanc, 5 = TD5.
        allowed_profiles:    Ensemble des IDs de CourseProfile dans lesquels
                             ce candidat peut apparaître.
        source_sym:          Code symbole OCAD source (ex : 204 pour Boulder).
        description_fr:      Libellé français (ex : "Bloc rocheux").
        source_feature_id:   ID de la feature GeoJSON / XML source (debug).
        extra:               Données additionnelles libres.
    """
    id: str
    geom: Point
    detail_type: DetailType
    attractiveness_score: float
    readability_score: float
    isolation_score: float = 1.0
    technical_level: int = 2                       # [1–5]
    allowed_profiles: FrozenSet[str] = field(default_factory=frozenset)
    source_sym: Optional[int] = None
    description_fr: str = ""
    source_feature_id: Optional[str] = None
    extra: dict = field(default_factory=dict)

    # --- Propriétés métier enrichies (calculées par controls/enricher.py) ---
    visibility_radius: float = 30.0          # Distance de détection visuelle (m)
    trap_potential: float = 0.0              # Potentiel de piège / confusion [0–1]
    landmark_strength: float = 0.5          # Force comme point de repère [0–1]
    approach_directions: List[float] = field(default_factory=list)  # Azimuts d'accès (°)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def x(self) -> float:
        """Coordonnée X projetée (mètres)."""
        return self.geom.x

    @property
    def y(self) -> float:
        """Coordonnée Y projetée (mètres)."""
        return self.geom.y

    @property
    def composite_score(self) -> float:
        """Score composite = attractivité + lisibilité.

        Sert à ordonner les candidats lors de la sélection initiale.
        L'isolation_score est intégré plus tard, après filtrage spatial.
        """
        return 0.6 * self.attractiveness_score + 0.4 * self.readability_score

    @property
    def quality_score(self) -> float:
        """Score de qualité enrichi intégrant toutes les propriétés métier.

        Utilisé après enrichissement (enrich_candidates) pour le scoring
        de qualité intrinsèque dans le flow scorer.
        """
        return (
            self.attractiveness_score * 0.40
            + self.isolation_score     * 0.25
            + self.landmark_strength   * 0.20
            + (1.0 - self.trap_potential) * 0.15   # trap élevé = piège = moins fiable
        )

    def is_allowed_for_profile(self, profile_id: str) -> bool:
        """True si ce candidat est autorisé dans le profil donné."""
        return profile_id in self.allowed_profiles

    def distance_to(self, other: "ControlCandidate") -> float:
        """Distance euclidienne entre deux candidats (mètres)."""
        return self.geom.distance(other.geom)

    def __repr__(self) -> str:
        return (
            f"ControlCandidate(id={self.id!r}, type={self.detail_type.value}, "
            f"score={self.composite_score:.2f}, td={self.technical_level})"
        )

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ControlCandidate):
            return NotImplemented
        return self.id == other.id
