"""
Couche 4 — Modèle de parcours (Course).

Un Course est une séquence ordonnée de ControlCandidate, avec :
  - départ (index 0) et arrivée (dernier élément),
  - métriques calculées à partir de la CostMatrix,
  - helpers immuables pour les modifications de séquence.

Exemple :
    course = Course(controls=[start, c1, c2, c3, finish], profile=profile)
    course = course.compute_metrics(cost_matrix)
    print(course.metrics.total_distance_m)
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace
from typing import Optional

from ..controls.candidate import ControlCandidate, DetailType
from ..profiles import CourseProfile


# ---------------------------------------------------------------------------
# LegInfo — description d'une jambe
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LegInfo:
    """Description d'une jambe i → i+1."""
    from_idx: int
    to_idx: int
    from_type: DetailType
    to_type: DetailType
    straight_dist_m: float          # Distance à vol d'oiseau
    cost: Optional[float]           # Coût du MovementModel (None = impossible)
    bearing_deg: float              # Azimut (0–360°, Nord = 0)
    bearing_change_deg: float       # Changement de cap vs jambe précédente (0–180°)

    # Propriétés métier enrichies (calculées si cost_matrix disponible)
    route_choice_complexity: float = 0.0   # Complexité du choix d'itinéraire [0–1]
    runnability: float = 0.8               # Facilité de déplacement [0–1]
    technical_difficulty: float = 0.0     # Difficulté de navigation [0–1]
    risk_level: float = 0.0               # Probabilité d'erreur [0–1]


# ---------------------------------------------------------------------------
# CourseMetrics — toutes les métriques dérivées d'un Course
# ---------------------------------------------------------------------------

@dataclass
class CourseMetrics:
    """
    Métriques calculées d'un parcours.

    Les attributs avec suffixe ``_m`` sont en mètres.
    """
    # Distance
    total_distance_m: float = 0.0
    min_leg_m: float = 0.0
    max_leg_m: float = 0.0
    mean_leg_m: float = 0.0
    std_leg_m: float = 0.0

    # Dénivelé (optionnel, si disponible)
    total_climb_m: Optional[float] = None

    # Niveau technique
    mean_technical_level: float = 0.0
    max_technical_level: int = 0

    # Variété des types de postes
    type_diversity: float = 0.0     # Shannon entropy normalisée [0–1]
    n_unique_types: int = 0

    # Structure du parcours
    bearing_changes: list[float] = field(default_factory=list)
    mean_bearing_change_deg: float = 0.0
    dog_legs: int = 0               # Jambes avec changement < 25° (dog-leg IOF)

    # Couverture spatiale
    coverage_ratio: float = 0.0     # Fraction du bbox de la carte couverte

    # Nombre total de postes (départ + intermédiaires + arrivée)
    n_controls: int = 0

    # Jambes infaisables
    n_infeasible_legs: int = 0

    # Legs
    legs: list[LegInfo] = field(default_factory=list)

    # Scores métier enrichis (calculés après enrich_candidates + flow scoring)
    mean_controls_quality: float = 0.0   # Qualité intrinsèque moyenne des postes [0–1]
    mean_legs_quality: float = 0.0       # Qualité métier moyenne des jambes [0–1]
    rhythm_score: float = 0.0            # Rythme (alternance longueurs) [0–1]
    variation_score: float = 0.0         # Variation types/directions [0–1]
    flow_score: float = 0.0              # Flow global (absence dog-legs, demi-tours) [0–1]


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------

@dataclass
class Course:
    """
    Parcours de course d'orientation.

    Attributes:
        controls: Séquence ordonnée de ControlCandidate.
                  controls[0]  = départ,
                  controls[-1] = arrivée.
        profile:  Profil de course associé.
        metrics:  Métriques calculées (None avant appel de compute_metrics()).
        generation: Numéro de génération GA (si applicable).
        score:    Score de qualité le plus récent (None avant scoring).
    """
    controls: list[ControlCandidate]
    profile: CourseProfile
    metrics: Optional[CourseMetrics] = None
    generation: int = 0
    score: Optional[float] = None

    # ------------------------------------------------------------------
    # Propriétés de base
    # ------------------------------------------------------------------

    @property
    def n_controls(self) -> int:
        """Nombre total de postes (départ + postes + arrivée)."""
        return len(self.controls)

    @property
    def n_intermediate(self) -> int:
        """Nombre de postes intermédiaires (sans départ ni arrivée)."""
        return max(0, len(self.controls) - 2)

    @property
    def start(self) -> Optional[ControlCandidate]:
        return self.controls[0] if self.controls else None

    @property
    def finish(self) -> Optional[ControlCandidate]:
        return self.controls[-1] if self.controls else None

    # ------------------------------------------------------------------
    # Calcul des métriques
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        cost_matrix: Optional[object] = None,  # CostMatrix (évite import circulaire)
    ) -> "Course":
        """
        Calcule les métriques du parcours et retourne un nouveau Course.

        Si cost_matrix est fourni, utilise ses coûts pour la distance totale.
        Sinon, utilise la distance euclidienne directe.

        Returns:
            Nouveau Course avec metrics renseignées (immutable update).
        """
        if len(self.controls) < 2:
            return replace(self, metrics=CourseMetrics())

        legs: list[LegInfo] = []
        straight_dists: list[float] = []
        bearings: list[float] = []
        prev_bearing: Optional[float] = None
        bearing_changes: list[float] = []
        dog_legs = 0
        n_infeasible = 0

        for i in range(len(self.controls) - 1):
            ca = self.controls[i]
            cb = self.controls[i + 1]

            # Distance et azimut
            dx = cb.x - ca.x
            dy = cb.y - ca.y
            dist = math.hypot(dx, dy)
            bearing = math.degrees(math.atan2(dx, dy)) % 360.0

            # Coût depuis la matrice
            cost: Optional[float] = None
            if cost_matrix is not None:
                cost = cost_matrix.cost(ca, cb)
                if cost is None:
                    n_infeasible += 1

            # Changement de cap
            change = 0.0
            if prev_bearing is not None:
                delta = abs(bearing - prev_bearing) % 360.0
                change = min(delta, 360.0 - delta)
                bearing_changes.append(change)
                if change < 25.0:
                    dog_legs += 1

            # Propriétés métier de la jambe
            if cost is not None and dist > 1.0:
                detour = (cost - dist) / dist
                rcc = min(1.0, max(0.0, detour * 2.0))
                runn = min(1.0, dist / cost)
            else:
                rcc = 0.0
                runn = 0.8

            cb_trap = getattr(cb, "trap_potential", 0.0)
            cb_vis = getattr(cb, "visibility_radius", 30.0)
            nav_diff = 1.0 - min(1.0, cb_vis / 30.0)
            tech_diff = min(1.0, cb_trap * 0.55 + nav_diff * 0.45)
            risk = min(1.0, tech_diff * 0.65 + cb_trap * 0.35)

            legs.append(LegInfo(
                from_idx=i,
                to_idx=i + 1,
                from_type=ca.detail_type,
                to_type=cb.detail_type,
                straight_dist_m=dist,
                cost=cost,
                bearing_deg=bearing,
                bearing_change_deg=change,
                route_choice_complexity=rcc,
                runnability=runn,
                technical_difficulty=tech_diff,
                risk_level=risk,
            ))
            straight_dists.append(dist)
            bearings.append(bearing)
            prev_bearing = bearing

        # Agrégats
        total_dist = sum(straight_dists)
        min_leg = min(straight_dists) if straight_dists else 0.0
        max_leg = max(straight_dists) if straight_dists else 0.0
        mean_leg = statistics.mean(straight_dists) if straight_dists else 0.0
        std_leg = statistics.stdev(straight_dists) if len(straight_dists) > 1 else 0.0

        # Niveau technique
        tech_levels = [c.technical_level for c in self.controls
                       if c.technical_level > 0]
        mean_td = statistics.mean(tech_levels) if tech_levels else 0.0
        max_td = max(tech_levels) if tech_levels else 0

        # Diversité de types (Shannon entropy)
        from collections import Counter
        type_counts = Counter(c.detail_type for c in self.controls)
        type_diversity = _shannon_entropy(list(type_counts.values()))
        n_unique = len(type_counts)

        # Changements de direction
        mean_bc = statistics.mean(bearing_changes) if bearing_changes else 0.0

        # Couverture spatiale (bbox postes / bbox carte)
        coverage = _coverage_ratio(self.controls)

        # Scores métier (lazy import pour éviter import circulaire)
        try:
            from ..scoring.flow import (
                compute_rhythm_score,
                compute_variation_score,
                compute_flow_score,
                score_controls_quality,
                score_legs_quality,
            )
            ctrl_quality = score_controls_quality(self.controls)
            legs_quality = score_legs_quality(legs)
            rhythm = compute_rhythm_score(straight_dists)
            variation = compute_variation_score(legs, self.controls)
            flow = compute_flow_score(legs)
        except Exception:
            ctrl_quality = legs_quality = rhythm = variation = flow = 0.0

        metrics = CourseMetrics(
            n_controls=len(self.controls),
            total_distance_m=total_dist,
            min_leg_m=min_leg,
            max_leg_m=max_leg,
            mean_leg_m=mean_leg,
            std_leg_m=std_leg,
            mean_technical_level=mean_td,
            max_technical_level=max_td,
            type_diversity=type_diversity,
            n_unique_types=n_unique,
            bearing_changes=bearing_changes,
            mean_bearing_change_deg=mean_bc,
            dog_legs=dog_legs,
            coverage_ratio=coverage,
            n_infeasible_legs=n_infeasible,
            legs=legs,
            mean_controls_quality=ctrl_quality,
            mean_legs_quality=legs_quality,
            rhythm_score=rhythm,
            variation_score=variation,
            flow_score=flow,
        )
        return replace(self, metrics=metrics)

    # ------------------------------------------------------------------
    # Modifications immuables
    # ------------------------------------------------------------------

    def with_control_at(self, index: int, candidate: ControlCandidate) -> "Course":
        """Remplace le poste à `index` par `candidate`. Retourne un nouveau Course."""
        new_controls = list(self.controls)
        new_controls[index] = candidate
        return replace(self, controls=new_controls, metrics=None, score=None)

    def with_swap(self, i: int, j: int) -> "Course":
        """Échange les postes aux indices i et j."""
        new_controls = list(self.controls)
        new_controls[i], new_controls[j] = new_controls[j], new_controls[i]
        return replace(self, controls=new_controls, metrics=None, score=None)

    def with_insertion(self, index: int, candidate: ControlCandidate) -> "Course":
        """Insère un poste à `index`. Retourne un nouveau Course."""
        new_controls = list(self.controls)
        new_controls.insert(index, candidate)
        return replace(self, controls=new_controls, metrics=None, score=None)

    def with_removal(self, index: int) -> "Course":
        """Supprime le poste à `index`. Retourne un nouveau Course."""
        if len(self.controls) <= 2:
            return self
        new_controls = [c for i, c in enumerate(self.controls) if i != index]
        return replace(self, controls=new_controls, metrics=None, score=None)

    def with_score(self, score: float) -> "Course":
        """Retourne un nouveau Course avec le score mis à jour."""
        return replace(self, score=score)

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        dist_str = ""
        if self.metrics:
            dist_str = f", dist={self.metrics.total_distance_m:.0f}m"
        score_str = f", score={self.score:.2f}" if self.score is not None else ""
        return (
            f"Course(n={self.n_controls}, profile={self.profile.id!r}"
            f"{dist_str}{score_str})"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shannon_entropy(counts: list[int]) -> float:
    """Entropie de Shannon normalisée [0–1]."""
    total = sum(counts)
    if total == 0 or len(counts) <= 1:
        return 0.0
    import math
    entropy = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    max_entropy = math.log2(len(counts))
    return entropy / max_entropy if max_entropy > 0 else 0.0


def _coverage_ratio(controls: list[ControlCandidate]) -> float:
    """Fraction de la zone cartographique couverte par les postes (0–1)."""
    if len(controls) < 2:
        return 0.0
    xs = [c.x for c in controls]
    ys = [c.y for c in controls]
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    area = w * h
    # Normalisation approximative : on vise environ 2km × 2km = 4km²
    ref_area = 4_000_000.0
    return min(1.0, area / ref_area)
