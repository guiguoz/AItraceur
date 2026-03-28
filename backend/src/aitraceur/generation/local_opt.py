"""
Optimisation locale d'un parcours existant.

Opérateurs disponibles :
  - swap(i, j)          : échange les postes i et j
  - replace(i, cand)    : remplace le poste i par un candidat voisin
  - insert(i, cand)     : insère un poste entre i et i+1
  - remove(i)           : supprime le poste i

Stratégie par défaut : hill-climbing avec redémarrage aléatoire.
Option : simulated annealing (SA) pour s'échapper des minima locaux.

Exemple :
    improved = improve_course_local(
        course, candidates, cost_matrix, profile, n_iter=500
    )
    print(improved.score, ">", course.score)
"""
from __future__ import annotations

import math
import random
from dataclasses import replace
from enum import Enum
from typing import Callable, Optional

from ..controls.candidate import ControlCandidate
from ..matrix.cost_matrix import CostMatrix
from ..model.course import Course
from ..profiles import CourseProfile
from ..scoring.scorer import score_course


# ---------------------------------------------------------------------------
# Opérateurs de mutation
# ---------------------------------------------------------------------------

class MutationType(str, Enum):
    SWAP = "swap"
    REPLACE = "replace"
    INSERT = "insert"
    REMOVE = "remove"
    REVERSE_SEGMENT = "reverse_segment"


def _mut_swap(course: Course, rng: random.Random) -> Optional[Course]:
    """Échange deux postes intermédiaires."""
    n = len(course.controls)
    if n < 4:
        return None
    # Garde le départ (0) et l'arrivée (n-1) fixes
    i = rng.randint(1, n - 2)
    j = rng.randint(1, n - 2)
    if i == j:
        return None
    return course.with_swap(i, j)


def _mut_replace(
    course: Course,
    candidates: list[ControlCandidate],
    cost_matrix: CostMatrix,
    rng: random.Random,
) -> Optional[Course]:
    """Remplace un poste intermédiaire par un candidat voisin non utilisé."""
    n = len(course.controls)
    if n < 3:
        return None

    idx = rng.randint(1, n - 2)   # poste intermédiaire
    current = course.controls[idx]
    used_ids = {c.id for c in course.controls}

    # Candidats voisins de current non utilisés
    neighbors = [
        (c, d) for c, d in cost_matrix.feasible_pairs(
            current,
            max_dist_m=course.profile.targets.leg_m_max,
        )
        if c.id not in used_ids
    ]
    if not neighbors:
        return None

    # Préférer un candidat de même niveau technique (maintient la cohérence)
    same_td = [(c, d) for c, d in neighbors
               if c.technical_level == current.technical_level]
    pool = same_td or neighbors
    new_cand = rng.choice([c for c, _ in pool[:8]])

    return course.with_control_at(idx, new_cand)


def _mut_insert(
    course: Course,
    candidates: list[ControlCandidate],
    cost_matrix: CostMatrix,
    rng: random.Random,
) -> Optional[Course]:
    """Insère un poste entre deux postes consécutifs."""
    targets = course.profile.targets
    n = len(course.controls)
    if n >= targets.controls_max:
        return None

    # Choisir une jambe longue (plus de gain potentiel)
    long_legs = sorted(
        range(n - 1),
        key=lambda i: course.controls[i].geom.distance(course.controls[i + 1].geom),
        reverse=True,
    )
    if not long_legs:
        return None

    # Essayer sur la jambe la plus longue parmi les top-3
    for leg_i in long_legs[:3]:
        ca = course.controls[leg_i]
        cb = course.controls[leg_i + 1]
        used_ids = {c.id for c in course.controls}

        # Chercher un candidat entre les deux extrémités de la jambe
        midpoint = ca.__class__(
            id="_mid",
            geom=ca.geom.__class__(
                (ca.x + cb.x) / 2,
                (ca.y + cb.y) / 2,
            ),
            detail_type=ca.detail_type,
            attractiveness_score=0,
            readability_score=0,
            allowed_profiles=frozenset(),
        )

        # Chercher dans cost_matrix les candidats proches du milieu
        nearby = [
            c for c in candidates
            if c.id not in used_ids
            and ca.geom.distance(c.geom) < targets.leg_m_max
            and cb.geom.distance(c.geom) < targets.leg_m_max
        ]

        if nearby:
            new_cand = rng.choice(nearby[:10])
            return course.with_insertion(leg_i + 1, new_cand)

    return None


def _mut_remove(
    course: Course,
    rng: random.Random,
) -> Optional[Course]:
    """Supprime un poste intermédiaire."""
    targets = course.profile.targets
    n = len(course.controls)
    if n - 1 <= targets.controls_min:
        return None

    idx = rng.randint(1, n - 2)
    return course.with_removal(idx)


def _mut_reverse_segment(
    course: Course,
    rng: random.Random,
) -> Optional[Course]:
    """Inverse un segment de la séquence (2-opt move)."""
    n = len(course.controls)
    if n < 5:
        return None
    i = rng.randint(1, n - 3)
    j = rng.randint(i + 1, n - 2)
    new_controls = (
        course.controls[:i]
        + list(reversed(course.controls[i:j + 1]))
        + course.controls[j + 1:]
    )
    return replace(course, controls=new_controls, metrics=None, score=None)


# ---------------------------------------------------------------------------
# Sélection d'opérateur
# ---------------------------------------------------------------------------

_OP_WEIGHTS = {
    MutationType.SWAP: 0.30,
    MutationType.REPLACE: 0.35,
    MutationType.INSERT: 0.15,
    MutationType.REMOVE: 0.10,
    MutationType.REVERSE_SEGMENT: 0.10,
}


def _apply_random_mutation(
    course: Course,
    candidates: list[ControlCandidate],
    cost_matrix: CostMatrix,
    rng: random.Random,
) -> Optional[Course]:
    """Choisit et applique un opérateur aléatoire."""
    ops = list(_OP_WEIGHTS.keys())
    weights = [_OP_WEIGHTS[o] for o in ops]
    op = rng.choices(ops, weights=weights, k=1)[0]

    if op == MutationType.SWAP:
        return _mut_swap(course, rng)
    elif op == MutationType.REPLACE:
        return _mut_replace(course, candidates, cost_matrix, rng)
    elif op == MutationType.INSERT:
        return _mut_insert(course, candidates, cost_matrix, rng)
    elif op == MutationType.REMOVE:
        return _mut_remove(course, rng)
    elif op == MutationType.REVERSE_SEGMENT:
        return _mut_reverse_segment(course, rng)
    return None


# ---------------------------------------------------------------------------
# Hill-climbing + Simulated Annealing
# ---------------------------------------------------------------------------

def improve_course_local(
    course: Course,
    candidates: list[ControlCandidate],
    cost_matrix: CostMatrix,
    profile: Optional[CourseProfile] = None,
    *,
    n_iter: int = 300,
    use_sa: bool = False,
    sa_temp_start: float = 10.0,
    sa_temp_end: float = 0.5,
    rng: Optional[random.Random] = None,
) -> Course:
    """
    Améliore un parcours par optimisation locale.

    Stratégie :
      - Hill-climbing (par défaut) : accepte uniquement les améliorations.
      - Simulated Annealing (use_sa=True) : accepte parfois les dégradations
        pour s'échapper des minima locaux.

    Args:
        course:         Parcours initial.
        candidates:     Liste complète des ControlCandidate.
        cost_matrix:    Matrice de coûts.
        profile:        Profil (default = course.profile).
        n_iter:         Nombre d'itérations.
        use_sa:         Active le simulated annealing.
        sa_temp_start:  Température initiale (SA).
        sa_temp_end:    Température finale (SA).
        rng:            Générateur aléatoire.

    Returns:
        Meilleur Course trouvé (score >= initial).
    """
    _profile = profile or course.profile
    _rng = rng or random.Random()

    # Score initial
    current = course.compute_metrics(cost_matrix)
    current_bd = score_course(current, cost_matrix, _profile)
    current = current.with_score(current_bd.global_score)
    best = current
    best_score = current_bd.global_score

    for it in range(n_iter):
        # Génère un voisin
        neighbor = _apply_random_mutation(
            current, candidates, cost_matrix, _rng
        )
        if neighbor is None:
            continue

        neighbor = neighbor.compute_metrics(cost_matrix)
        nb_bd = score_course(neighbor, cost_matrix, _profile)
        nb_score = nb_bd.global_score
        neighbor = neighbor.with_score(nb_score)

        # Critère d'acceptation
        if use_sa:
            t = sa_temp_start * (sa_temp_end / sa_temp_start) ** (it / max(1, n_iter - 1))
            delta = nb_score - (current.score or 0.0)
            if delta >= 0 or _rng.random() < math.exp(delta / max(1e-9, t)):
                current = neighbor
        else:
            if nb_score > (current.score or 0.0):
                current = neighbor

        if nb_score > best_score:
            best = neighbor
            best_score = nb_score

    return best
