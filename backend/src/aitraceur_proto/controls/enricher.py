"""
Enrichissement contextuel et sélection élite des candidats postes.

Deux responsabilités :

  1. enrich_candidates() — calcule les propriétés contextuelles de chaque
     candidat à partir de son voisinage spatial (scipy KDTree) :
     isolation, visibilité, potentiel de piège, force comme repère.

  2. select_elite_candidates() — réduit la liste à N candidats en
     maximisant qualité ET distribution spatiale (algorithme glouton).

Ces fonctions s'insèrent avant build_cost_matrix pour réduire la
combinatoire tout en conservant les postes les plus intéressants.

Exemple :
    enriched = enrich_candidates(candidates)
    elite    = select_elite_candidates(enriched, max_count=250)
    cm       = build_cost_matrix(elite, movement_model, profile)
"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import List, Optional

try:
    from scipy.spatial import cKDTree as KDTree
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False

from .candidate import ControlCandidate


# ---------------------------------------------------------------------------
# Tables de référence
# ---------------------------------------------------------------------------

# Rayon de détection des voisins (zone de contrôle IOF ≈ 30 m)
_ISOLATION_RADIUS_M: float = 30.0
_MAX_VISIBILITY_M: float = 50.0
_MIN_VISIBILITY_M: float = 8.0

# Force de repère par type de détail (basé sur la saillance perceptive de l'objet)
_LANDMARK_BY_TYPE: dict[str, float] = {
    "tower": 1.00,
    "building": 1.00,
    "road_junction": 0.95,
    "building_corner": 0.90,
    "bridge": 0.90,
    "path_junction": 0.85,
    "wall_corner": 0.82,
    "boulder": 0.80,
    "wall_end": 0.78,
    "pond_edge": 0.75,
    "cliff_foot": 0.75,
    "stream_junction": 0.72,
    "cliff_top": 0.70,
    "knoll": 0.70,
    "gate": 0.70,
    "fence_corner": 0.65,
    "hill_top": 0.65,
    "path_bend": 0.63,
    "pit": 0.60,
    "boulder_cluster": 0.58,   # groupe = moins isolé
    "depression": 0.55,
    "reentrant": 0.52,
    "clearing_corner": 0.50,
    "veg_boundary": 0.45,
    "spur": 0.45,
    "stream_bend": 0.42,
    "earthwall_end": 0.40,
    "marsh_edge": 0.38,
}

_DEFAULT_LANDMARK: float = 0.50


# ---------------------------------------------------------------------------
# Enrichissement
# ---------------------------------------------------------------------------

def enrich_candidates(
    candidates: List[ControlCandidate],
    *,
    isolation_radius_m: float = _ISOLATION_RADIUS_M,
    max_visibility_m: float = _MAX_VISIBILITY_M,
) -> List[ControlCandidate]:
    """
    Calcule les propriétés contextuelles de chaque candidat.

    Propriétés calculées :
      - isolation_score    : éloignement des objets du même type [0–1].
      - visibility_radius  : distance estimée de détection visuelle (m).
      - trap_potential     : risque de confusion avec des voisins similaires [0–1].
      - landmark_strength  : force comme point de repère iconique [0–1].
      - approach_directions: azimuts naturels d'accès depuis les voisins proches.

    Si scipy n'est pas installé, seul landmark_strength est affecté.

    Args:
        candidates:         Liste de ControlCandidate à enrichir.
        isolation_radius_m: Rayon de recherche des voisins (m).
        max_visibility_m:   Visibilité maximale (terrain dégagé, m).

    Returns:
        Nouvelle liste de ControlCandidate enrichis (objets distincts).
    """
    if not candidates:
        return []

    if not _SCIPY_OK:
        return [_apply_landmark(c) for c in candidates]

    coords = [(c.x, c.y) for c in candidates]
    tree = KDTree(coords)
    enriched: List[ControlCandidate] = []

    for i, cand in enumerate(candidates):
        # Voisins dans le rayon d'isolation (soi-même exclu)
        nb_idx: List[int] = [
            j for j in tree.query_ball_point((cand.x, cand.y), r=isolation_radius_m)
            if j != i
        ]

        # Voisins du MÊME type → confusion possible → piège
        same_type = sum(
            1 for j in nb_idx
            if candidates[j].detail_type == cand.detail_type
        )
        total_nb = len(nb_idx)

        # isolation_score : 1 = seul de son type, 0 = entouré de copies
        isolation = 1.0 / (1.0 + same_type)

        # trap_potential : plus il y a de copies voisines, plus c'est un piège
        trap = min(1.0, same_type * 0.25)

        # visibility_radius : densité locale ≈ indicateur de végétation
        density_factor = math.exp(-total_nb * 0.12)
        visibility = max(_MIN_VISIBILITY_M, max_visibility_m * density_factor)

        # approach_directions : azimuts depuis les voisins
        approach = _approach_dirs(cand, candidates, nb_idx)

        # landmark_strength depuis le type
        landmark = _LANDMARK_BY_TYPE.get(cand.detail_type.value, _DEFAULT_LANDMARK)

        enriched.append(replace(
            cand,
            isolation_score=round(isolation, 4),
            trap_potential=round(trap, 4),
            visibility_radius=round(visibility, 2),
            approach_directions=approach,
            landmark_strength=landmark,
        ))

    return enriched


def _apply_landmark(cand: ControlCandidate) -> ControlCandidate:
    """Affecte uniquement landmark_strength (fallback sans scipy)."""
    landmark = _LANDMARK_BY_TYPE.get(cand.detail_type.value, _DEFAULT_LANDMARK)
    return replace(cand, landmark_strength=landmark)


def _approach_dirs(
    cand: ControlCandidate,
    candidates: List[ControlCandidate],
    neighbor_indices: List[int],
) -> List[float]:
    """Azimuts naturels d'accès depuis les voisins proches (max 8)."""
    dirs: List[float] = []
    for j in neighbor_indices[:8]:
        other = candidates[j]
        dx = cand.x - other.x
        dy = cand.y - other.y
        if abs(dx) + abs(dy) < 1e-6:
            continue
        az = math.degrees(math.atan2(dx, dy)) % 360.0
        dirs.append(round(az, 1))
    return sorted(dirs)


# ---------------------------------------------------------------------------
# Sélection élite
# ---------------------------------------------------------------------------

def select_elite_candidates(
    candidates: List[ControlCandidate],
    max_count: int = 300,
    *,
    min_separation_m: float = 25.0,
) -> List[ControlCandidate]:
    """
    Sélectionne les meilleurs candidats avec bonne distribution spatiale.

    Algorithme glouton :
      1. Trier par score élite = 0.55 × composite_score + 0.45 × isolation_score.
      2. Accepter un candidat seulement s'il est à ≥ min_separation_m de tous
         les candidats déjà sélectionnés.

    Cette réduction évite les clusters denses qui gonfleraient la combinatoire
    sans apporter de diversité (ex: 50 blocs dans 50 m²).

    Args:
        candidates:        Liste de ControlCandidate (de préférence enrichis).
        max_count:         Nombre maximum de candidats à retenir.
        min_separation_m:  Distance minimale entre deux sélectionnés (m).

    Returns:
        Sous-liste triée par score élite décroissant.
    """
    if not candidates:
        return []

    if len(candidates) <= max_count:
        return sorted(candidates, key=_elite_score, reverse=True)

    sorted_cands = sorted(candidates, key=_elite_score, reverse=True)

    if _SCIPY_OK:
        return _greedy_kdtree(sorted_cands, max_count, min_separation_m)
    return _greedy_naive(sorted_cands, max_count, min_separation_m)


def _elite_score(c: ControlCandidate) -> float:
    return c.composite_score * 0.55 + c.isolation_score * 0.45


def _greedy_kdtree(
    sorted_cands: List[ControlCandidate],
    max_count: int,
    min_sep: float,
) -> List[ControlCandidate]:
    """Sélection O(N log N) avec KDTree scipy."""
    selected: List[ControlCandidate] = []
    coords: List[tuple[float, float]] = []

    for cand in sorted_cands:
        if len(selected) >= max_count:
            break
        if not coords:
            selected.append(cand)
            coords.append((cand.x, cand.y))
            continue
        dist, _ = KDTree(coords).query((cand.x, cand.y))
        if dist >= min_sep:
            selected.append(cand)
            coords.append((cand.x, cand.y))

    return selected


def _greedy_naive(
    sorted_cands: List[ControlCandidate],
    max_count: int,
    min_sep: float,
) -> List[ControlCandidate]:
    """Fallback O(N²) sans scipy."""
    selected: List[ControlCandidate] = []
    for cand in sorted_cands:
        if len(selected) >= max_count:
            break
        if not any(math.hypot(cand.x - s.x, cand.y - s.y) < min_sep for s in selected):
            selected.append(cand)
    return selected
