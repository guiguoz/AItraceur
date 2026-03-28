"""
Couche 6 (optionnelle) — Algorithme Génétique pour la génération de parcours.

Le GA est un outil complémentaire à l'optimisation locale, pas le cœur de
la solution. Il est utile pour explorer un espace de solutions plus large
quand le hill-climbing se bloque dans un minimum local.

Opérateurs :
  - Sélection    : tournoi (tournoi_size = 3)
  - Croisement   : Order Crossover (OX) sur les postes intermédiaires
  - Mutation     : opérateurs de local_opt
  - Élitisme     : top-N préservés à chaque génération

Exemple :
    result = run_genetic_algorithm(
        candidates, cost_matrix, profile,
        population_size=30, n_generations=50,
    )
    best_course = result.best_course
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Optional

from ..controls.candidate import ControlCandidate
from ..matrix.cost_matrix import CostMatrix
from ..model.course import Course
from ..profiles import CourseProfile
from ..scoring.scorer import score_course
from .constructive import generate_initial_course
from .local_opt import _apply_random_mutation, improve_course_local


# ---------------------------------------------------------------------------
# Résultat du GA
# ---------------------------------------------------------------------------

@dataclass
class GAResult:
    """Résultat d'une exécution de l'algorithme génétique."""
    best_course: Course
    best_score: float
    n_generations: int
    elapsed_s: float
    score_history: list[float] = field(default_factory=list)   # max score par génération


# ---------------------------------------------------------------------------
# Opérateurs génétiques
# ---------------------------------------------------------------------------

def _ox_crossover(
    parent_a: Course,
    parent_b: Course,
    rng: random.Random,
) -> Course:
    """
    Order Crossover (OX) sur les postes intermédiaires.

    Préserve le départ (parent_a[0]) et l'arrivée (parent_a[-1]).
    Les postes intermédiaires sont recombinés par OX.
    """
    pa = parent_a.controls[1:-1]   # intermédiaires
    pb = parent_b.controls[1:-1]

    n = len(pa)
    if n == 0:
        return parent_a

    i1, i2 = sorted(rng.sample(range(n), 2))
    segment = pa[i1:i2 + 1]
    seg_ids = {c.id for c in segment}

    # Remplir le reste depuis parent_b dans l'ordre
    remaining = [c for c in pb if c.id not in seg_ids]

    child_inter = (
        remaining[:i1]
        + segment
        + remaining[i1:]
    )
    child_inter = child_inter[:len(pa)]   # garder la même taille

    from dataclasses import replace
    child_controls = [parent_a.controls[0]] + child_inter + [parent_a.controls[-1]]
    return replace(parent_a, controls=child_controls, metrics=None, score=None)


def _tournament_select(
    population: list[Course],
    rng: random.Random,
    tournament_size: int = 3,
) -> Course:
    """Sélection par tournoi."""
    contestants = rng.sample(population, min(tournament_size, len(population)))
    return max(contestants, key=lambda c: c.score or 0.0)


# ---------------------------------------------------------------------------
# Algorithme génétique principal
# ---------------------------------------------------------------------------

def run_genetic_algorithm(
    candidates: list[ControlCandidate],
    cost_matrix: CostMatrix,
    profile: CourseProfile,
    *,
    population_size: int = 30,
    n_generations: int = 50,
    elite_count: int = 3,
    crossover_rate: float = 0.7,
    mutation_rate: float = 0.3,
    local_opt_per_gen: int = 2,      # Itérations d'opt locale par individu élite
    rng: Optional[random.Random] = None,
    timeout_s: Optional[float] = None,
    progress_callback: Optional[callable] = None,
) -> GAResult:
    """
    Exécute l'algorithme génétique et retourne le meilleur parcours.

    Args:
        candidates:          Candidats postes disponibles.
        cost_matrix:         Matrice de coûts.
        profile:             Profil de course.
        population_size:     Taille de la population.
        n_generations:       Nombre de générations.
        elite_count:         Nombre d'élites préservés.
        crossover_rate:      Probabilité de croisement.
        mutation_rate:       Probabilité de mutation.
        local_opt_per_gen:   Itérations d'opt locale appliquées aux élites.
        rng:                 Générateur aléatoire.
        timeout_s:           Timeout en secondes (None = pas de limite).
        progress_callback:   Appelé avec (gen, best_score) à chaque génération.

    Returns:
        GAResult avec le meilleur Course trouvé.
    """
    _rng = rng or random.Random()
    start_time = time.monotonic()
    score_history: list[float] = []

    # --- Population initiale ---
    population: list[Course] = []
    for _ in range(population_size):
        try:
            course = generate_initial_course(candidates, cost_matrix, profile, rng=_rng)
            course = course.compute_metrics(cost_matrix)
            bd = score_course(course, cost_matrix, profile)
            course = course.with_score(bd.global_score)
            population.append(course)
        except Exception:
            pass

    if not population:
        raise RuntimeError("Impossible de générer une population initiale.")

    best = max(population, key=lambda c: c.score or 0.0)

    # --- Boucle de générations ---
    for gen in range(n_generations):
        if timeout_s and (time.monotonic() - start_time) > timeout_s:
            break

        # Tri par score décroissant
        population.sort(key=lambda c: c.score or 0.0, reverse=True)
        gen_best = population[0]
        score_history.append(gen_best.score or 0.0)

        if (gen_best.score or 0.0) > (best.score or 0.0):
            best = gen_best

        if progress_callback:
            progress_callback(gen, best.score or 0.0)

        # Élitisme : conserver les meilleurs
        elites = population[:elite_count]

        # Appliquer opt locale sur les élites
        improved_elites = []
        for elite in elites:
            improved = improve_course_local(
                elite, candidates, cost_matrix, profile,
                n_iter=local_opt_per_gen * 10,
                rng=_rng,
            )
            improved_elites.append(improved)

        # Nouvelle population
        new_population: list[Course] = list(improved_elites)

        while len(new_population) < population_size:
            if _rng.random() < crossover_rate and len(population) >= 2:
                parent_a = _tournament_select(population, _rng)
                parent_b = _tournament_select(population, _rng)
                if parent_a is not parent_b:
                    child = _ox_crossover(parent_a, parent_b, _rng)
                else:
                    child = parent_a
            else:
                child = _tournament_select(population, _rng)

            # Mutation
            if _rng.random() < mutation_rate:
                mutated = _apply_random_mutation(child, candidates, cost_matrix, _rng)
                if mutated is not None:
                    child = mutated

            child = child.compute_metrics(cost_matrix)
            bd = score_course(child, cost_matrix, profile)
            child = child.with_score(bd.global_score)
            new_population.append(child)

        population = new_population

    elapsed = time.monotonic() - start_time

    return GAResult(
        best_course=best,
        best_score=best.score or 0.0,
        n_generations=len(score_history),
        elapsed_s=elapsed,
        score_history=score_history,
    )
