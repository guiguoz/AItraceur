"""Distance cosinus entre CourseProfiles + sélection diversifiée (Phase 5)."""
from __future__ import annotations

from typing import List, Tuple

import numpy as np

from .course_profile import CourseProfile


def course_profile_vector(cp: CourseProfile) -> np.ndarray:
    """Vecteur numérique 11-dim extrait d'un CourseProfile. NaN = donnée absente."""
    hist = cp.leg_intent_histogram
    total = max(1, sum(hist.values()))
    nav_f = hist.get("navigation", 0) / total
    ori_f = hist.get("orienteering", 0) / total
    spd_f = hist.get("speed", 0) / total
    return np.array([
        cp.technical_balance,
        cp.route_choice_density,
        cp.alternation / 100.0,
        cp.climb_distribution,
        cp.map_coverage,
        cp.zone_balance,
        min(1.0, cp.transition_count / 10.0),
        cp.transition_strength,
        nav_f,
        ori_f,
        spd_f,
    ], dtype=np.float32)


def cosine_distance(v1: np.ndarray, v2: np.ndarray) -> float:
    """Distance cosinus ∈ [0, 1]. Ignore les dimensions NaN."""
    mask = ~(np.isnan(v1) | np.isnan(v2))
    if not mask.any():
        return 0.0
    a, b = v1[mask], v2[mask]
    norms = np.linalg.norm(a) * np.linalg.norm(b)
    if norms == 0:
        return 0.0
    return float(1.0 - np.dot(a, b) / norms)


def select_diverse_circuits(
    circuits_with_profiles: List[Tuple],
    n_select: int = 3,
) -> List[Tuple]:
    """
    Sélectionne n_select circuits maximisant la diversité intra-groupe.

    circuits_with_profiles : list[(Circuit, CourseProfile)] triés par fitness desc.
    Retourne : sous-liste de longueur ≤ n_select (greedy max-min-distance).
    """
    if len(circuits_with_profiles) <= n_select:
        return circuits_with_profiles

    vectors = [course_profile_vector(cp) for _, cp in circuits_with_profiles]
    selected = [0]  # Toujours partir du meilleur

    while len(selected) < n_select:
        best_idx = -1
        best_min_dist = -1.0
        for i in range(len(vectors)):
            if i in selected:
                continue
            min_d = min(cosine_distance(vectors[i], vectors[j]) for j in selected)
            if min_d > best_min_dist:
                best_min_dist = min_d
                best_idx = i
        if best_idx < 0:
            break
        selected.append(best_idx)

    return [circuits_with_profiles[i] for i in selected]
