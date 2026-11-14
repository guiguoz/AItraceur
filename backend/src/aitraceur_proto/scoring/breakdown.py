"""
CourseScoreBreakdown — résultat détaillé du scoring.

Chaque dimension reflète un critère du traceur IOF/FFCO.
Le score global est la somme pondérée par ScoringWeights du profil.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..model.leg import Leg


@dataclass
class CourseScoreBreakdown:
    """
    Décomposition explicable du score d'un parcours.

    Tous les sous-scores sont dans [0.0, 1.0] (1.0 = parfait).
    Le score global (global_score) est dans [0.0, 100.0].

    Attributes:
        global_score:    Score global [0–100] — agrégat pondéré.
        grade:           Lettre de qualité : A (≥85), B (≥70), C (≥55), D (<55).

        distance_score:  Proximité à la distance cible du profil.
        climb_score:     Proximité au dénivelé cible.
        technical_score: Cohérence du niveau technique avec le profil.
        variety_score:   Diversité des longueurs de jambe (CV) [0–1].
        structure_score: Qualité de la structure (dog-legs, bornes jambes, faisabilité).
        spatial_score:   Couverture et répartition spatiale sur la carte.
        safety_score:    Absence de jambes impossibles, de dog-legs critiques.

        controls_quality_score: Qualité intrinsèque des postes [0–1].
        legs_quality_score:     Qualité des jambes (choix d'itinéraire, runn) [0–1].
        flow_score:             Fluidité des changements de cap successifs [0–1].
        global_effort_score:    Cohérence de l'effort physique global vs cible [0–1].
        alignment_score:        Absence d'alignements A→B→C [0–1].
                                1.0 = aucun alignement, 0.0 = parfaitement alignés.
        clustering_score:       Distribution spatiale des postes [0–1].
                                Score élevé si espacement varié (pas de amas).
        diversity_score:        Entropie de Shannon des symbols/types de postes [0–1].

        distance_m:      Distance totale calculée (m).
        target_dist_m:   Distance cible du profil (m).
        climb_m:         Dénivelé calculé (m), si disponible.
        target_climb_m:  Dénivelé cible (m).
        dog_legs:        Nombre de dog-legs détectés.
        n_infeasible:    Nombre de jambes infaisables.
        n_controls:      Nombre total de postes.
        type_diversity:  Entropie de Shannon des types (0–1).
        mean_td:         Niveau technique moyen.

        mean_km_effort:               Moyenne du km-effort IOF par jambe.
        mean_route_choice_complexity: Complexité moyenne des choix d'itinéraire [0–1].
        total_climb:                  Dénivelé positif total du parcours (m).

        details:         Infos complémentaires libres (pour debug/UI).
    """
    global_score: float = 0.0
    grade: str = "D"

    # Sous-scores composantes [0–1]
    distance_score: float = 0.0
    climb_score: float = 0.0
    technical_score: float = 0.0
    variety_score: float = 0.0
    structure_score: float = 0.0
    spatial_score: float = 0.0
    safety_score: float = 0.0

    # Sous-scores métier [0–1]
    controls_quality_score: float = 0.0   # Qualité intrinsèque des postes
    legs_quality_score: float = 0.0       # Qualité des jambes (choix d'itinéraire, runn)
    flow_score: float = 0.0               # Fluidité des changements de cap successifs
    global_effort_score: float = 0.0      # Cohérence effort physique global vs cible

    # Sous-scores métier avancés [0–1] — scoring anti-patterns (ajout BLOC 1)
    alignment_score: float = 1.0    # Absence d'alignements A→B→C (1.0 = aucun)
    clustering_score: float = 1.0   # Distribution spatiale (1.0 = bien réparti)
    diversity_score: float = 1.0    # Entropie Shannon des symboles (1.0 = max diversité)

    # Valeurs brutes
    distance_m: float = 0.0
    target_dist_m: float = 0.0
    climb_m: Optional[float] = None
    target_climb_m: Optional[float] = None
    dog_legs: int = 0
    n_infeasible: int = 0
    n_controls: int = 0
    type_diversity: float = 0.0
    mean_td: float = 0.0

    # Métriques 3D enrichies
    mean_km_effort: float = 0.0               # Moyenne km-effort IOF par jambe
    mean_route_choice_complexity: float = 0.0  # Complexité moyenne choix d'itinéraire [0–1]
    total_climb: float = 0.0                  # Dénivelé positif total (m)

    # Détails libres
    details: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Factory depuis une liste de Leg
    # ------------------------------------------------------------------

    @staticmethod
    def from_legs(legs: List["Leg"]) -> "CourseScoreBreakdown":
        """
        Construit un CourseScoreBreakdown minimal depuis une liste de Leg.

        Calcule :
          - mean_km_effort               : moyenne de leg.km_effort
          - mean_route_choice_complexity : moyenne de leg.route_choice_complexity
          - total_climb                  : somme de leg.climb_m

        Cas vide : retourne un CourseScoreBreakdown avec toutes les valeurs à 0.0.

        Args:
            legs: Liste de Leg (objets model.leg.Leg avec les champs 3D).

        Returns:
            CourseScoreBreakdown avec les trois champs enrichis renseignés.
        """
        if not legs:
            return CourseScoreBreakdown()

        n = len(legs)
        mean_km_effort = sum(lg.km_effort for lg in legs) / n
        mean_rcc = sum(lg.route_choice_complexity for lg in legs) / n
        total_climb = sum(lg.climb_m for lg in legs)

        return CourseScoreBreakdown(
            mean_km_effort=round(mean_km_effort, 4),
            mean_route_choice_complexity=round(mean_rcc, 4),
            total_climb=round(total_climb, 2),
        )

    # ------------------------------------------------------------------
    # Sérialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Sérialisation pour les APIs et logs."""
        return {
            "global_score": round(self.global_score, 2),
            "grade": self.grade,
            "distance_score": round(self.distance_score, 3),
            "climb_score": round(self.climb_score, 3),
            "technical_score": round(self.technical_score, 3),
            "variety_score": round(self.variety_score, 3),
            "structure_score": round(self.structure_score, 3),
            "spatial_score": round(self.spatial_score, 3),
            "safety_score": round(self.safety_score, 3),
            "controls_quality_score": round(self.controls_quality_score, 3),
            "legs_quality_score": round(self.legs_quality_score, 3),
            "flow_score": round(self.flow_score, 3),
            "global_effort_score": round(self.global_effort_score, 3),
            "alignment_score": round(self.alignment_score, 3),
            "clustering_score": round(self.clustering_score, 3),
            "diversity_score": round(self.diversity_score, 3),
            "distance_m": round(self.distance_m, 1),
            "target_dist_m": self.target_dist_m,
            "dog_legs": self.dog_legs,
            "n_infeasible": self.n_infeasible,
            "n_controls": self.n_controls,
            "type_diversity": round(self.type_diversity, 3),
            "mean_td": round(self.mean_td, 2),
            "mean_km_effort": round(self.mean_km_effort, 4),
            "mean_route_choice_complexity": round(self.mean_route_choice_complexity, 4),
            "total_climb": round(self.total_climb, 2),
            **self.details,
        }


def _letter_grade(score: float) -> str:
    """Traduit un score [0–100] en lettre A–D."""
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"
