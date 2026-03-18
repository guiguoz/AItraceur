"""
Extracteur de features ML depuis des fichiers GPX/KMZ (sprint urbain).
Pipeline : GPX/KMZ → coordonnées GPS → features géométriques + terrain OSM.

Terrain : appel Overpass UNIQUE sur la bbox du circuit → calcul local par poste.
Pas de coordonnées absolues stockées (anonymisation par distances/angles).
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from ..analysis.gpx_parser import extract_waypoints, parse_gpx
from ..importers.kmz_importer import parse_kmz
from ..terrain.osm_fetcher import extract_sprint_features
from .feature_extractor import (
    ContributionFeatures,
    ControlFeatureVector,
    _haversine_m,
)

# Attractivité CO par type de feature OSM urbain
_OSM_ATTRACTIVENESS: Dict[str, float] = {
    "intersection": 0.90,   # Carrefour de rues → poste sprint par excellence
    "building_corner": 0.80,  # Angle de bâtiment
    "amenity": 0.85,        # Fontaine, horloge, boîte aux lettres
    "path": 0.70,           # Chemin/rue générique
}

_OSM_FEATURE_TYPE: Dict[str, str] = {
    "intersection": "street_intersection",
    "building_corner": "building_corner",
    "amenity": "urban_amenity",
    "path": "path",
}


def _bearing(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Azimut (0–360°) de p1 vers p2. p = (lng, lat)."""
    lat1, lat2 = math.radians(p1[1]), math.radians(p2[1])
    dlng = math.radians(p2[0] - p1[0])
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _bearing_change(b1: float, b2: float) -> float:
    """Angle de changement de direction (0–180°)."""
    diff = abs(b2 - b1) % 360
    return min(diff, 360 - diff)


def _circuit_quality_score(controls: List[Tuple[float, float]]) -> float:
    """
    Score de qualité géométrique (0–100) → normalisé en 0–1.
    Réplique la logique de FeatureExtractor._circuit_quality_score().
    """
    n = len(controls)
    if n < 3:
        return 0.5

    legs = [_haversine_m(controls[i], controls[i + 1]) for i in range(n - 1)]
    if not legs:
        return 0.5

    # Balance : coefficient de variation inversé
    mean_leg = sum(legs) / len(legs)
    std_leg = math.sqrt(sum((l - mean_leg) ** 2 for l in legs) / len(legs))
    cv = std_leg / max(mean_leg, 1.0)
    balance = max(0.0, 1.0 - cv)

    # Variété : proportion de bons changements de direction (30–150°)
    bearings = [_bearing(controls[i], controls[i + 1]) for i in range(n - 1)]
    changes = [_bearing_change(bearings[i], bearings[i + 1]) for i in range(len(bearings) - 1)]

    good_turns = sum(1 for c in changes if 30 <= c <= 150)
    variety = good_turns / max(len(changes), 1)

    # Pénalités
    penalties = 0.0
    for c in changes:
        if c < 25:  # dog-leg
            penalties += 10.0
    min_leg_sprint = 20.0
    for leg in legs:
        if leg < min_leg_sprint:
            penalties += 15.0

    score = (balance * 0.4 + variety * 0.6) * 100 - penalties
    return max(0.0, min(100.0, score)) / 100.0


def _grade_td(legs: List[float]) -> int:
    """TD 1–5 depuis la jambe la plus longue."""
    if not legs:
        return 1
    max_leg = max(legs)
    if max_leg <= 200:
        return 1
    if max_leg <= 350:
        return 2
    if max_leg <= 700:
        return 3
    if max_leg <= 1500:
        return 4
    return 5


def _compute_osm_terrain(
    controls: List[Tuple[float, float]],  # (lng, lat)
    radius_m: float = 50.0,
) -> List[Dict[str, Any]]:
    """
    Pour chaque contrôle, calcule les features terrain depuis les données OSM.

    Effectue UN SEUL appel Overpass sur la bbox du circuit, puis calcule
    les features localement pour chaque contrôle.

    Returns:
        Liste de dicts {terrain_symbol_density, nearest_path_dist_m,
                        control_feature_type, attractiveness_score}
        Une entrée par contrôle.
    """
    if not controls:
        return []

    # Bbox du circuit avec marge de 100m
    lngs = [c[0] for c in controls]
    lats = [c[1] for c in controls]
    margin_deg = 100 / 111_320  # ~100m en degrés
    bbox = {
        "min_x": min(lngs) - margin_deg,
        "max_x": max(lngs) + margin_deg,
        "min_y": min(lats) - margin_deg,
        "max_y": max(lats) + margin_deg,
    }

    try:
        osm = extract_sprint_features(bbox)
    except Exception as e:
        print(f"[gpx_extractor] Overpass error: {e}")
        osm = {}

    # Références OSM : intersections + coins de bâtiments + amenities
    osm_refs: List[Dict] = osm.get("candidates", [])  # [{x:lng, y:lat, type:str}]
    highway_ways: List[List[Tuple]] = osm.get("highway_ways", [])  # [[(lng,lat),...]]

    # Pré-calcul : liste aplatie des points highway pour nearest_path_dist_m
    highway_pts: List[Tuple[float, float]] = []
    for way in highway_ways:
        highway_pts.extend(way)

    results = []
    for lng, lat in controls:
        ctrl = (lng, lat)

        # Features OSM dans le rayon
        nearby = []
        for ref in osm_refs:
            d = _haversine_m(ctrl, (ref["x"], ref["y"]))
            if d <= radius_m:
                nearby.append((d, ref["type"]))

        terrain_density = float(len(nearby))

        # Type et attractivité : feature la plus proche
        if nearby:
            nearest_d, nearest_type = min(nearby, key=lambda x: x[0])
            feat_type = _OSM_FEATURE_TYPE.get(nearest_type, "unknown")
            attract = _OSM_ATTRACTIVENESS.get(nearest_type, 0.5)
        else:
            feat_type = "unknown"
            attract = 0.3

        # Distance au chemin OSM le plus proche
        nearest_path_d: Optional[float] = None
        if highway_pts:
            min_d = min(_haversine_m(ctrl, pt) for pt in highway_pts)
            nearest_path_d = round(min_d, 1)

        results.append({
            "terrain_symbol_density": terrain_density,
            "nearest_path_dist_m": nearest_path_d,
            "control_feature_type": feat_type,
            "attractiveness_score": attract,
        })

    return results


class GpxFeatureExtractor:
    """
    Extrait les features ML depuis un fichier GPX ou KMZ (sprint urbain uniquement).

    Usage:
        extractor = GpxFeatureExtractor()
        features = extractor.extract(gpx_bytes, circuit_type="sprint",
                                     map_type="urban", ffco_category="H21E")
    """

    def extract_from_gpx(
        self,
        content: bytes,
        circuit_type: str = "sprint",
        map_type: str = "urban",
        ffco_category: str = "Open",
        climb_m: Optional[float] = None,
        with_osm_terrain: bool = True,
    ) -> Optional[ContributionFeatures]:
        """
        Extrait depuis un fichier GPX.

        Args:
            content: Contenu brut du fichier GPX (bytes)
            circuit_type: "sprint" (seul pipeline GPX valide pour l'instant)
            map_type: "urban"
            ffco_category: Catégorie FFCO (ex: "H21E", "Open")
            climb_m: Dénivelé positif total (optionnel, non calculé depuis GPX)
            with_osm_terrain: Si True, appelle Overpass pour les features terrain

        Returns:
            ContributionFeatures ou None si le GPX est invalide / trop peu de points.
        """
        text = content.decode("utf-8", errors="replace")

        # Priorité : waypoints (postes CO) > trackpoints (parcours GPS)
        waypoints = extract_waypoints(text)
        if len(waypoints) >= 3:
            controls = [(w["lon"], w["lat"]) for w in waypoints]
        else:
            track_pts = parse_gpx(text)
            if len(track_pts) < 3:
                return None
            # Échantillonnage si track trop long (≥100 pts → garder ~15 points clés)
            controls = self._sample_track(track_pts)
            if len(controls) < 3:
                return None

        return self._compute_features(
            controls, circuit_type, map_type, ffco_category, climb_m, with_osm_terrain
        )

    def extract_from_kmz(
        self,
        content: bytes,
        circuit_type: str = "sprint",
        map_type: str = "urban",
        ffco_category: str = "Open",
        climb_m: Optional[float] = None,
        with_osm_terrain: bool = True,
    ) -> Optional[ContributionFeatures]:
        """
        Extrait depuis un fichier KMZ.
        L'image JPEG éventuelle est ignorée (pas d'interprétation symboles).
        """
        placemarks = parse_kmz(content)
        if len(placemarks) < 3:
            return None

        controls = [(p["lon"], p["lat"]) for p in placemarks]
        return self._compute_features(
            controls, circuit_type, map_type, ffco_category, climb_m, with_osm_terrain
        )

    def _sample_track(
        self,
        track_pts,
        target_n: int = 15,
        min_dist_m: float = 80.0,
    ) -> List[Tuple[float, float]]:
        """
        Réduit un tracklog à ~target_n points clés (changements de direction).
        Utilisé quand le GPX contient un trace GPS complet plutôt que des waypoints.
        """
        pts = [(p.lon, p.lat) for p in track_pts]
        if len(pts) <= target_n:
            return pts

        # Garder les points avec changement de direction significatif
        selected = [pts[0]]
        for i in range(1, len(pts) - 1):
            if _haversine_m(selected[-1], pts[i]) < min_dist_m:
                continue
            # Calcul changement de direction
            b1 = _bearing(selected[-1], pts[i])
            b2 = _bearing(pts[i], pts[i + 1])
            if _bearing_change(b1, b2) > 25:
                selected.append(pts[i])
                if len(selected) >= target_n:
                    break

        selected.append(pts[-1])
        return selected

    def _compute_features(
        self,
        controls: List[Tuple[float, float]],  # (lng, lat)
        circuit_type: str,
        map_type: str,
        ffco_category: str,
        climb_m: Optional[float],
        with_osm_terrain: bool,
    ) -> Optional[ContributionFeatures]:
        """Calcule toutes les features à partir d'une liste de (lng, lat)."""
        n = len(controls)
        if n < 3:
            return None

        # Legs et métriques circuit
        legs = [_haversine_m(controls[i], controls[i + 1]) for i in range(n - 1)]
        total_m = sum(legs)
        td = _grade_td(legs)
        bearings = [_bearing(controls[i], controls[i + 1]) for i in range(n - 1)]
        quality = _circuit_quality_score(controls)

        # Terrain OSM (un appel Overpass pour tout le circuit)
        osm_terrain = _compute_osm_terrain(controls) if with_osm_terrain else []

        feature_vectors = []
        for idx in range(n):
            fv = ControlFeatureVector(
                td_grade=td,
                pd_grade=None,  # non calculable sans DEM
                control_position_ratio=idx / max(1, n - 1),
                quality_score=quality,
            )

            if idx > 0:
                fv.leg_distance_m = round(legs[idx - 1], 1)

            if 0 < idx < n - 1:
                fv.leg_bearing_change = round(
                    _bearing_change(bearings[idx - 1], bearings[idx]), 1
                )

            if osm_terrain and idx < len(osm_terrain):
                t = osm_terrain[idx]
                fv.terrain_symbol_density = t["terrain_symbol_density"]
                fv.nearest_path_dist_m = t["nearest_path_dist_m"]
                fv.control_feature_type = t["control_feature_type"]
                fv.attractiveness_score = t["attractiveness_score"]

            feature_vectors.append(fv)

        return ContributionFeatures(
            circuit_type=circuit_type,
            map_type=map_type,
            ffco_category=ffco_category,
            td_grade=td,
            pd_grade=None,
            n_controls=n - 2,  # exclure départ et arrivée
            length_m=round(total_m),
            climb_m=climb_m,
            controls=feature_vectors,
        )
