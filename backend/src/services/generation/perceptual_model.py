"""
Couche perceptuelle cognitive — abstraction intermédiaire entre features ISOM brutes et scoring GA.

Pipeline :
    segments OCAD (list[dict])
        → build_segment_index()
        → SegmentSpatialIndex (cKDTree sur midpoints)
            → query_radius()    # Terme P — rayon autour d'un poste
            → query_corridor()  # Termes N/O — corridor le long d'une jambe
        → LegIntentInference   (par jambe — Niveau 1 + Niveau 2 affordances)
"""

import math
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar, List, Optional

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
    # Convention bearing : atan2(Δlng, Δlat) → Nord=0, Est=π/2 (compas, non math).
    # leg_bearing dans genetic_algo._build_leg_cognitive_profile utilise la même formule.
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
class LegIntentInference:
    """
    Niveau 1 + Niveau 2 — affordances terrain et evidence navigationnelle d'une jambe CO.

    Niveau 1 — Observables terrain (calcul dans genetic_algo._build_leg_cognitive_profile) :
      N/O/P inchangés + 3 nouveaux construits (contour_crossing_guidance, direct_run_index, safety_recovery).

    Niveau 2 — Evidence navigationnelle absolue (cached_property navigation_evidence) :
      Activations [0,1] sans normalisation. Les modes coexistent (HANDRAIL=0.7 + LINE_CROSSING=0.6 = jambe riche).
      Pas de probabilité, pas de softmax. AND-logic multiplicatif.
    """

    # Niveau 1 — Observables terrain (calcul inchangé)
    parallel_affordance: float = 0.0  # Terme N : chemin longeant [0,1]
    crossing_density: float = 0.0     # Terme O : saut de ligne [0,1]
    exit_clarity: float = 0.0         # Terme P : clarté sortie [0,1]

    # Niveau 1 étendu — nouveaux construits (Phase A : calculés, pas encore dans fitness)
    contour_crossing_guidance: float = 0.0  # [0,1] traversées transverses de contours (slope crossing)
    direct_run_index: float = 0.0           # [0,1] "open low-guidance traversal" (proxy azimut Phase A)
    safety_recovery: float = 0.0            # [0,1] ambiguïté sans structure (semi-redondant P, log-only)

    # Ordre stable pour vectorisation — ClassVar : non inclus dans __repr__/comparaisons/sérialisation
    INTENT_KEYS: ClassVar[tuple] = (
        "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
        "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
    )
    _EPS: ClassVar[float] = 1e-10

    @property
    def np_correlation_risk(self) -> float:
        return self.parallel_affordance * self.exit_clarity

    @cached_property
    def navigation_evidence(self) -> dict:
        """
        Niveau 2 — activations navigationnelles absolues. Pas de normalisation.
        Modes coexistants : HANDRAIL=0.7 + LINE_CROSSING=0.6 = jambe riche en lecture.
        AND-logic : s'effondre si une condition manque. Clés dans INTENT_KEYS.

        Limites Phase A (acceptables pour logging) :
        - DIRECT_RISK_RUN = "open low-guidance traversal" (prairie runnable ↑), pas azimut expert.
        - RELIEF_CROSSING_GUIDANCE = traversées transverses de contours uniquement (pas ridge/reentrant).
        - SAFETY_RECOVERY ≈ P élargi (semi-redondant) — log-only longtemps.
        """
        P_amb = 1.0 - self.exit_clarity
        _support = max(self.parallel_affordance, self.contour_crossing_guidance)
        return {
            "HANDRAIL_FOLLOW":          self.parallel_affordance * self.exit_clarity ** 0.5,
            "LINE_CROSSING":            self.crossing_density * (0.4 + 0.6 * P_amb),
            "ATTACK_POINT":             P_amb * (1.0 + self.crossing_density) / 2.0,
            "DIRECT_RISK_RUN":          self.direct_run_index * (1.0 - _support) * (1.0 - P_amb) ** 0.5,
            "RELIEF_CROSSING_GUIDANCE": self.contour_crossing_guidance * (1.0 - P_amb) ** 0.5,
            "SAFETY_RECOVERY":          P_amb * (1.0 - _support) * (0.5 + 0.5 * self.crossing_density * (1.0 - _support)),
        }

    @cached_property
    def activation_density(self) -> float:
        """Densité cognitive moyenne — distingue jambes riches vs pauvres."""
        return sum(self.navigation_evidence.values()) / len(self.navigation_evidence)

    @cached_property
    def relative_balance(self) -> float:
        """Soft-suppressed entropy — entropie de la distribution après pondération v^1.5.
        ⚠ PRIOR INTENTIONNEL : v^1.5 encode "signaux faibles = moins pertinents cognitivement".
           La distribution pondérée ≠ distribution originale.
           NE PAS ajouter d'autre filtrage sans retirer d'abord cet exposant (double suppression).
        Avantage vs seuil dur : continuité garantie — pas de discontinuité GA au seuil."""
        weights = [v ** 1.5 for v in self.navigation_evidence.values()]
        total = sum(weights) or self._EPS
        n = len(weights)
        return -sum((w / total) * math.log(w / total + self._EPS) for w in weights) / math.log(n)

    @cached_property
    def cognitive_richness(self) -> float:
        """Richesse cognitive = densité × équilibre. Logging Phase A uniquement."""
        return self.activation_density * self.relative_balance

    @property
    def cognitive_dispersion(self) -> float:
        return self.relative_balance

    @property
    def ambiguity(self) -> float:
        return self.relative_balance

    @property
    def dominant_intent(self) -> str:
        # Debug/inspection uniquement. NE PAS utiliser dans fitness ou diversité.
        return max(self.navigation_evidence, key=self.navigation_evidence.get)


# Alias backward-compat — préférer LegIntentInference dans le code nouveau
LegCognitiveProfile = LegIntentInference


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
