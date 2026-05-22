"""
Couche perceptuelle cognitive — abstraction intermédiaire entre features ISOM brutes et scoring GA.

Pipeline :
    segments OCAD (list[dict])
        → build_segment_index()
        → SegmentSpatialIndex (cKDTree sur midpoints)
            → query_radius()    # Terme P — rayon autour d'un poste
            → query_corridor()  # Termes N/O — corridor le long d'une jambe
        → LegCognitiveProfile  (par jambe)
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from scipy.spatial import cKDTree


_DEFAULT_PROFILE = {
    "mobility_weight": 0.3,
    "crossing_salience": 0.4,
    "misleading_potential": 0.3,
    "handrail_strength": 0.2,
}


@dataclass(slots=True)
class PerceptualFeature:
    """Segment OCAD enrichi — géométrie et profil sémantique pré-calculés."""

    p0: tuple                 # (lng, lat)
    p1: tuple                 # (lng, lat)
    isom_code: int
    midpoint: tuple           # ((lng0+lng1)/2, (lat0+lat1)/2)
    bearing_rad: float        # atan2(dlng, dlat)
    length_m: float           # longueur terrain en mètres
    mobility_weight: float
    crossing_salience: float
    misleading_potential: float
    handrail_strength: float


def _build_perceptual_feature(seg: dict, isom_sem: dict) -> PerceptualFeature:
    p0 = tuple(seg["p0"])
    p1 = tuple(seg["p1"])
    code = int(seg.get("isom_code", 0))
    profile = isom_sem.get(str(code), _DEFAULT_PROFILE)

    mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    bearing = math.atan2(p1[0] - p0[0], p1[1] - p0[1])

    # Approximation métrique locale (précision suffisante pour 0–5 km)
    cos_lat = math.cos(math.radians(mid[1]))
    dlat_m = (p1[1] - p0[1]) * 111000.0
    dlng_m = (p1[0] - p0[0]) * 111000.0 * cos_lat
    length_m = math.sqrt(dlat_m ** 2 + dlng_m ** 2)

    return PerceptualFeature(
        p0=p0, p1=p1, isom_code=code,
        midpoint=mid, bearing_rad=bearing, length_m=length_m,
        mobility_weight=float(profile.get("mobility_weight", _DEFAULT_PROFILE["mobility_weight"])),
        crossing_salience=float(profile.get("crossing_salience", _DEFAULT_PROFILE["crossing_salience"])),
        misleading_potential=float(profile.get("misleading_potential", _DEFAULT_PROFILE["misleading_potential"])),
        handrail_strength=float(profile.get("handrail_strength", _DEFAULT_PROFILE["handrail_strength"])),
    )


@dataclass
class LegCognitiveProfile:
    """Primitives cognitives d'une jambe CO — projection de la carte perceptuelle."""

    parallel_affordance: float = 0.0  # Terme N : chemin longeant [0,1]
    crossing_density: float = 0.0     # Terme O : saut de ligne [0,1]
    exit_clarity: float = 0.0         # Terme P : clarté sortie [0,1]

    @property
    def np_correlation_risk(self) -> float:
        """Signal de sur-score corrélé N↔P (layon parallèle fort)."""
        return self.parallel_affordance * self.exit_clarity


class SegmentSpatialIndex:
    """Index spatial O(log n + k) sur les midpoints des PerceptualFeature."""

    def __init__(self, features: List[PerceptualFeature], center_lat: float = 48.0):
        self._features = features
        self._cos_lat = math.cos(math.radians(center_lat))
        if features:
            mids = np.array([[f.midpoint[0], f.midpoint[1]] for f in features])
            self._tree: Optional[cKDTree] = cKDTree(mids)
        else:
            self._tree = None
        self.segment_count = len(features)

    def _deg_radius(self, radius_m: float) -> float:
        return radius_m / (111000.0 * self._cos_lat)

    def query_radius(
        self, lng: float, lat: float, radius_m: float
    ) -> List[PerceptualFeature]:
        """Features dont le midpoint est dans le rayon (Terme P — autour d'un poste)."""
        if self._tree is None:
            return []
        r = self._deg_radius(radius_m)
        idxs = self._tree.query_ball_point([lng, lat], r)
        return [self._features[i] for i in idxs]

    def query_corridor(
        self,
        lng0: float, lat0: float,
        lng1: float, lat1: float,
        half_width_m: float,
    ) -> List[PerceptualFeature]:
        """
        Pre-filtre les features dans le corridor de la jambe (Termes N, O).

        Utilise la sphère englobante : midpoint du segment ≤ leg_half + half_width
        depuis le midpoint de la jambe. Le filtrage géométrique exact (projection,
        angle, intersection) reste dans les méthodes _score_pp_ocad/_score_lc_ocad.
        """
        if self._tree is None:
            return []
        leg_mid_lng = (lng0 + lng1) / 2.0
        leg_mid_lat = (lat0 + lat1) / 2.0
        dlat_m = (lat1 - lat0) * 111000.0
        dlng_m = (lng1 - lng0) * 111000.0 * self._cos_lat
        leg_half_m = math.sqrt(dlat_m ** 2 + dlng_m ** 2) / 2.0
        search_r = self._deg_radius(leg_half_m + half_width_m)
        idxs = self._tree.query_ball_point([leg_mid_lng, leg_mid_lat], search_r)
        return [self._features[i] for i in idxs]


def build_segment_index(
    segments: List[dict],
    isom_sem: dict,
    center_lat: float = 48.0,
) -> SegmentSpatialIndex:
    """Construit un SegmentSpatialIndex depuis les segments bruts OCAD."""
    features = [_build_perceptual_feature(s, isom_sem) for s in segments]
    return SegmentSpatialIndex(features, center_lat=center_lat)
