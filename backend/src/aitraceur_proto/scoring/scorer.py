"""
Couche 5 — Fonction de scoring explicable.

    breakdown = score_course(course, profile=my_profile)       # API héritée
    breakdown = score_course(course, my_weights)               # API nouvelle

    # Scoring par jambe :
    leg_score = compute_leg_score(leg, base_speed_mps=3.5, weights=w)

    # Scoring séquentiel sur les jambes :
    flow    = compute_flow_score(legs)
    variety = compute_variety_score(legs)
    effort  = compute_global_effort(legs, target_effort=1.2)

    # Scoring métier avancé (anti-patterns) :
    align   = compute_alignment_score(course)   # pénalise les A→B→C alignés
    cluster = compute_clustering_score(course)  # pénalise les amas
    divers  = compute_diversity_score(course)   # entropie Shannon des symboles

Formule active :
  - Si w_legs + w_flow + w_variety + w_effort + w_alignment + w_clustering + w_diversity > 0 :
        final = somme pondérée des 7 composantes (clampée [0,1])
  - Sinon (défaut) : ancienne formule dimensionnelle (distance, climb, technical…)
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import List, Optional

from ..model.course import Course, CourseMetrics
from ..model.leg import Leg
from ..profiles import CourseProfile, ProfileTargets, ScoringWeights
from .breakdown import CourseScoreBreakdown, _letter_grade
from .flow import compute_rhythm_score, compute_variation_score, compute_flow_score

# Numpy/scipy — optionnels, fallback pur-Python si absents
try:
    import numpy as np
    _NUMPY_OK = True
except ImportError:  # pragma: no cover
    _NUMPY_OK = False

try:
    from scipy.spatial import cKDTree
    _SCIPY_OK = True
except ImportError:  # pragma: no cover
    _SCIPY_OK = False


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    """Borne v dans [lo, hi]."""
    return max(lo, min(hi, v))


def _dist_of(leg: object) -> float:
    """Extrait la distance d'un objet Leg ou LegInfo (duck-typing)."""
    d = getattr(leg, "distance_2d", None)
    if d is None:
        d = getattr(leg, "straight_dist_m", 0.0)
    return float(d) if d is not None else 0.0


def _km_effort_of(leg: object) -> float:
    """
    Extrait le km-effort d'un objet Leg ou LegInfo.

    Pour un Leg : km_effort = distance/1000 + climb/100.
    Pour un LegInfo (pas de dénivelé) : approximation = distance/1000.
    """
    ke = getattr(leg, "km_effort", None)
    if ke is not None:
        return float(ke)
    return _dist_of(leg) / 1000.0


# ---------------------------------------------------------------------------
# Score d'une jambe individuelle (objet Leg complet)
# ---------------------------------------------------------------------------

def compute_leg_score(
    leg: Leg,
    base_speed_mps: float,
    weights: ScoringWeights,
) -> float:
    """
    Score [0–1] d'une jambe individuelle (Leg avec champs 3D).

    Trois composantes pondérées par weights.effort_weight / choice_weight / tech_weight :

    1. **Effort physique** (relief) :
       effort_score = clamp(km_effort/flat_km - 1, 0, 2) / 2
       → 0 = terrain plat, 1 = effort très significatif

    2. **Complexité d'itinéraire** :
       choice_score = clamp(travel_time_s / (dist/speed) - 1, 0, 3) / 3
       → 0 = ligne droite optimale, 1 = détour majeur

    3. **Difficulté technique** :
       tech_score = clamp(technical_difficulty, 0, 1)

    Args:
        leg:            Objet Leg avec km_effort, travel_time_seconds, technical_difficulty.
        base_speed_mps: Vitesse de référence (m/s) sur terrain plat.
        weights:        ScoringWeights avec effort_weight, choice_weight, tech_weight.

    Returns:
        Score agrégé [0.0, 1.0].
    """
    flat_dist_km = max(1e-6, leg.distance_2d / 1000.0)
    effort_score = _clamp(leg.km_effort / flat_dist_km - 1.0, 0.0, 2.0) / 2.0

    theoretical_time = leg.distance_2d / max(1e-6, base_speed_mps)
    choice_score = _clamp(
        leg.travel_time_seconds / max(1e-6, theoretical_time) - 1.0,
        0.0, 3.0,
    ) / 3.0

    tech_score = _clamp(leg.technical_difficulty, 0.0, 1.0)

    score = (
        weights.effort_weight * effort_score
        + weights.choice_weight * choice_score
        + weights.tech_weight  * tech_score
    )
    return _clamp(score, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Flow score (fluidité des changements de cap)
# ---------------------------------------------------------------------------

def compute_flow_score(legs: List[object]) -> float:
    """
    Score de fluidité [0–1] basé sur les variations angulaires successives.

    Méthode :
      - Extrait les bearings (degrés → radians) de chaque jambe.
      - Calcule les deltas successifs entre jambes consécutives.
      - Gaussienne centrée sur π/2 (~90°) : exp(-((delta-π/2)²) / σ), σ=0.5.
      - Retourne la moyenne des scores individuels.

    Args:
        legs: Objets avec attribut ``bearing_deg`` (Leg ou LegInfo).

    Returns:
        Score [0.0, 1.0]. Retourne 0.5 (neutre) si moins de 2 jambes.
    """
    if len(legs) < 2:
        return 0.5

    optimal = math.pi / 2.0  # 90°
    sigma = 0.5               # largeur de la gaussienne (rad²)
    bearings = [math.radians(getattr(lg, "bearing_deg", 0.0)) for lg in legs]

    scores: List[float] = []
    for i in range(len(bearings) - 1):
        delta = abs(bearings[i + 1] - bearings[i])
        delta = min(delta, 2.0 * math.pi - delta)  # ramener dans [0, π]
        scores.append(math.exp(-((delta - optimal) ** 2) / sigma))

    return sum(scores) / max(1, len(scores))


# ---------------------------------------------------------------------------
# Variety score (diversité des longueurs de jambe)
# ---------------------------------------------------------------------------

def compute_variety_score(legs: List[object]) -> float:
    """
    Score de variété [0–1] basé sur le coefficient de variation des distances.

    Méthode :
      cv = std / (mean + 1e-6)
      variety_score = 1 - exp(-cv)

    Args:
        legs: Objets avec attribut ``distance_2d`` ou ``straight_dist_m``.

    Returns:
        Score [0.0, 1.0). Retourne 0.0 si la liste est vide.
    """
    if not legs:
        return 0.0

    distances = [_dist_of(lg) for lg in legs]
    n = len(distances)
    mean = sum(distances) / n
    variance = sum((d - mean) ** 2 for d in distances) / n
    std = math.sqrt(max(0.0, variance))

    cv = std / max(1e-6, mean)
    return _clamp(1.0 - math.exp(-cv), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Global effort score (cohérence physique globale)
# ---------------------------------------------------------------------------

def compute_global_effort(legs: List[object], target_effort: float) -> float:
    """
    Score de cohérence de l'effort physique global [0–1].

    Méthode :
      effort_ratio = mean(km_effort / flat_distance_km)
      score = exp(-|effort_ratio - target_effort|)

    Args:
        legs:          Objets avec ``km_effort`` et ``distance_2d``.
        target_effort: Ratio km-effort cible (ex. 1.2 = +20% de dénivelé relatif).

    Returns:
        Score [0.0, 1.0]. 1.0 = effort parfaitement aligné sur la cible.
    """
    if not legs:
        return 0.0

    ratios: List[float] = []
    for lg in legs:
        flat_km = max(1e-6, _dist_of(lg) / 1000.0)
        ratios.append(_km_effort_of(lg) / flat_km)

    mean_ratio = sum(ratios) / len(ratios)
    return math.exp(-abs(mean_ratio - target_effort))


# ---------------------------------------------------------------------------
# BLOC 2 — Alignment score (pénalise les postes alignés A→B→C)
# ---------------------------------------------------------------------------

def compute_alignment_score(course: Course) -> float:
    """
    Score anti-alignement [0–1].

    Pénalise les triplets consécutifs (A, B, C) où A→B→C forment une ligne
    droite (ce qui est monotone et peu technique en CO).

    Méthode numpy vectorisée O(n) :
      1. Construit les vecteurs AB et BC pour chaque triplet successif.
      2. Normalise chaque vecteur (ε = 1e-6 pour la stabilité).
      3. Calcule les produits scalaires : dot = AB_n · BC_n ∈ [-1, 1].
      4. score = 1 - mean(|dot|)
         → 1.0 = aucun alignement (angles variés)
         → 0.0 = tous les postes parfaitement alignés

    Fallback pur-Python si numpy absent.

    Args:
        course: Parcours avec ``course.controls`` (List[ControlCandidate]).

    Returns:
        Score [0.0, 1.0]. Retourne 1.0 (neutre) si moins de 3 postes.
    """
    controls = course.controls
    if len(controls) < 3:
        return 1.0

    if _NUMPY_OK:
        coords = np.array([[c.x, c.y] for c in controls], dtype=np.float64)
        # Vecteurs AB (de chaque point vers le suivant) et BC
        ab = coords[1:-1] - coords[:-2]   # shape (n-2, 2)
        bc = coords[2:]   - coords[1:-1]  # shape (n-2, 2)

        ab_norms = np.linalg.norm(ab, axis=1, keepdims=True)
        bc_norms = np.linalg.norm(bc, axis=1, keepdims=True)

        ab_n = ab / np.maximum(ab_norms, 1e-6)
        bc_n = bc / np.maximum(bc_norms, 1e-6)

        dots = np.sum(ab_n * bc_n, axis=1)  # produit scalaire par triplet
        score = 1.0 - float(np.mean(np.abs(dots)))
    else:
        # Fallback pur-Python (O(n), pas de numpy)
        dot_abs_sum = 0.0
        n_triplets = len(controls) - 2
        for i in range(n_triplets):
            ax, ay = controls[i].x,     controls[i].y
            bx, by = controls[i+1].x,   controls[i+1].y
            cx, cy = controls[i+2].x,   controls[i+2].y
            abx, aby = bx - ax, by - ay
            bcx, bcy = cx - bx, cy - by
            ab_norm = math.hypot(abx, aby)
            bc_norm = math.hypot(bcx, bcy)
            if ab_norm < 1e-6 or bc_norm < 1e-6:
                continue
            dot = (abx * bcx + aby * bcy) / (ab_norm * bc_norm)
            dot_abs_sum += abs(dot)
        score = 1.0 - dot_abs_sum / max(1, n_triplets)

    return _clamp(score, 0.0, 1.0)


# ---------------------------------------------------------------------------
# BLOC 2 — Clustering score (pénalise les amas de postes)
# ---------------------------------------------------------------------------

def compute_clustering_score(course: Course) -> float:
    """
    Score anti-clustering [0–1].

    Mesure si les postes sont bien distribués dans l'espace.
    Un parcours avec des postes en amas (quelques-uns très proches, d'autres
    isolés) obtient un score élevé (variation des distances NN élevée),
    signalant un problème de répartition.

    Méthode :
      1. Calcule la distance au plus proche voisin (NN) pour chaque poste
         via KDTree → O(n log n).
      2. cv = std(NN_dists) / (mean(NN_dists) + ε)
      3. clustering_score = 1 - exp(-cv)
         → élevé si les NN distances sont très hétérogènes (amas + isolation)
         → faible si tous les postes sont uniformément espacés

    Fallback O(n²) pur-Python si scipy absent.

    Args:
        course: Parcours avec ``course.controls`` (List[ControlCandidate]).

    Returns:
        Score [0.0, 1.0]. Retourne 1.0 (neutre) si moins de 3 postes.
    """
    controls = course.controls
    if len(controls) < 3:
        return 1.0

    if _NUMPY_OK and _SCIPY_OK:
        coords = np.array([[c.x, c.y] for c in controls], dtype=np.float64)
        tree = cKDTree(coords)
        # k=2 : premier résultat = soi-même (dist=0), second = vrai NN
        nn_dists_raw, _ = tree.query(coords, k=2, workers=1)
        nn_dists = nn_dists_raw[:, 1].astype(np.float64)

        mean_d = float(np.mean(nn_dists))
        std_d  = float(np.std(nn_dists))
    elif _NUMPY_OK:
        # KDTree absent : distance matrix numpy (O(n²) mémoire, sans boucle Python)
        coords = np.array([[c.x, c.y] for c in controls], dtype=np.float64)
        diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]   # (n, n, 2)
        dist_mat = np.linalg.norm(diff, axis=2)                       # (n, n)
        np.fill_diagonal(dist_mat, np.inf)
        nn_dists = dist_mat.min(axis=1)

        mean_d = float(np.mean(nn_dists))
        std_d  = float(np.std(nn_dists))
    else:
        # Fallback pur-Python O(n²) — acceptable pour n < 30
        nn_dists_py: List[float] = []
        for i, ci in enumerate(controls):
            min_d = math.inf
            for j, cj in enumerate(controls):
                if i == j:
                    continue
                d = math.hypot(ci.x - cj.x, ci.y - cj.y)
                if d < min_d:
                    min_d = d
            nn_dists_py.append(min_d)
        mean_d = sum(nn_dists_py) / len(nn_dists_py)
        variance = sum((d - mean_d) ** 2 for d in nn_dists_py) / len(nn_dists_py)
        std_d = math.sqrt(max(0.0, variance))

    cv = std_d / max(1e-6, mean_d)
    return _clamp(1.0 - math.exp(-cv), 0.0, 1.0)


# ---------------------------------------------------------------------------
# BLOC 2 — Diversity score (entropie Shannon des symboles OCAD)
# ---------------------------------------------------------------------------

def compute_diversity_score(course: Course) -> float:
    """
    Score de diversité [0–1] — entropie de Shannon normalisée des symboles.

    Mesure la variété des types de postes (source_sym OCAD ou detail_type).
    Un parcours avec tous les postes sur le même symbole obtient 0.0.
    Un parcours avec une distribution équirépartie sur n symboles obtient ≈ 1.0.

    Méthode :
      - Collecte les ``source_sym`` non-None (fallback sur ``detail_type``).
      - Calcule la distribution de fréquences.
      - H = -sum(p * log(p))
      - H_norm = H / log(n_unique)

    Fallback :
      - Si < 2 symboles uniques → retourne 0.0.
      - Si ``source_sym`` absent sur tous → utilise ``detail_type``.

    Args:
        course: Parcours avec ``course.controls`` (List[ControlCandidate]).

    Returns:
        Score [0.0, 1.0]. Retourne 0.0 si moins de 2 symboles distincts.
    """
    controls = course.controls
    if len(controls) < 3:
        return 1.0  # neutre — pas assez de données

    # Collecte des identifiants symboliques
    # Priorité : source_sym (code OCAD numérique), fallback : detail_type (string)
    symbols: List[object] = []
    for c in controls:
        sym = getattr(c, "source_sym", None)
        if sym is not None:
            symbols.append(sym)
        else:
            dt = getattr(c, "detail_type", None)
            if dt is not None:
                symbols.append(dt)

    if not symbols:
        return 0.0

    counts = Counter(symbols)
    n_unique = len(counts)
    if n_unique < 2:
        return 0.0

    n_total = len(symbols)
    # Entropie de Shannon
    h = 0.0
    for freq in counts.values():
        p = freq / n_total
        h -= p * math.log(p + 1e-12)

    # Normalisation par l'entropie maximale (distribution uniforme)
    h_norm = h / math.log(n_unique)
    return _clamp(h_norm, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Fonctions de scoring par composante (formule dimensionnelle héritée)
# ---------------------------------------------------------------------------

def _score_distance(dist_m: float, targets: ProfileTargets) -> float:
    """Score de distance [0–1] — gaussienne centrée sur la cible."""
    t = targets.distance_m_target
    if t <= 0:
        return 1.0
    if dist_m < targets.distance_m_min:
        return max(0.0, dist_m / targets.distance_m_min)
    if dist_m > targets.distance_m_max:
        return max(0.0, targets.distance_m_max / dist_m)
    sigma = (targets.distance_m_max - targets.distance_m_min) / 4.0
    return math.exp(-0.5 * ((dist_m - t) / sigma) ** 2)


def _score_climb(climb_m: Optional[float], targets: ProfileTargets) -> float:
    """Score de dénivelé [0–1]. Score neutre 0.6 si info absente."""
    if climb_m is None:
        return 0.6
    t = targets.climb_m_target
    if t <= 0:
        return 1.0 if climb_m <= targets.climb_m_max else 0.5
    if climb_m < targets.climb_m_min:
        return max(0.0, (climb_m / targets.climb_m_min) ** 0.5)
    if climb_m > targets.climb_m_max:
        return max(0.0, targets.climb_m_max / climb_m)
    sigma = (targets.climb_m_max - targets.climb_m_min) / 4.0
    return math.exp(-0.5 * ((climb_m - t) / sigma) ** 2)


def _score_technical(mean_td: float, max_td: int, profile: CourseProfile) -> float:
    """Score de niveau technique [0–1]."""
    target_td = float(profile.technical_level.value)
    if target_td <= 0:
        return 0.5
    score_mean = math.exp(-0.5 * ((mean_td - target_td) / 1.0) ** 2)
    penalty_max = math.exp(-max(0.0, max_td - (target_td + 1)) * 0.8)
    return score_mean * penalty_max


def _score_variety_legacy(metrics: CourseMetrics, profile: CourseProfile) -> float:
    """Score de variété [0–1] — version dimensionnelle héritée."""
    type_div = metrics.type_diversity
    if metrics.mean_leg_m > 0 and metrics.std_leg_m >= 0:
        cv = metrics.std_leg_m / metrics.mean_leg_m
        score_len_var = math.exp(-2.0 * (cv - 0.4) ** 2)
    else:
        score_len_var = 0.5
    if metrics.bearing_changes:
        mean_bc = statistics.mean(metrics.bearing_changes)
        score_dir = math.exp(-0.5 * ((mean_bc - 80.0) / 30.0) ** 2)
    else:
        score_dir = 0.5
    return 0.50 * type_div + 0.25 * score_len_var + 0.25 * score_dir


def _score_structure(metrics: CourseMetrics, profile: CourseProfile) -> float:
    """Score de structure du parcours [0–1]."""
    targets = profile.targets
    n_legs = len(metrics.legs)
    if n_legs > 0:
        score_no_dogleg = max(0.0, 1.0 - metrics.dog_legs / n_legs * 2.5)
    else:
        score_no_dogleg = 1.0
    if metrics.legs:
        leg_dists = [lg.straight_dist_m for lg in metrics.legs]
        out_of_range = sum(
            1 for d in leg_dists if d < targets.leg_m_min or d > targets.leg_m_max
        )
        score_leg_range = max(0.0, 1.0 - out_of_range / len(leg_dists))
    else:
        score_leg_range = 0.5
    if n_legs > 0:
        score_feasible = max(0.0, 1.0 - metrics.n_infeasible_legs / n_legs)
    else:
        score_feasible = 1.0
    return 0.40 * score_no_dogleg + 0.30 * score_leg_range + 0.30 * score_feasible


def _score_spatial(metrics: CourseMetrics) -> float:
    """Score de répartition spatiale [0–1]."""
    target_coverage = 0.5
    cov = metrics.coverage_ratio
    if cov >= target_coverage:
        return min(1.0, 0.7 + 0.3 * (cov - target_coverage) / (1.0 - target_coverage))
    return max(0.0, cov / target_coverage)


def _score_safety(metrics: CourseMetrics, profile: CourseProfile) -> float:
    """Score de sécurité / conformité IOF [0–1]."""
    targets = profile.targets
    n_legs = len(metrics.legs)
    infeasible_penalty = max(
        0.0, 1.0 - metrics.n_infeasible_legs / max(1, n_legs) * 5.0
    )
    n = metrics.n_controls
    if n < targets.controls_min:
        n_score = max(0.0, n / targets.controls_min)
    elif n > targets.controls_max:
        n_score = max(0.0, targets.controls_max / n)
    else:
        n_score = 1.0
    dog_penalty = max(0.0, 1.0 - metrics.dog_legs / max(1, n_legs) * 3.0)
    return 0.40 * infeasible_penalty + 0.30 * n_score + 0.30 * dog_penalty


def _score_legacy_flow(metrics: CourseMetrics) -> float:
    """Score de flow [0–1] — agrège rythme, variation et fluidité (hérité)."""
    return (
        metrics.rhythm_score    * 0.40
        + metrics.variation_score * 0.30
        + metrics.flow_score      * 0.30
    )


# ---------------------------------------------------------------------------
# Helper — métriques enrichies depuis LegInfo
# ---------------------------------------------------------------------------

def _compute_enriched_metrics(
    metrics: CourseMetrics,
) -> tuple[float, float, float]:
    """
    Retourne (mean_km_effort, mean_route_choice_complexity, total_climb)
    depuis les LegInfo du parcours (approximation sans dénivelé par jambe).
    """
    total_climb_val = metrics.total_climb_m or 0.0
    if metrics.legs:
        n = len(metrics.legs)
        total_km_effort = metrics.total_distance_m / 1000.0 + total_climb_val / 100.0
        mean_km_effort = total_km_effort / n
        mean_rcc = sum(lg.route_choice_complexity for lg in metrics.legs) / n
    else:
        mean_km_effort = 0.0
        mean_rcc = 0.0
    return mean_km_effort, mean_rcc, total_climb_val


# ---------------------------------------------------------------------------
# Fonction principale — formule hybride (héritée ou nouvelle selon weights)
# ---------------------------------------------------------------------------

def score_course(
    course: Course,
    weights: Optional[ScoringWeights] = None,
    *,
    cost_matrix: Optional[object] = None,
    profile: Optional[CourseProfile] = None,
) -> CourseScoreBreakdown:
    """
    Calcule le score d'un parcours et retourne un CourseScoreBreakdown détaillé.

    Deux formules coexistent selon les poids configurés dans ``weights`` :

    **Formule nouvelle** (activée si la somme des w_* > 0) :
        final = w_legs·legs + w_flow·flow + w_variety·variety
              + w_effort·effort + w_alignment·alignment
              + w_clustering·clustering + w_diversity·diversity
        → Favorise fluidité, variété, cohérence physique et distribution.

    **Formule héritée** (défaut si tous les w_* sont nuls) :
        global_score = somme pondérée distance, dénivelé, technique, variété…
        → Comportement identique aux versions précédentes.

    Les deux formules populen TOUJOURS l'ensemble des champs du breakdown.

    Args:
        course:      Parcours à évaluer.
        weights:     ScoringWeights à utiliser. Si None : course.profile.weights.
        cost_matrix: Matrice de coûts (optionnel, améliore la précision).
                     Paramètre keyword-only — rétrocompatibilité.
        profile:     Profil de course. Si None : course.profile.
                     Paramètre keyword-only — rétrocompatibilité.

    Returns:
        CourseScoreBreakdown avec global_score [0–100] et tous les sous-scores.
    """
    _profile = profile or course.profile
    _weights = weights if isinstance(weights, ScoringWeights) else _profile.weights

    # Calcul (ou récupération) des métriques
    c = course
    if c.metrics is None:
        c = c.compute_metrics(cost_matrix)
    metrics = c.metrics

    targets = _profile.targets
    legs = metrics.legs  # LegInfo objects

    # ------------------------------------------------------------------
    # Sous-scores communs (toujours calculés)
    # ------------------------------------------------------------------
    dist_s      = _score_distance(metrics.total_distance_m, targets)
    climb_s     = _score_climb(metrics.total_climb_m, targets)
    tech_s      = _score_technical(
        metrics.mean_technical_level, metrics.max_technical_level, _profile,
    )
    var_leg_s   = _score_variety_legacy(metrics, _profile)
    struct_s    = _score_structure(metrics, _profile)
    spatial_s   = _score_spatial(metrics)
    safety_s    = _score_safety(metrics, _profile)
    cq_s        = metrics.mean_controls_quality
    lq_s        = metrics.mean_legs_quality
    legacy_flow = _score_legacy_flow(metrics)

    # ------------------------------------------------------------------
    # Sous-scores flow/variety/effort (sur jambes)
    # ------------------------------------------------------------------
    flow_s          = compute_flow_score(legs)
    variety_s       = compute_variety_score(legs)
    global_effort_s = compute_global_effort(legs, _weights.target_effort)
    mean_leg_s      = lq_s  # proxy depuis legs_quality (LegInfo sans Leg complet)

    # ------------------------------------------------------------------
    # Sous-scores métier avancés (anti-patterns, sur course.controls)
    # ------------------------------------------------------------------
    alignment_s  = compute_alignment_score(course)
    clustering_s = compute_clustering_score(course)
    diversity_s  = compute_diversity_score(course)

    # ------------------------------------------------------------------
    # Score global — sélection de formule
    # ------------------------------------------------------------------
    new_weight_sum = (
        _weights.w_legs      + _weights.w_flow     + _weights.w_variety
        + _weights.w_effort  + _weights.w_alignment
        + _weights.w_clustering + _weights.w_diversity
    )

    if new_weight_sum > 1e-6:
        # Nouvelle formule étendue — 7 composantes
        raw = (
            _weights.w_legs       * mean_leg_s
            + _weights.w_flow       * flow_s
            + _weights.w_variety    * variety_s
            + _weights.w_effort     * global_effort_s
            + _weights.w_alignment  * alignment_s
            + _weights.w_clustering * clustering_s
            + _weights.w_diversity  * diversity_s
        )
        # Normalisation si la somme des poids ≠ 1 (robustesse)
        final_01 = _clamp(raw / max(1e-6, new_weight_sum), 0.0, 1.0)
    else:
        # Formule héritée dimensionnelle (rétrocompatible)
        final_01 = (
            _weights.distance           * dist_s
            + _weights.climb            * climb_s
            + _weights.technical        * tech_s
            + _weights.variety          * var_leg_s
            + _weights.structure        * struct_s
            + _weights.spatial          * spatial_s
            + _weights.safety           * safety_s
            + _weights.controls_quality * cq_s
            + _weights.legs_quality     * lq_s
            + _weights.flow             * legacy_flow
        )

    global_score = round(_clamp(final_01, 0.0, 1.0) * 100.0, 2)

    # ------------------------------------------------------------------
    # Métriques enrichies
    # ------------------------------------------------------------------
    mean_km_effort, mean_rcc, total_climb_val = _compute_enriched_metrics(metrics)

    # ------------------------------------------------------------------
    # Assemblage du breakdown
    # ------------------------------------------------------------------
    return CourseScoreBreakdown(
        global_score=global_score,
        grade=_letter_grade(global_score),
        # Sous-scores dimensionnels
        distance_score=round(dist_s, 4),
        climb_score=round(climb_s, 4),
        technical_score=round(tech_s, 4),
        variety_score=round(variety_s, 4),
        structure_score=round(struct_s, 4),
        spatial_score=round(spatial_s, 4),
        safety_score=round(safety_s, 4),
        # Sous-scores métier
        controls_quality_score=round(cq_s, 4),
        legs_quality_score=round(mean_leg_s, 4),
        flow_score=round(flow_s, 4),
        global_effort_score=round(global_effort_s, 4),
        # Sous-scores anti-patterns
        alignment_score=round(alignment_s, 4),
        clustering_score=round(clustering_s, 4),
        diversity_score=round(diversity_s, 4),
        # Valeurs brutes
        distance_m=metrics.total_distance_m,
        target_dist_m=targets.distance_m_target,
        climb_m=metrics.total_climb_m,
        target_climb_m=targets.climb_m_target,
        dog_legs=metrics.dog_legs,
        n_infeasible=metrics.n_infeasible_legs,
        n_controls=metrics.n_controls,
        type_diversity=metrics.type_diversity,
        mean_td=metrics.mean_technical_level,
        # Métriques enrichies 3D
        mean_km_effort=round(mean_km_effort, 4),
        mean_route_choice_complexity=round(mean_rcc, 4),
        total_climb=round(total_climb_val, 2),
        # Détails debug
        details={
            "formula": "new" if new_weight_sum > 1e-6 else "legacy",
            "weights": {
                "w_legs":       _weights.w_legs,
                "w_flow":       _weights.w_flow,
                "w_variety":    _weights.w_variety,
                "w_effort":     _weights.w_effort,
                "w_alignment":  _weights.w_alignment,
                "w_clustering": _weights.w_clustering,
                "w_diversity":  _weights.w_diversity,
                "target_effort": _weights.target_effort,
            } if new_weight_sum > 1e-6 else {
                "distance":         _weights.distance,
                "climb":            _weights.climb,
                "technical":        _weights.technical,
                "variety":          _weights.variety,
                "structure":        _weights.structure,
                "spatial":          _weights.spatial,
                "safety":           _weights.safety,
                "controls_quality": _weights.controls_quality,
                "legs_quality":     _weights.legs_quality,
                "flow":             _weights.flow,
            },
            "n_legs":             len(legs),
            "coverage_ratio":     round(metrics.coverage_ratio, 3),
            "flow_bearing_score": round(flow_s, 3),
            "variety_cv_score":   round(variety_s, 3),
        },
    )
