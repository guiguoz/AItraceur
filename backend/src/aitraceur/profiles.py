"""
Profils de course — définissent l'ensemble des paramètres cibles,
des pondérations de scoring et des règles métier propres à chaque format.

Exemple d'utilisation :
    profile = PROFILE_FOREST_MIDDLE_ORANGE
    print(profile.targets.distance_m_target)   # 4000
    print(profile.environment)                 # CourseEnvironment.FOREST
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet


# ---------------------------------------------------------------------------
# Énumérations de base
# ---------------------------------------------------------------------------

class CourseEnvironment(str, Enum):
    """Type d'environnement cartographique."""
    FOREST = "forest"
    SPRINT_URBAN = "sprint_urban"
    PARK = "park"
    MIXED = "mixed"


class CourseFormat(str, Enum):
    """Format de compétition."""
    SPRINT = "sprint"
    MIDDLE = "middle"
    LONG = "long"
    ULTRA_LONG = "ultra_long"
    RELAY = "relay"
    SCORE = "score"
    TRAINING = "training"
    SCHOOL = "school"


class TechnicalLevel(int, Enum):
    """Niveau technique (correspond aux catégories FFCO / niveaux IOF TD)."""
    WHITE = 1    # Blanc — très facile, TD1
    YELLOW = 2   # Jaune — facile, TD1-2
    ORANGE = 3   # Orange — moyen, TD2-3
    GREEN = 4    # Vert — difficile, TD3-4
    BLUE = 5     # Bleu — très difficile, TD4-5
    RED = 6      # Rouge / Noir — élite, TD5


# ---------------------------------------------------------------------------
# Cibles numériques par profil
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileTargets:
    """
    Paramètres cibles pour un profil de course.

    Toutes les distances sont en mètres, le temps en minutes, le dénivelé en mètres.
    Les bornes min/max définissent les seuils de pénalité dans le scoring.
    """
    distance_m_min: float
    distance_m_target: float
    distance_m_max: float

    climb_m_min: float
    climb_m_target: float
    climb_m_max: float

    controls_min: int
    controls_target: int
    controls_max: int

    winning_time_min_min: float
    winning_time_min_target: float
    winning_time_min_max: float

    leg_m_min: float    # Longueur minimale d'une jambe
    leg_m_max: float    # Longueur maximale d'une jambe


# ---------------------------------------------------------------------------
# Pondérations de scoring
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoringWeights:
    """
    Pondérations des composantes du score (doivent sommer à 1.0).

    Chaque champ correspond à une dimension de CourseScoreBreakdown.
    """
    distance: float = 0.20
    climb: float = 0.10
    technical: float = 0.20
    variety: float = 0.15
    structure: float = 0.15
    spatial: float = 0.10
    safety: float = 0.10

    # Nouveaux poids métier (défaut 0.0 → rétrocompatibles avec les anciens profils)
    controls_quality: float = 0.0   # Qualité intrinsèque des postes
    legs_quality: float = 0.0       # Qualité des jambes (choix d'itinéraire)
    flow: float = 0.0               # Flow global (rythme + variation + fluidité)

    # Poids internes compute_leg_score (ne participent pas à la somme globale)
    effort_weight: float = 0.4      # Poids de l'effort physique (relief) dans le score de jambe
    choice_weight: float = 0.4      # Poids de la complexité d'itinéraire dans le score de jambe
    tech_weight: float = 0.2        # Poids de la difficulté technique dans le score de jambe

    # Poids agrégation globale BLOC 3 (ne participent pas à la somme globale)
    global_leg_weight: float = 0.0    # Poids du score moyen de jambe dans le score global simplifié
    global_effort_weight: float = 0.0 # Poids de l'effort normalisé dans le score global simplifié
    global_climb_weight: float = 0.0  # Poids du dénivelé normalisé dans le score global simplifié

    # Poids formule flow+variety+effort (défaut 0.0 → formule ancienne active)
    # Quand w_legs + w_flow + w_variety + w_effort > 0, la nouvelle formule est utilisée.
    w_legs: float = 0.0     # Poids du score moyen de jambe (compute_leg_score)
    w_flow: float = 0.0     # Poids de la fluidité (compute_flow_score)
    w_variety: float = 0.0  # Poids de la variété des distances (compute_variety_score)
    w_effort: float = 0.0   # Poids de la cohérence effort (compute_global_effort)
    target_effort: float = 1.2  # Ratio km-effort cible (1.2 ≈ 20 % de dénivelé relatif)

    # Poids anti-patterns (défaut 0.0 → non activés)
    w_alignment: float = 0.0   # Poids pénalité alignements A→B→C
    w_clustering: float = 0.0  # Poids pénalité amas de postes
    w_diversity: float = 0.0   # Poids entropie Shannon des symboles OCAD

    def validate(self) -> None:
        total = (
            self.distance + self.climb + self.technical
            + self.variety + self.structure + self.spatial + self.safety
            + self.controls_quality + self.legs_quality + self.flow
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ScoringWeights doit sommer à 1.0, obtenu {total:.4f}")


# ---------------------------------------------------------------------------
# Paramètres de déplacement
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MovementParams:
    """
    Paramètres du modèle de déplacement pour un profil donné.

    base_speed_m_per_min : vitesse de référence sur terrain ouvert/route.
    raster_resolution_m  : résolution du raster de coût (mètres par cellule).
    graph_buffer_m       : distance max entre un point et le graphe pour
                           s'y « accrocher » lors du pathfinding.
    max_leg_graph_ratio  : si la jambe dépasse cette fraction du raster,
                           le graphe est prioritaire sur le raster.
    """
    base_speed_m_per_min: float = 6.0
    raster_resolution_m: float = 5.0
    graph_buffer_m: float = 15.0
    max_leg_graph_ratio: float = 0.4


# ---------------------------------------------------------------------------
# Profil de course complet
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CourseProfile:
    """
    Description complète d'un profil de course.

    Ce profil pilote le comportement de toutes les couches du moteur :
    - candidats autorisés (allowed_control_categories),
    - pondérations de scoring (weights),
    - paramètres de déplacement (movement).
    """
    id: str                                  # ex. "FOREST_MD_ORANGE"
    name: str                                # ex. "Forêt — Moyen — Orange"
    environment: CourseEnvironment
    format: CourseFormat
    technical_level: TechnicalLevel
    targets: ProfileTargets
    allowed_control_categories: FrozenSet[str]  # noms de SemanticCategory
    weights: ScoringWeights
    movement: MovementParams


# ---------------------------------------------------------------------------
# Catégories sémantiques (noms) utilisées par allowed_control_categories
# Correspondent aux valeurs de SemanticCategory dans symbol_map.py
# ---------------------------------------------------------------------------

_FOREST_CATEGORIES: FrozenSet[str] = frozenset({
    "LANDFORM",
    "ROCK",
    "WATER",
    "VEGETATION_EDGE",
    "PATH",
    "MANMADE",
})

_SPRINT_CATEGORIES: FrozenSet[str] = frozenset({
    "MANMADE",
    "PATH",
    "WATER",
    "LANDFORM",   # rare en sprint, mais possible dans parcs
})

_ALL_CATEGORIES: FrozenSet[str] = frozenset({
    "LANDFORM", "ROCK", "WATER", "VEGETATION_EDGE",
    "PATH", "MANMADE",
})


# ---------------------------------------------------------------------------
# Définition des profils standards
# ---------------------------------------------------------------------------

PROFILE_FOREST_MIDDLE_ORANGE = CourseProfile(
    id="FOREST_MD_ORANGE",
    name="Forêt — Moyen — Orange (TD2-3)",
    environment=CourseEnvironment.FOREST,
    format=CourseFormat.MIDDLE,
    technical_level=TechnicalLevel.ORANGE,
    targets=ProfileTargets(
        distance_m_min=2500, distance_m_target=4000, distance_m_max=5500,
        climb_m_min=80,      climb_m_target=150,    climb_m_max=280,
        controls_min=8,      controls_target=12,    controls_max=18,
        winning_time_min_min=25, winning_time_min_target=35, winning_time_min_max=50,
        leg_m_min=200,   leg_m_max=1200,
    ),
    allowed_control_categories=_FOREST_CATEGORIES,
    weights=ScoringWeights(
        distance=0.20, climb=0.10, technical=0.20,
        variety=0.15, structure=0.15, spatial=0.10, safety=0.10,
    ),
    movement=MovementParams(
        base_speed_m_per_min=6.0,
        raster_resolution_m=5.0,
        graph_buffer_m=15.0,
        max_leg_graph_ratio=0.4,
    ),
)

PROFILE_FOREST_LONG_GREEN = CourseProfile(
    id="FOREST_LD_GREEN",
    name="Forêt — Long — Vert (TD3-4)",
    environment=CourseEnvironment.FOREST,
    format=CourseFormat.LONG,
    technical_level=TechnicalLevel.GREEN,
    targets=ProfileTargets(
        distance_m_min=5000, distance_m_target=8000, distance_m_max=14000,
        climb_m_min=150,     climb_m_target=350,    climb_m_max=600,
        controls_min=15,     controls_target=22,    controls_max=30,
        winning_time_min_min=50, winning_time_min_target=75, winning_time_min_max=105,
        leg_m_min=300,   leg_m_max=2000,
    ),
    allowed_control_categories=_FOREST_CATEGORIES,
    weights=ScoringWeights(
        distance=0.20, climb=0.15, technical=0.20,
        variety=0.15, structure=0.10, spatial=0.10, safety=0.10,
    ),
    movement=MovementParams(
        base_speed_m_per_min=5.5,
        raster_resolution_m=8.0,
        graph_buffer_m=20.0,
        max_leg_graph_ratio=0.5,
    ),
)

PROFILE_FOREST_MIDDLE_BLUE = CourseProfile(
    id="FOREST_MD_BLUE",
    name="Forêt — Moyen — Bleu/Rouge (TD4-5)",
    environment=CourseEnvironment.FOREST,
    format=CourseFormat.MIDDLE,
    technical_level=TechnicalLevel.BLUE,
    targets=ProfileTargets(
        distance_m_min=3000, distance_m_target=5000, distance_m_max=7000,
        climb_m_min=100,     climb_m_target=200,    climb_m_max=350,
        controls_min=15,     controls_target=22,    controls_max=30,
        winning_time_min_min=28, winning_time_min_target=40, winning_time_min_max=55,
        leg_m_min=150,   leg_m_max=900,
    ),
    allowed_control_categories=_ALL_CATEGORIES,
    weights=ScoringWeights(
        distance=0.15, climb=0.10, technical=0.25,
        variety=0.20, structure=0.10, spatial=0.10, safety=0.10,
    ),
    movement=MovementParams(
        base_speed_m_per_min=7.0,
        raster_resolution_m=5.0,
        graph_buffer_m=15.0,
        max_leg_graph_ratio=0.3,
    ),
)

PROFILE_SPRINT_URBAN = CourseProfile(
    id="SPRINT_URBAN",
    name="Sprint — Urbain (ISSprOM)",
    environment=CourseEnvironment.SPRINT_URBAN,
    format=CourseFormat.SPRINT,
    technical_level=TechnicalLevel.ORANGE,  # technique sprint ≈ Orange
    targets=ProfileTargets(
        distance_m_min=1500, distance_m_target=2800, distance_m_max=4200,
        climb_m_min=0,       climb_m_target=30,     climb_m_max=100,
        controls_min=12,     controls_target=18,    controls_max=25,
        winning_time_min_min=10, winning_time_min_target=15, winning_time_min_max=20,
        leg_m_min=60,    leg_m_max=400,
    ),
    allowed_control_categories=_SPRINT_CATEGORIES,
    weights=ScoringWeights(
        distance=0.20, climb=0.05, technical=0.20,
        variety=0.20, structure=0.15, spatial=0.10, safety=0.10,
    ),
    movement=MovementParams(
        base_speed_m_per_min=10.0,
        raster_resolution_m=2.0,
        graph_buffer_m=5.0,
        max_leg_graph_ratio=0.8,
    ),
)

PROFILE_SCHOOL = CourseProfile(
    id="SCHOOL",
    name="Entraînement scolaire — Blanc/Jaune",
    environment=CourseEnvironment.PARK,
    format=CourseFormat.SCHOOL,
    technical_level=TechnicalLevel.WHITE,
    targets=ProfileTargets(
        distance_m_min=800,  distance_m_target=1500, distance_m_max=2500,
        climb_m_min=0,       climb_m_target=20,     climb_m_max=60,
        controls_min=5,      controls_target=8,     controls_max=12,
        winning_time_min_min=10, winning_time_min_target=18, winning_time_min_max=30,
        leg_m_min=80,    leg_m_max=500,
    ),
    allowed_control_categories=frozenset({
        "PATH", "MANMADE", "WATER",
    }),
    weights=ScoringWeights(
        distance=0.25, climb=0.05, technical=0.10,
        variety=0.15, structure=0.20, spatial=0.15, safety=0.10,
    ),
    movement=MovementParams(
        base_speed_m_per_min=7.0,
        raster_resolution_m=3.0,
        graph_buffer_m=10.0,
        max_leg_graph_ratio=0.9,
    ),
)

# Registre de tous les profils disponibles
ALL_PROFILES: dict[str, CourseProfile] = {
    p.id: p for p in [
        PROFILE_FOREST_MIDDLE_ORANGE,
        PROFILE_FOREST_LONG_GREEN,
        PROFILE_FOREST_MIDDLE_BLUE,
        PROFILE_SPRINT_URBAN,
        PROFILE_SCHOOL,
    ]
}


def get_profile(profile_id: str) -> CourseProfile:
    """Récupère un profil par son identifiant.

    Raises:
        KeyError: si le profil n'existe pas.
    """
    if profile_id not in ALL_PROFILES:
        raise KeyError(f"Profil inconnu : {profile_id!r}. Disponibles : {list(ALL_PROFILES)}")
    return ALL_PROFILES[profile_id]
