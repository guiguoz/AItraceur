# =============================================
# Extracteur de features ML
# Collecte anonymisée de circuits contribués
# =============================================
#
# Principe d'anonymisation :
#   - Les coordonnées WGS84 sont utilisées uniquement pour calculer
#     des distances/angles (translation-invariantes).
#   - Aucune coordonnée absolue n'est stockée.
#   - Pour les features terrain (GeoJSON), les coordonnées sont
#     recentrées sur (0, 0) avant calcul.
# =============================================

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..importers.iof_xml_importer import IOFXMLImporter, XMLRaceData

# Patterns de détection automatique depuis le nom du cours XML
_COLOR_PATTERN = re.compile(
    r'\b(blanc|jaune|orange|vert|bleu|violet|rouge|marron|noir)\b', re.IGNORECASE
)
_CATEGORY_PATTERN = re.compile(
    r'\b(H|D|W|M)(10|12|14|16|18|20|21|35|40|45|50|55|60|65|70|75|80)([EAB])?\b',
    re.IGNORECASE
)


def _detect_color(course_name: str) -> Optional[str]:
    """Détecte la couleur depuis le nom du cours (ex: 'Bleu 4.5km' → 'bleu')."""
    m = _COLOR_PATTERN.search(course_name or "")
    return m.group(1).lower() if m else None


def _detect_category(course_name: str) -> Optional[str]:
    """Détecte la catégorie FFCO/IOF ou couleur (ex: 'H21E' → 'H21E', 'Bleu 4.5km' → 'Bleu')."""
    m = _CATEGORY_PATTERN.search(course_name or "")
    if m:
        return m.group(0).upper()
    m2 = _COLOR_PATTERN.search(course_name or "")
    return m2.group(1).capitalize() if m2 else None


# =============================================
# Types
# =============================================

@dataclass
class ControlFeatureVector:
    """Vecteur de features ML pour un poste individuel."""
    leg_distance_m: Optional[float] = None
    leg_bearing_change: Optional[float] = None
    control_position_ratio: Optional[float] = None
    td_grade: Optional[int] = None
    pd_grade: Optional[int] = None
    terrain_symbol_density: Optional[float] = None
    nearest_path_dist_m: Optional[float] = None
    control_feature_type: Optional[str] = None
    attractiveness_score: Optional[float] = None
    quality_score: Optional[float] = None  # label ML


@dataclass
class ContributionFeatures:
    """Features extraites d'un circuit contribué."""
    # Métadonnées circuit (anonymes)
    circuit_type: Optional[str] = None       # sprint / middle / long
    map_type: Optional[str] = None           # urban / forest
    ffco_category: Optional[str] = None      # H21E, D16, H45, Open... (fourni par l'utilisateur)
    td_grade: Optional[int] = None
    pd_grade: Optional[int] = None
    n_controls: int = 0
    length_m: Optional[float] = None
    climb_m: Optional[float] = None

    # Auto-détection depuis le nom du cours XML (non stocké en DB)
    course_name: Optional[str] = None        # nom brut du cours (ex: "Bleu 4.5km")
    color_detected: Optional[str] = None     # couleur auto-détectée
    category_detected: Optional[str] = None  # catégorie auto-détectée

    # Vecteurs par poste
    controls: List[ControlFeatureVector] = field(default_factory=list)


# =============================================
# Utilitaires géométriques
# =============================================

def _haversine_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Distance haversine en mètres entre deux points WGS84 (lng, lat)."""
    R = 6_371_000.0
    lat1, lat2 = math.radians(p1[1]), math.radians(p2[1])
    dlat = math.radians(p2[1] - p1[1])
    dlng = math.radians(p2[0] - p1[0])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Azimut (0–360°) de p1 vers p2, en WGS84 (lng, lat)."""
    lat1 = math.radians(p1[1])
    lat2 = math.radians(p2[1])
    dlng = math.radians(p2[0] - p1[0])
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return math.degrees(math.atan2(x, y)) % 360


def _bearing_change(b_in: float, b_out: float) -> float:
    """Changement d'angle entre deux azimuts (0–180°)."""
    diff = abs(b_in - b_out) % 360
    if diff > 180:
        diff = 360 - diff
    return diff


def _grade_td(positions: List[Tuple[float, float]]) -> int:
    """TD1-TD5 basé sur la jambe maximale."""
    if len(positions) < 2:
        return 1
    legs = [_haversine_m(positions[i], positions[i + 1]) for i in range(len(positions) - 1)]
    max_leg = max(legs)
    if max_leg <= 200:
        return 1
    elif max_leg <= 350:
        return 2
    elif max_leg <= 700:
        return 3
    elif max_leg <= 1500:
        return 4
    return 5


def _grade_pd(climb_m: float, total_length_m: float) -> int:
    """PD1-PD5 basé sur le ratio D+/distance."""
    if total_length_m <= 0:
        return 1
    ratio = climb_m / total_length_m
    if ratio < 0.01:
        return 1
    elif ratio < 0.02:
        return 2
    elif ratio < 0.04:
        return 3
    elif ratio < 0.06:
        return 4
    return 5


def _circuit_quality_score(
    positions: List[Tuple[float, float]],
    length_m: float,
    circuit_type: Optional[str] = None,
) -> float:
    """
    Score de qualité simplifié du circuit (0–100).
    Basé sur : équilibre des jambes, variété angulaire, distances.
    Sert de label ML approximatif pour chaque poste du circuit.
    Les seuils varient selon le type de circuit (sprint vs middle/long).
    """
    if len(positions) < 3:
        return 50.0

    legs = [_haversine_m(positions[i], positions[i + 1]) for i in range(len(positions) - 1)]
    mean_leg = sum(legs) / len(legs)
    if mean_leg == 0:
        return 50.0

    # Seuil minimum de jambe selon le type de circuit
    # Sprint urbain : 20m acceptable  |  middle/long forêt : 60m
    is_sprint = (circuit_type or "").lower() == "sprint"
    min_leg_threshold = 20.0 if is_sprint else 60.0

    # Balance : coefficient de variation des jambes
    cv = math.sqrt(sum((d - mean_leg) ** 2 for d in legs) / len(legs)) / mean_leg
    balance_score = max(0, 100 - cv * 200)

    # Variété : proportion de bonnes rotations (30–150°)
    bearings = [_bearing(positions[i], positions[i + 1]) for i in range(len(positions) - 1)]
    good_turns = sum(
        1 for i in range(len(bearings) - 1)
        if 30 <= _bearing_change(bearings[i], bearings[i + 1]) <= 150
    )
    variety_score = (good_turns / max(1, len(bearings) - 1)) * 100

    # Pénalité dog-legs
    dog_legs = sum(
        1 for i in range(len(bearings) - 1)
        if _bearing_change(bearings[i], bearings[i + 1]) < 25
    )
    penalty = min(40, dog_legs * 10)

    # Pénalité postes trop proches (seuil adapté au type de circuit)
    close = sum(1 for d in legs if d < min_leg_threshold)
    penalty += min(30, close * 15)

    total = (balance_score * 0.4 + variety_score * 0.6) - penalty
    return max(0.0, min(100.0, total))


# =============================================
# Extraction depuis GeoJSON (terrain OCAD)
# =============================================

# Chargement des sémantiques ISOM (fallback si absent)
_ISOM_ATTRACTIVENESS: Dict[str, float] = {}
_ISOM_TERRAIN_TYPES: Dict[str, str] = {}

try:
    import json
    import os
    _sem_path = os.path.join(os.path.dirname(__file__), "../../../data/ocad_semantics.json")
    if os.path.exists(_sem_path):
        with open(_sem_path, encoding="utf-8") as _f:
            _sem = json.load(_f)
        for _code, _props in _sem.items():
            _ISOM_ATTRACTIVENESS[_code] = _props.get("control_attractiveness", 0.3)
            _ISOM_TERRAIN_TYPES[_code] = _props.get("terrain_type", "unknown")
except Exception:
    pass


def _wgs84_to_relative_m(
    lng: float, lat: float, centroid_lng: float, centroid_lat: float
) -> Tuple[float, float]:
    """Convertit WGS84 (degrés) en offset mètres par rapport au centroïde."""
    DEG_LAT_M = 111320.0
    cos_lat = math.cos(math.radians(centroid_lat))
    dx = (lng - centroid_lng) * DEG_LAT_M * cos_lat
    dy = (lat - centroid_lat) * DEG_LAT_M
    return dx, dy


def _dist_m(ax: float, ay: float, bx: float, by: float) -> float:
    """Distance euclidéenne en mètres (coordonnées relatives déjà en mètres)."""
    return math.hypot(ax - bx, ay - by)


def _extract_terrain_features(
    ctrl_dx: float,
    ctrl_dy: float,
    geojson_features: List[Dict],
    radius_m: float = 50.0,
) -> Dict[str, Any]:
    """
    Extrait les features terrain dans un rayon autour d'un poste.
    ctrl_dx, ctrl_dy : position du poste en mètres relatifs (centrés sur 0,0).
    Les features GeoJSON sont également en mètres relatifs (sortie de extract_geojson.js).
    """
    nearby = []
    nearest_path_dist = None
    PATH_TYPES = {"path", "track", "road", "street", "footway", "cycleway"}

    for feature in geojson_features:
        geom = feature.get("geometry", {})
        props = feature.get("properties", {})
        sym = str(props.get("sym", ""))

        coords_list: List[Tuple[float, float]] = []
        gtype = geom.get("type", "")
        if gtype == "Point":
            c = geom.get("coordinates", [])
            if len(c) >= 2:
                coords_list = [(c[0], c[1])]
        elif gtype in ("LineString", "MultiPoint"):
            coords_list = [(c[0], c[1]) for c in geom.get("coordinates", []) if len(c) >= 2]
        elif gtype == "Polygon":
            outer = geom.get("coordinates", [[]])[0]
            coords_list = [(c[0], c[1]) for c in outer if len(c) >= 2]

        for fx, fy in coords_list:
            dist = _dist_m(ctrl_dx, ctrl_dy, fx, fy)
            if dist <= radius_m:
                terrain_type = _ISOM_TERRAIN_TYPES.get(sym, "unknown")
                nearby.append({
                    "dist": dist,
                    "sym": sym,
                    "terrain_type": terrain_type,
                    "attractiveness": _ISOM_ATTRACTIVENESS.get(sym, 0.3),
                })
                if terrain_type in PATH_TYPES and (nearest_path_dist is None or dist < nearest_path_dist):
                    nearest_path_dist = dist
            break  # Un seul point représentatif par feature

    if not nearby:
        return {
            "terrain_symbol_density": 0.0,
            "nearest_path_dist_m": None,
            "control_feature_type": None,
            "attractiveness_score": None,
        }

    nearest = min(nearby, key=lambda x: x["dist"])
    return {
        "terrain_symbol_density": float(len(nearby)),
        "nearest_path_dist_m": nearest_path_dist,
        "control_feature_type": nearest["terrain_type"],
        "attractiveness_score": nearest["attractiveness"],
    }


# =============================================
# Extracteur principal
# =============================================

class FeatureExtractor:
    """
    Extrait les features ML anonymisées depuis :
      - Un fichier IOF XML 3.0 (obligatoire)
      - Des features GeoJSON terrain optionnelles (depuis ocad2geojson côté frontend)
    """

    def extract(
        self,
        xml_bytes: bytes,
        geojson_features: Optional[List[Dict]] = None,
        circuit_type: Optional[str] = None,
        climb_m: Optional[float] = None,
    ) -> ContributionFeatures:
        """
        Parse le XML et extrait les features de chaque poste.
        Si le XML contient plusieurs circuits, prend le plus long.
        Pour extraire tous les circuits, utiliser extract_all().

        Args:
            xml_bytes: Contenu du fichier IOF XML
            geojson_features: Liste de features GeoJSON en mètres relatifs (depuis extract_geojson.js)
            circuit_type: "sprint" | "classic" | "middle" (optionnel)
            climb_m: Dénivelé en mètres (optionnel)

        Returns:
            ContributionFeatures du circuit le plus long
        """
        results = self.extract_all(xml_bytes, geojson_features, circuit_type, climb_m)
        if not results:
            return ContributionFeatures()
        # Retourner le circuit avec le plus de postes (ou le plus long)
        return max(results, key=lambda r: r.n_controls)

    def extract_all(
        self,
        xml_bytes: bytes,
        geojson_features: Optional[List[Dict]] = None,
        circuit_type: Optional[str] = None,
        climb_m: Optional[float] = None,
    ) -> List["ContributionFeatures"]:
        """
        Extrait les features de TOUS les circuits du XML.
        Un XML peut contenir plusieurs circuits (bleu, jaune, orange...).
        """
        importer = IOFXMLImporter()
        race_data: XMLRaceData = importer.parse_bytes(xml_bytes, "contribution.xml")

        if not race_data.courses:
            return []

        results = []
        for course in race_data.courses:
            result = self._extract_course(race_data, course, geojson_features, circuit_type, climb_m)
            if result is not None:
                results.append(result)
        return results

    def _extract_course(
        self,
        race_data: "XMLRaceData",
        course: Any,
        geojson_features: Optional[List[Dict]],
        circuit_type: Optional[str],
        climb_m: Optional[float],
    ) -> Optional["ContributionFeatures"]:
        """Extrait les features d'un circuit unique."""
        # Résoudre les postes dans l'ordre
        ordered_controls = []
        for ctrl_id in course.controls:
            ctrl = race_data.controls.get(ctrl_id)
            if ctrl and ctrl.lat is not None and ctrl.lng is not None:
                ordered_controls.append(ctrl)

        if len(ordered_controls) < 2:
            return None

        # Positions WGS84 (lng, lat) — utilisées uniquement pour calculs
        positions = [(c.lng, c.lat) for c in ordered_controls]

        # Centroïde WGS84 pour conversion en coords relatives
        n = len(ordered_controls)
        centroid_lng = sum(p[0] for p in positions) / n
        centroid_lat = sum(p[1] for p in positions) / n

        # Longueur totale
        total_length = sum(
            _haversine_m(positions[i], positions[i + 1])
            for i in range(len(positions) - 1)
        )
        if course.length_meters:
            total_length = float(course.length_meters)

        climb = climb_m or float(course.climb_meters or 0)
        td = _grade_td(positions)
        pd = _grade_pd(climb, total_length)
        quality = _circuit_quality_score(positions, total_length, circuit_type)

        # Calcul des azimuts
        bearings = [
            _bearing(positions[i], positions[i + 1])
            for i in range(len(positions) - 1)
        ]

        feature_vectors: List[ControlFeatureVector] = []

        for idx, ctrl in enumerate(ordered_controls):
            fv = ControlFeatureVector(
                td_grade=td,
                pd_grade=pd,
                control_position_ratio=idx / max(1, n - 1),
                quality_score=quality / 100.0,  # normaliser 0–1
            )

            # Distance de la jambe (depuis le poste précédent)
            if idx > 0:
                fv.leg_distance_m = _haversine_m(positions[idx - 1], positions[idx])

            # Changement d'angle à ce poste
            if 0 < idx < n - 1 and idx - 1 < len(bearings) and idx < len(bearings):
                fv.leg_bearing_change = _bearing_change(bearings[idx - 1], bearings[idx])

            # Features terrain (GeoJSON en mètres relatifs depuis extract_geojson.js)
            if geojson_features:
                # Convertir la position WGS84 du poste en mètres relatifs (même référentiel que GeoJSON)
                ctrl_dx, ctrl_dy = _wgs84_to_relative_m(ctrl.lng, ctrl.lat, centroid_lng, centroid_lat)
                terrain = _extract_terrain_features(ctrl_dx, ctrl_dy, geojson_features)
                fv.terrain_symbol_density = terrain["terrain_symbol_density"]
                fv.nearest_path_dist_m = terrain["nearest_path_dist_m"]
                fv.control_feature_type = terrain["control_feature_type"]
                fv.attractiveness_score = terrain["attractiveness_score"]

            feature_vectors.append(fv)

        # Auto-détection couleur + catégorie depuis le nom du cours
        course_name = getattr(course, "name", None) or ""
        color_det = _detect_color(course_name)
        category_det = _detect_category(course_name)

        return ContributionFeatures(
            circuit_type=circuit_type,
            td_grade=td,
            pd_grade=pd,
            n_controls=n,
            length_m=total_length,
            climb_m=climb,
            course_name=course_name,
            color_detected=color_det,
            category_detected=category_det,
            controls=feature_vectors,
        )
