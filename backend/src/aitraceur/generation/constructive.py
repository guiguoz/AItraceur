"""
Génération constructive d'un premier parcours plausible.

Heuristiques métier utilisées :
  1. Sélection du départ : candidat avec bon score composite, pas en bordure.
  2. Construction greedy : à chaque étape, choisir le prochain poste qui
     maximise un score local (coût + qualité + variété + direction).
  3. Contraintes satisfaites à la construction :
     - longueur de jambe dans [leg_m_min, leg_m_max]
     - pas deux fois le même type consécutivement (si possible)
     - distance totale restante compatible avec cible
  4. Arrivée : poste le plus proche du départ (zone de départ/arrivée compacte).

Exemple :
    course = generate_initial_course(candidates, cost_matrix, profile)
"""
from __future__ import annotations

import math
import random
from typing import Optional

from ..controls.candidate import ControlCandidate, DetailType
from ..controls.enricher import enrich_candidates, select_elite_candidates
from ..matrix.cost_matrix import CostMatrix
from ..model.course import Course
from ..profiles import CourseProfile


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MIN_CANDIDATE_SCORE = 0.30   # Seuil minimal de composite_score pour être inclus
_GREEDY_BEAM_WIDTH = 5        # Nombre de candidats explorés à chaque étape


def generate_initial_course(
    candidates: list[ControlCandidate],
    cost_matrix: CostMatrix,
    profile: CourseProfile,
    *,
    rng: Optional[random.Random] = None,
    max_attempts: int = 10,
    use_elite: bool = False,
    max_elite: int = 300,
    elite_min_sep_m: float = 25.0,
) -> Course:
    """
    Génère un premier parcours plausible par construction greedy.

    Le parcours respecte (approximativement) :
      - le nombre cible de postes,
      - les bornes de longueur de jambe,
      - la distance totale cible.

    Args:
        candidates:      Liste de ControlCandidate autorisés pour le profil.
        cost_matrix:     Matrice de coûts précalculée.
        profile:         Profil de course pilotant la génération.
        rng:             Générateur aléatoire (pour reproductibilité).
        max_attempts:    Nombre de tentatives si la construction échoue.
        use_elite:       Si True, enrichit les candidats et sélectionne les
                         meilleurs avant la construction (réduit la combinatoire).
        max_elite:       Nombre maximum de candidats élite à conserver.
        elite_min_sep_m: Distance minimale entre deux candidats élite (m).

    Returns:
        Course constructif initial.
    """
    _rng = rng or random.Random()

    # Réduction combinatoire optionnelle
    if use_elite and len(candidates) > max_elite:
        enriched = enrich_candidates(candidates)
        candidates = select_elite_candidates(
            enriched,
            max_count=max_elite,
            min_separation_m=elite_min_sep_m,
        )

    # Filtrer les candidats autorisés et de qualité suffisante
    valid = [
        c for c in candidates
        if c.is_allowed_for_profile(profile.id)
        and c.composite_score >= _MIN_CANDIDATE_SCORE
    ]

    if len(valid) < profile.targets.controls_min:
        # Fallback : prendre tous les candidats triés par score
        valid = sorted(candidates, key=lambda c: c.composite_score, reverse=True)

    if len(valid) < 2:
        raise ValueError(
            f"Pas assez de candidats ({len(valid)}) pour générer un parcours "
            f"de profil {profile.id!r}."
        )

    for attempt in range(max_attempts):
        course = _try_build_course(valid, cost_matrix, profile, _rng)
        if course is not None and len(course.controls) >= profile.targets.controls_min:
            return course

    # Dernier recours : parcours minimal
    return _fallback_course(valid, cost_matrix, profile, _rng)


def _try_build_course(
    valid: list[ControlCandidate],
    cost_matrix: CostMatrix,
    profile: CourseProfile,
    rng: random.Random,
) -> Optional[Course]:
    """Tente une construction greedy unique."""
    targets = profile.targets

    # 1. Départ : parmi les top-20% en score composite
    top_k = max(5, len(valid) // 5)
    pool_start = sorted(valid, key=lambda c: c.composite_score, reverse=True)[:top_k]
    start = rng.choice(pool_start)

    controls: list[ControlCandidate] = [start]
    used_ids: set[str] = {start.id}
    total_dist = 0.0
    last_type: Optional[DetailType] = start.detail_type

    # Combien de postes intermédiaires viser ?
    # On réserve au moins 1 candidat pour l'arrivée
    max_intermediate = max(0, len(valid) - 2)  # -1 départ, -1 arrivée
    n_intermediate = rng.randint(
        targets.controls_target - 2,
        targets.controls_target + 2,
    )
    n_intermediate = max(
        targets.controls_min - 2,
        min(targets.controls_max - 2, n_intermediate, max_intermediate),
    )

    for step in range(n_intermediate):
        remaining_steps = n_intermediate - step
        dist_so_far = total_dist
        dist_remaining = targets.distance_m_target - dist_so_far

        # Longueur de jambe idéale pour ce pas
        ideal_leg = dist_remaining / (remaining_steps + 1) if remaining_steps > 0 else targets.mean_leg_m

        current = controls[-1]
        # Trouver le meilleur prochain candidat
        next_c = _pick_next(
            current, valid, cost_matrix, used_ids, profile,
            ideal_leg=ideal_leg,
            last_type=last_type,
            rng=rng,
        )
        if next_c is None:
            break

        controls.append(next_c)
        used_ids.add(next_c.id)
        total_dist += current.geom.distance(next_c.geom)
        last_type = next_c.detail_type

    if len(controls) < 2:
        return None

    # Arrivée : poste proche du départ (sans être le départ)
    finish = _pick_finish(start, controls, valid, cost_matrix, profile, rng)
    controls.append(finish)

    return Course(controls=controls, profile=profile)


def _pick_next(
    current: ControlCandidate,
    valid: list[ControlCandidate],
    cost_matrix: CostMatrix,
    used_ids: set[str],
    profile: CourseProfile,
    *,
    ideal_leg: float,
    last_type: Optional[DetailType],
    rng: random.Random,
) -> Optional[ControlCandidate]:
    """
    Choisit le prochain poste en maximisant un score local.

    Score local = pondération de :
      - Distance à l'idéal (proximité à ideal_leg)
      - Qualité du candidat (composite_score)
      - Diversité (pénalité si même type que le précédent)
    """
    targets = profile.targets

    # Candidats accessibles dans la plage de jambe
    feasible = []
    for pair in cost_matrix.feasible_pairs(
        current,
        max_dist_m=targets.leg_m_max * 1.2,
    ):
        cand, cost = pair
        if cand.id in used_ids:
            continue
        dist = current.geom.distance(cand.geom)
        if dist < targets.leg_m_min * 0.5:
            continue
        feasible.append((cand, dist, cost))

    if not feasible:
        return None

    # Score local pour chaque candidat
    def local_score(item: tuple) -> float:
        cand, dist, cost = item
        # Proximité à l'idéal
        dist_gap = abs(dist - ideal_leg) / max(1.0, ideal_leg)
        dist_s = math.exp(-2.0 * dist_gap)

        # Qualité enrichie (inclut isolation + landmark si disponible)
        qual_s = getattr(cand, "quality_score", cand.composite_score)

        # Pénalité type identique
        type_penalty = 0.7 if cand.detail_type == last_type else 1.0

        return dist_s * 0.38 + qual_s * 0.47 + (type_penalty - 1.0) * 0.15

    # Beam search : prendre les meilleurs avec un peu d'aléatoire
    scored = sorted(feasible, key=local_score, reverse=True)[:_GREEDY_BEAM_WIDTH]
    if not scored:
        return None

    # Sélection pondérée par le score (soft-max)
    scores = [local_score(item) for item in scored]
    min_s = min(scores)
    weights = [max(0.01, s - min_s + 0.1) for s in scores]
    total_w = sum(weights)
    probs = [w / total_w for w in weights]

    # Choix probabiliste
    r = rng.random()
    cumul = 0.0
    for item, p in zip(scored, probs):
        cumul += p
        if r <= cumul:
            return item[0]
    return scored[0][0]


def _pick_finish(
    start: ControlCandidate,
    controls: list[ControlCandidate],
    valid: list[ControlCandidate],
    cost_matrix: CostMatrix,
    profile: CourseProfile,
    rng: random.Random,
) -> ControlCandidate:
    """
    Choisit l'arrivée : poste non utilisé, pas trop loin du départ,
    et avec une bonne jambe depuis le dernier poste.
    """
    last = controls[-1]
    used_ids = {c.id for c in controls}
    targets = profile.targets

    candidates_finish = [
        c for c in valid
        if c.id not in used_ids
        and targets.leg_m_min * 0.5 <= last.geom.distance(c.geom) <= targets.leg_m_max
    ]

    if not candidates_finish:
        available = [c for c in valid if c.id not in used_ids]
        if not available:
            # Tous les candidats sont utilisés → le départ fait aussi office d'arrivée
            return start
        return min(available, key=lambda c: c.geom.distance(start.geom))

    # Préférer un poste proche du départ (esthétique classique d'un circuit)
    return min(
        candidates_finish,
        key=lambda c: c.geom.distance(start.geom),
    )


def _fallback_course(
    valid: list[ControlCandidate],
    cost_matrix: CostMatrix,
    profile: CourseProfile,
    rng: random.Random,
) -> Course:
    """Parcours de secours : prend les N meilleurs candidats dans l'ordre."""
    n = profile.targets.controls_target
    top = sorted(valid, key=lambda c: c.composite_score, reverse=True)[:n]
    if len(top) < 2:
        top = valid[:2]
    return Course(controls=top, profile=profile)
