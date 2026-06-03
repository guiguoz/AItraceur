"""CourseProfile — personnalité d'un parcours CO."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class ProfileEpisode:
    start_leg: int
    end_leg: int
    dominant_mode: str              # "navigation"|"orienteering"|"speed"
    centroid: Tuple[float, float]   # (lng, lat) barycentre des milieux de jambes


@dataclass
class CourseProfile:
    # Statistiques globales
    technical_balance: float        # std des fractions N/O/S — 0=équilibré, 0.47=mono
    route_choice_density: float     # fraction jambes avec Jaccard > 0.30
    alternation: float              # % alternance court/long [0-100]
    climb_distribution: float       # régularité D+ par jambe [0=irrégulier, 1=régulier]

    # Couverture géographique
    map_coverage: float             # aire convex hull / aire bbox [0-1]
    zone_balance: float             # entropie Shannon grille 4×4 [0=concentré, 1=uniforme]

    # Épisodes & séquence
    episodes: List[ProfileEpisode]
    zone_sequence: List[str]        # par jambe : "navigation"|"orienteering"|"speed"

    # Transitions
    profile_segments: List[Tuple[str, int]]  # run-length : [("speed",4), ("nav",3)]
    transition_count: int
    transition_strength: float      # amplitude moyenne des transitions [0-1]

    # Dramaturgie
    difficulty_curve: List[float]   # [0-1] par jambe
    narrative_shape: str            # "progressive"|"stable"|"climax_final"|
                                    # "climax_middle"|"sawtooth"|"random"
    leg_intent_histogram: Dict[str, int]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _alternation_score(legs_m: np.ndarray) -> float:
    if len(legs_m) < 4:
        return 75.0
    mean = float(legs_m.mean())
    if mean == 0:
        return 75.0
    labels = []
    for d in legs_m:
        if d < 0.80 * mean:
            labels.append('C')
        elif d > 1.20 * mean:
            labels.append('L')
        else:
            labels.append('M')
    relevant = [l for l in labels if l in ('C', 'L')]
    if len(relevant) < 2:
        return 75.0
    alternations = sum(1 for a, b in zip(relevant, relevant[1:]) if a != b)
    return 100.0 * alternations / (len(relevant) - 1)


def _zone_balance(controls: list, bbox: tuple, n: int = 4) -> float:
    """Entropie de Shannon normalisée de la distribution des postes dans une grille n×n."""
    if len(controls) < 2:
        return 0.0
    min_lng, min_lat, max_lng, max_lat = bbox
    w = max_lng - min_lng
    h = max_lat - min_lat
    if w <= 0 or h <= 0:
        return 0.0
    counts = np.zeros(n * n, dtype=float)
    for c in controls:
        ci = min(n - 1, int((c[0] - min_lng) / w * n))
        cj = min(n - 1, int((c[1] - min_lat) / h * n))
        counts[cj * n + ci] += 1
    total = counts.sum()
    if total == 0:
        return 0.0
    probs = counts / total
    nonzero = probs[probs > 0]
    entropy = max(0.0, -float(np.sum(nonzero * np.log(nonzero))))
    h_max = math.log(n * n)
    return float(min(1.0, entropy / h_max))


def _map_coverage(controls: list, bbox: tuple) -> float:
    """Aire convex hull controls / aire bbox (projections approximées en mètres)."""
    if len(controls) < 3:
        return 0.0
    min_lng, min_lat, max_lng, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2.0
    lng_scale = math.cos(math.radians(mid_lat)) * 111_320.0
    lat_scale = 111_320.0

    xs = np.array([c[0] * lng_scale for c in controls])
    ys = np.array([c[1] * lat_scale for c in controls])

    bbox_w = (max_lng - min_lng) * lng_scale
    bbox_h = (max_lat - min_lat) * lat_scale
    bbox_area = bbox_w * bbox_h
    if bbox_area <= 0:
        return 0.0

    try:
        from scipy.spatial import ConvexHull
        hull_area = ConvexHull(np.column_stack([xs, ys])).volume  # volume = area in 2D
    except Exception:
        # Fallback shoelace sur les points bruts (borne inférieure)
        n = len(xs)
        hull_area = abs(
            sum(xs[i] * ys[(i + 1) % n] - xs[(i + 1) % n] * ys[i] for i in range(n))
        ) / 2.0

    return float(min(1.0, hull_area / bbox_area))


def _classify_zone_cnn(cnn_score: float) -> str:
    if cnn_score >= 0.60:
        return "speed"
    if cnn_score >= 0.40:
        return "orienteering"
    return "navigation"


def _classify_zone_cognitive(leg_profile: Any) -> str:
    """Classifie à partir d'un LegIntentInference (duck-typed pour éviter import circulaire)."""
    nav = getattr(leg_profile, 'crossing_density', 0) + getattr(leg_profile, 'contour_crossing_guidance', 0)
    phys = getattr(leg_profile, 'direct_run_index', 0) + getattr(leg_profile, 'parallel_affordance', 0)
    ori = getattr(leg_profile, 'exit_clarity', 0) + getattr(leg_profile, 'safety_recovery', 0)
    best = max(nav, phys, ori)
    if best == phys:
        return "speed"
    if best == nav:
        return "navigation"
    return "orienteering"


def _profile_segments(zone_sequence: List[str]) -> List[Tuple[str, int]]:
    if not zone_sequence:
        return []
    segs: List[Tuple[str, int]] = []
    current, count = zone_sequence[0], 1
    for z in zone_sequence[1:]:
        if z == current:
            count += 1
        else:
            segs.append((current, count))
            current, count = z, 1
    segs.append((current, count))
    return segs


_MODE_RANK = {"navigation": 0, "orienteering": 1, "speed": 2}


def _narrative_shape(dc: List[float]) -> str:
    if len(dc) < 3:
        return "stable"
    arr = np.array(dc, dtype=float)
    if arr.std() < 0.10:
        return "stable"
    n = len(arr)
    third = max(1, n // 3)
    diffs = np.diff(arr)
    # Progressive: > 70% des sauts positifs
    if (diffs > 0).sum() > 0.70 * len(diffs):
        return "progressive"
    # Sawtooth: > 50% de changements de signe
    sign_changes = int(np.sum(diffs[:-1] * diffs[1:] < 0))
    if sign_changes > 0.50 * (len(diffs) - 1):
        return "sawtooth"
    peak = int(np.argmax(arr))
    if peak >= 2 * third:
        return "climax_final"
    if peak >= third:
        return "climax_middle"
    return "random"


# ── API publique ───────────────────────────────────────────────────────────────

def compute_course_profile(
    controls: list,
    legs_m: np.ndarray,
    bbox: tuple,
    heatmap_cache=None,
    elevation_cache=None,
    route_analyzer=None,
    cognitive_profiles: Optional[list] = None,
) -> CourseProfile:
    """
    Calcule la personnalité d'un parcours.

    controls          : list[(lng, lat)], N postes
    legs_m            : ndarray shape (N-1,) distances en mètres
    bbox              : (min_lng, min_lat, max_lng, max_lat)
    cognitive_profiles: list[(LegIntentInference, n_contours, n_micro)] par jambe (optionnel)
    """
    n_legs = len(legs_m)

    # ── Zone sequence ──────────────────────────────────────────────────────────
    zone_sequence: List[str] = []
    for i in range(n_legs):
        p0, p1 = controls[i], controls[i + 1]
        mid_lng = (p0[0] + p1[0]) / 2.0
        mid_lat = (p0[1] + p1[1]) / 2.0
        if cognitive_profiles and i < len(cognitive_profiles):
            leg_inf = cognitive_profiles[i][0]
            zone_sequence.append(_classify_zone_cognitive(leg_inf))
        elif heatmap_cache is not None:
            zone_sequence.append(_classify_zone_cnn(heatmap_cache.query(mid_lng, mid_lat)))
        else:
            zone_sequence.append("orienteering")

    # ── Segments & transitions ─────────────────────────────────────────────────
    segs = _profile_segments(zone_sequence)
    transition_count = max(0, len(segs) - 1)
    if transition_count > 0:
        strengths = [
            abs(_MODE_RANK.get(m1, 1) - _MODE_RANK.get(m2, 1)) / 2.0
            for (m1, _), (m2, _) in zip(segs, segs[1:])
        ]
        transition_strength = float(np.mean(strengths))
    else:
        transition_strength = 0.0

    # ── Épisodes ───────────────────────────────────────────────────────────────
    episodes: List[ProfileEpisode] = []
    leg_idx = 0
    for mode, count in segs:
        start_leg = leg_idx
        end_leg = leg_idx + count - 1
        mid_lngs = [(controls[j][0] + controls[j + 1][0]) / 2.0 for j in range(start_leg, end_leg + 1)]
        mid_lats = [(controls[j][1] + controls[j + 1][1]) / 2.0 for j in range(start_leg, end_leg + 1)]
        episodes.append(ProfileEpisode(
            start_leg=start_leg,
            end_leg=end_leg,
            dominant_mode=mode,
            centroid=(float(np.mean(mid_lngs)), float(np.mean(mid_lats))),
        ))
        leg_idx += count

    # ── Technical balance ──────────────────────────────────────────────────────
    hist: Dict[str, int] = {"navigation": 0, "orienteering": 0, "speed": 0}
    for z in zone_sequence:
        hist[z] = hist.get(z, 0) + 1
    counts = np.array([hist[k] for k in ("navigation", "orienteering", "speed")], dtype=float)
    if counts.sum() > 0:
        counts /= counts.sum()
    technical_balance = float(counts.std())

    # ── Route choice density ──────────────────────────────────────────────────
    route_choice_count = 0
    if route_analyzer is not None:
        for i in range(n_legs):
            p0, p1 = controls[i], controls[i + 1]
            try:
                score = route_analyzer.route_diversity_score(p0[0], p0[1], p1[0], p1[1])
                if score > 0.30:
                    route_choice_count += 1
            except Exception:
                pass
    route_choice_density = route_choice_count / n_legs if n_legs > 0 else 0.0

    # ── Alternation ───────────────────────────────────────────────────────────
    alternation = _alternation_score(legs_m)

    # ── Climb distribution ────────────────────────────────────────────────────
    if elevation_cache is not None and n_legs > 0:
        dplus_legs = []
        for i in range(n_legs):
            try:
                dplus_legs.append(elevation_cache.estimate_dplus(controls[i:i + 2]))
            except Exception:
                dplus_legs.append(0.0)
        dp_arr = np.array(dplus_legs, dtype=float)
        mean_dp = dp_arr.mean()
        cv = dp_arr.std() / mean_dp if mean_dp > 0 else 0.0
        climb_distribution = float(max(0.0, 1.0 - min(cv, 1.0)))
    else:
        climb_distribution = 0.5

    # ── Difficulty curve ──────────────────────────────────────────────────────
    leg_norm = legs_m / legs_m.max() if legs_m.max() > 0 else np.zeros_like(legs_m)
    if heatmap_cache is not None:
        cnn_scores = np.array([
            heatmap_cache.query((controls[i][0] + controls[i + 1][0]) / 2.0,
                                (controls[i][1] + controls[i + 1][1]) / 2.0)
            for i in range(n_legs)
        ], dtype=float)
        difficulty = 0.5 * leg_norm + 0.5 * (1.0 - cnn_scores)
    else:
        difficulty = leg_norm
    difficulty_curve = [round(float(v), 3) for v in difficulty]

    return CourseProfile(
        technical_balance=round(technical_balance, 3),
        route_choice_density=round(route_choice_density, 3),
        alternation=round(alternation, 1),
        climb_distribution=round(climb_distribution, 3),
        map_coverage=round(_map_coverage(controls, bbox), 3),
        zone_balance=round(_zone_balance(controls, bbox), 3),
        episodes=episodes,
        zone_sequence=zone_sequence,
        profile_segments=segs,
        transition_count=transition_count,
        transition_strength=round(transition_strength, 3),
        difficulty_curve=difficulty_curve,
        narrative_shape=_narrative_shape(difficulty_curve),
        leg_intent_histogram=hist,
    )
