"""
Scoring du flow, du rythme et de la variation d'un parcours.

Ces fonctions évaluent la dynamique du parcours telle qu'un traceur
IOF/FFCO l'apprécie : alternance des jambes, variété des défis,
absence de répétition et de dog-legs.

Elles sont appelées automatiquement dans Course.compute_metrics() et
intégrées dans score_course() via les nouveaux sous-scores.

Exemple :
    rhythm = compute_rhythm_score([200, 800, 150, 600, 350])   # 0.76
    flow   = compute_flow_score(course.metrics.legs)            # 0.82
"""
from __future__ import annotations

import math
import statistics
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..controls.candidate import ControlCandidate
    from ..model.course import LegInfo


# ---------------------------------------------------------------------------
# Rythme — alternance des longueurs de jambes
# ---------------------------------------------------------------------------

def compute_rhythm_score(leg_dists: List[float]) -> float:
    """
    Score de rythme [0–1] basé sur la variété des longueurs de jambes.

    Un bon parcours d'orientation alterne longues et courtes jambes
    plutôt que d'être monotone. On recherche un coefficient de variation
    (CV = écart-type / moyenne) proche de 0.45.

    Pénalise :
      - CV < 0.15 : parcours monotone (toutes les jambes identiques)
      - CV > 0.85 : parcours trop chaotique (jambes sans cohérence)

    Args:
        leg_dists: Distances à vol d'oiseau de chaque jambe (m).

    Returns:
        Score [0–1], 1 = rythme idéal.
    """
    if len(leg_dists) < 2:
        return 0.5

    mean = statistics.mean(leg_dists)
    if mean < 1e-6:
        return 0.0

    std = statistics.stdev(leg_dists)
    cv = std / mean

    # Gaussienne centrée sur CV cible = 0.45
    # Paramètre -8.0 : pénalisation forte des parcours monotones (CV ≈ 0)
    return math.exp(-8.0 * (cv - 0.45) ** 2)


# ---------------------------------------------------------------------------
# Variation — diversité des types et directions
# ---------------------------------------------------------------------------

def compute_variation_score(
    legs: "List[LegInfo]",
    controls: "List[ControlCandidate]",
) -> float:
    """
    Score de variation [0–1] — diversité des types et changements de cap.

    Composantes :
      1. Pénalité si ≥ 3 postes consécutifs du même type (monotonie).
      2. Taux de types distincts parmi les arrivées de jambes.
      3. Irrégularité des changements de direction (non-spirale).

    Args:
        legs:     Liste de LegInfo du parcours.
        controls: Séquence complète de ControlCandidate.

    Returns:
        Score [0–1].
    """
    if not legs:
        return 0.5

    scores: List[float] = []

    # 1. Absence de séquences monotones (même type de poste consécutif)
    max_run = _max_type_run(legs)
    monotony_penalty = max(0.0, 1.0 - (max_run - 2) * 0.30)
    scores.append(max(0.0, min(1.0, monotony_penalty)))

    # 2. Diversité des types d'arrivée (ratio types_distincts / nb_jambes)
    arrival_types = {lg.to_type for lg in legs}
    type_ratio = len(arrival_types) / max(1, len(legs))
    type_div = min(1.0, type_ratio * 1.8)   # 1 type/2 jambes ≈ 0.9
    scores.append(type_div)

    # 3. Irrégularité des changements de cap
    bearing_changes = [lg.bearing_change_deg for lg in legs if lg.bearing_change_deg > 0]
    if len(bearing_changes) >= 2:
        bc_std = statistics.stdev(bearing_changes)
        bc_variation = min(1.0, bc_std / 35.0)
        scores.append(bc_variation)

    return statistics.mean(scores)


def _max_type_run(legs: "List[LegInfo]") -> int:
    """Longueur maximale d'une séquence de types identiques consécutifs."""
    if not legs:
        return 0
    run = max_run = 1
    for i in range(1, len(legs)):
        if legs[i].to_type == legs[i - 1].to_type:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 1
    return max_run


# ---------------------------------------------------------------------------
# Flow — cohérence globale, absence de dog-legs / demi-tours
# ---------------------------------------------------------------------------

def compute_flow_score(legs: "List[LegInfo]") -> float:
    """
    Score de flow global [0–1].

    Pénalise :
      - Dog-legs (bearing_change < 25°) : l'arrivée au poste révèle le suivant.
      - Demi-tours (bearing_change > 155°) : revenir sur ses pas.
      - Deux jambes très courtes consécutives (< 80 m) : pas de navigation.

    Args:
        legs: Liste de LegInfo calculées dans Course.compute_metrics().

    Returns:
        Score [0–1], 1 = flow parfait.
    """
    if not legs:
        return 0.5

    n = len(legs)
    penalty = 0.0

    for i, leg in enumerate(legs):
        bc = leg.bearing_change_deg

        # Dog-leg (changement < 25° → même direction que le leg précédent)
        if i > 0 and bc < 25.0:
            penalty += 0.40

        # Demi-tour (revenir en arrière) — très pénalisé en CO
        if bc > 155.0:
            penalty += 0.60

        # Deux courtes jambes consécutives
        if (i > 0
                and legs[i - 1].straight_dist_m < 80.0
                and leg.straight_dist_m < 80.0):
            penalty += 0.20

    raw = 1.0 - (penalty / max(1, n))
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Qualité intrinsèque des postes
# ---------------------------------------------------------------------------

def score_controls_quality(controls: "List[ControlCandidate]") -> float:
    """
    Score moyen de qualité intrinsèque des postes intermédiaires [0–1].

    Combine attractivité, isolation et landmark_strength.
    Ignore le départ (index 0) et l'arrivée (dernier).

    Args:
        controls: Séquence complète de ControlCandidate.

    Returns:
        Score [0–1], 0.5 si aucun poste intermédiaire.
    """
    intermediate = controls[1:-1] if len(controls) > 2 else []
    if not intermediate:
        return 0.5

    scores: List[float] = []
    for c in intermediate:
        landmark = getattr(c, "landmark_strength", 0.5)
        isolation = getattr(c, "isolation_score", 1.0)
        q = (
            c.attractiveness_score * 0.45
            + isolation             * 0.30
            + landmark              * 0.25
        )
        scores.append(min(1.0, max(0.0, q)))

    return statistics.mean(scores)


# ---------------------------------------------------------------------------
# Qualité des jambes
# ---------------------------------------------------------------------------

def score_legs_quality(legs: "List[LegInfo]") -> float:
    """
    Score moyen de qualité métier des jambes [0–1].

    Combine choix d'itinéraire, courabilité et difficulté maîtrisée.

    Un bon leg en CO a :
      - Un choix d'itinéraire non trivial (exploration, décision)
      - Une bonne courabilité (l'athlète peut courir)
      - Une difficulté technique maîtrisée (ni trop facile, ni impossible)

    Args:
        legs: Liste de LegInfo.

    Returns:
        Score [0–1], 0.5 si pas de jambes.
    """
    if not legs:
        return 0.5

    scores: List[float] = []
    for lg in legs:
        rcc  = getattr(lg, "route_choice_complexity", 0.0)
        runn = getattr(lg, "runnability", 0.8)
        tech = getattr(lg, "technical_difficulty", 0.0)

        # Choix d'itinéraire + courabilité + difficulté maîtrisée
        q = rcc * 0.40 + runn * 0.35 + (1.0 - tech) * 0.25
        scores.append(min(1.0, max(0.0, q)))

    return statistics.mean(scores)
