"""
Couche 1 — Génération des ControlCandidate depuis des SemanticFeature.

Fonction principale :
    candidates = generate_control_candidates(features, profile)

Règles métier :
  - Seuls les symboles dont la SemanticCategory est dans ``profile.allowed_control_categories``
    sont considérés.
  - Les objets dans des zones interdites sont supprimés.
  - Une distance minimale entre postes évite les clusters.
  - Chaque type géométrique (point, ligne, polygone) produit des candidats
    à des endroits différents :
      * Point   → 1 candidat au centre du symbole
      * Ligne   → candidats aux extrémités, jonctions avec d'autres lignes,
                  et virages significatifs
      * Polygone → candidats aux angles saillants et au centroïde si pertinent
"""
from __future__ import annotations

import math
import uuid
from collections import defaultdict
from typing import Optional

try:
    from shapely.geometry import MultiPolygon, Point, Polygon, box
    from shapely.ops import unary_union
    _SHAPELY_OK = True
except ImportError:
    _SHAPELY_OK = False

from ..profiles import CourseProfile
from .candidate import ControlCandidate, DetailType
from .ocad_parser import SemanticFeature
from .symbol_map import SemanticCategory, SemanticInfo, TerrainType


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Distance minimale entre candidats (mètres) — évite les doublons géographiques
_DEFAULT_MIN_SEPARATION_M = 20.0

# Distance à laquelle un candidat est considéré « dans » une zone interdite
_FORBIDDEN_BUFFER_M = 5.0

# Angle minimal (degrés) pour détecter un virage significatif dans une ligne
_MIN_BEND_ANGLE_DEG = 25.0

# Angle minimal (degrés) pour détecter un angle saillant dans un polygone
_MIN_POLYGON_ANGLE_DEG = 30.0


# ---------------------------------------------------------------------------
# Mapping TerrainType → DetailType
# ---------------------------------------------------------------------------

_TERRAIN_TO_DETAIL: dict[TerrainType, DetailType] = {
    TerrainType.KNOLL:           DetailType.KNOLL,
    TerrainType.HILL_TOP:        DetailType.HILL_TOP,
    TerrainType.SADDLE:          DetailType.SADDLE,
    TerrainType.DEPRESSION:      DetailType.DEPRESSION,
    TerrainType.PIT:             DetailType.PIT,
    TerrainType.REENTRANT:       DetailType.REENTRANT,
    TerrainType.SPUR:            DetailType.SPUR,
    TerrainType.EARTHWALL:       DetailType.EARTHWALL_END,
    TerrainType.EARTHWALL_RUIN:  DetailType.EARTHWALL_END,
    TerrainType.EROSION_GULLY:   DetailType.EROSION_GULLY_END,
    TerrainType.BROKEN_GROUND:   DetailType.BROKEN_GROUND,
    TerrainType.BOULDER:         DetailType.BOULDER,
    TerrainType.BOULDER_CLUSTER: DetailType.BOULDER_CLUSTER,
    TerrainType.CLIFF:           DetailType.CLIFF_FOOT,
    TerrainType.CLIFF_IMPASSABLE: DetailType.CLIFF_FOOT,
    TerrainType.ROCKY_GROUND:    DetailType.ROCKY_GROUND_EDGE,
    TerrainType.BARE_ROCK:       DetailType.BARE_ROCK,
    TerrainType.OPEN_WATER:      DetailType.POND_EDGE,
    TerrainType.POND:            DetailType.POND_EDGE,
    TerrainType.STREAM:          DetailType.STREAM_JUNCTION,
    TerrainType.MARSH:           DetailType.MARSH_EDGE,
    TerrainType.SPRING:          DetailType.SPRING,
    TerrainType.OPEN_LAND:       DetailType.CLEARING_EDGE,
    TerrainType.ROUGH_OPEN:      DetailType.CLEARING_EDGE,
    TerrainType.OPEN_LAND:       DetailType.CLEARING_EDGE,  # alias
    TerrainType.PATH:            DetailType.PATH_JUNCTION,
    TerrainType.FOOTPATH:        DetailType.PATH_JUNCTION,
    TerrainType.NARROW_RIDE:     DetailType.PATH_JUNCTION,
    TerrainType.ROAD_PAVED:      DetailType.ROAD_JUNCTION,
    TerrainType.ROAD_UNPAVED:    DetailType.ROAD_JUNCTION,
    TerrainType.ROAD_FOREST:     DetailType.ROAD_JUNCTION,
    TerrainType.BRIDGE:          DetailType.BRIDGE,
    TerrainType.CROSSING_POINT:  DetailType.CROSSING_POINT,
    TerrainType.BUILDING:        DetailType.BUILDING_CORNER,
    TerrainType.SETTLEMENT:      DetailType.BUILDING,
    TerrainType.RUIN:            DetailType.RUIN_CORNER,
    TerrainType.WALL:            DetailType.WALL_CORNER,
    TerrainType.WALL_RUINED:     DetailType.WALL_CORNER,
    TerrainType.FENCE:           DetailType.FENCE_CORNER,
    TerrainType.HEDGE:           DetailType.HEDGE_END,
    TerrainType.TOWER:           DetailType.TOWER,
    TerrainType.PASSAGE:         DetailType.PASSAGE,
    TerrainType.STAIRS:          DetailType.STAIRS,
    TerrainType.PAVED_AREA:      DetailType.PAVED_AREA_CORNER,
    TerrainType.SPECIAL_MANMADE: DetailType.SPECIAL_OBJECT,
}


def _terrain_to_detail(tt: TerrainType) -> DetailType:
    return _TERRAIN_TO_DETAIL.get(tt, DetailType.UNKNOWN)


# ---------------------------------------------------------------------------
# Profils autorisés pour un candidat (heuristique par type)
# ---------------------------------------------------------------------------

def _compute_allowed_profiles(
    info: SemanticInfo,
    all_profiles: list[CourseProfile],
) -> frozenset[str]:
    """Calcule l'ensemble des profils qui autorisent ce candidat."""
    result = set()
    for profile in all_profiles:
        if info.category.value in profile.allowed_control_categories:
            result.add(profile.id)
    return frozenset(result)


# ---------------------------------------------------------------------------
# Extraction de points candidats depuis les géométries
# ---------------------------------------------------------------------------

def _angle_deg(p0: tuple, p1: tuple, p2: tuple) -> float:
    """Angle en degrés au sommet p1 entre les segments p0→p1 et p1→p2."""
    v1 = (p0[0] - p1[0], p0[1] - p1[1])
    v2 = (p2[0] - p1[0], p2[1] - p1[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    cos_a = max(-1.0, min(1.0, dot / (n1 * n2)))
    return math.degrees(math.acos(cos_a))


def _bend_points_from_line(
    coords: list[tuple], min_angle_deg: float = _MIN_BEND_ANGLE_DEG
) -> list[Point]:
    """Retourne les Points aux virages significatifs d'une polyligne."""
    points = []
    if len(coords) < 3:
        return points
    for i in range(1, len(coords) - 1):
        angle = _angle_deg(coords[i - 1], coords[i], coords[i + 1])
        # angle = angle au virage = 180° - angle_interne → plus l'angle interne est petit,
        # plus le virage est serré.  On veut les virages > min_angle_deg.
        if (180.0 - angle) >= min_angle_deg:
            points.append(Point(coords[i]))
    return points


def _notable_polygon_corners(
    poly: Polygon, min_angle_deg: float = _MIN_POLYGON_ANGLE_DEG
) -> list[Point]:
    """Retourne les coins saillants d'un polygone (bâtiments, zones, etc.)."""
    coords = list(poly.exterior.coords)[:-1]  # fermeture supprimée
    n = len(coords)
    if n < 3:
        return []
    points = []
    for i in range(n):
        p0 = coords[(i - 1) % n]
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        angle = _angle_deg(p0, p1, p2)
        if (180.0 - angle) >= min_angle_deg:
            points.append(Point(p1))
    return points


def _candidates_from_feature(
    feat: SemanticFeature,
    info: SemanticInfo,
    allowed_profiles: frozenset[str],
    ctr: list[int],
) -> list[ControlCandidate]:
    """
    Génère les ControlCandidate depuis une SemanticFeature unique.

    Stratégie selon le type géométrique :
      - Point    → 1 candidat au point lui-même
      - Ligne    → extrémités + virages significatifs
      - Polygone → coins saillants (+ centroïde pour bâtiments)
    """
    results: list[ControlCandidate] = []
    detail = _terrain_to_detail(info.terrain_type)
    base_id = f"c_{feat.sym}_{feat.fid}"

    def make(pt: Point, detail_type: DetailType = detail) -> ControlCandidate:
        ctr[0] += 1
        return ControlCandidate(
            id=f"{base_id}_{ctr[0]}",
            geom=pt,
            detail_type=detail_type,
            attractiveness_score=info.attractiveness,
            readability_score=info.readability,
            isolation_score=1.0,      # calculé plus tard
            technical_level=max(1, info.base_td),
            allowed_profiles=allowed_profiles,
            source_sym=feat.sym,
            description_fr=info.description_fr,
            source_feature_id=feat.fid,
        )

    geom = feat.geom
    if geom is None:
        return results

    if feat.is_point:
        results.append(make(Point(geom.x, geom.y)))

    elif feat.is_linear:
        coords = list(geom.coords)
        if coords:
            # Extrémités
            results.append(make(Point(coords[0]), _end_detail(detail)))
            if len(coords) > 1:
                results.append(make(Point(coords[-1]), _end_detail(detail)))
            # Virages
            for pt in _bend_points_from_line(coords):
                results.append(make(pt, _bend_detail(detail)))

    elif feat.is_area:
        if geom.geom_type == "Polygon":
            polygons = [geom]
        elif geom.geom_type == "MultiPolygon":
            polygons = list(geom.geoms)
        else:
            polygons = []

        for poly in polygons:
            # Coins saillants
            for pt in _notable_polygon_corners(poly):
                results.append(make(pt, _corner_detail(detail)))
            # Centroïde pour les petits objets isolés (boulders area, bâtiments)
            if info.attractiveness >= 0.7:
                c = poly.centroid
                results.append(make(Point(c.x, c.y), detail))

    return results


def _end_detail(d: DetailType) -> DetailType:
    """Adapte un DetailType pour l'extrémité d'une ligne."""
    _ends = {
        DetailType.PATH_JUNCTION: DetailType.PATH_END,
        DetailType.WALL_CORNER: DetailType.WALL_END,
        DetailType.FENCE_CORNER: DetailType.FENCE_END,
        DetailType.STREAM_JUNCTION: DetailType.STREAM_SOURCE,
        DetailType.EROSION_GULLY_END: DetailType.EROSION_GULLY_END,
        DetailType.EARTHWALL_CORNER: DetailType.EARTHWALL_END,
    }
    return _ends.get(d, d)


def _bend_detail(d: DetailType) -> DetailType:
    """Adapte un DetailType pour un virage."""
    _bends = {
        DetailType.PATH_JUNCTION: DetailType.PATH_BEND,
        DetailType.STREAM_JUNCTION: DetailType.STREAM_BEND,
        DetailType.ROAD_JUNCTION: DetailType.PATH_BEND,
    }
    return _bends.get(d, d)


def _corner_detail(d: DetailType) -> DetailType:
    """Adapte un DetailType pour un coin de polygone."""
    _corners = {
        DetailType.BUILDING: DetailType.BUILDING_CORNER,
        DetailType.RUIN_CORNER: DetailType.RUIN_CORNER,
        DetailType.PAVED_AREA_CORNER: DetailType.PAVED_AREA_CORNER,
    }
    return _corners.get(d, d)


# ---------------------------------------------------------------------------
# Filtrage spatial — suppression des candidats trop proches ou interdits
# ---------------------------------------------------------------------------

def _build_forbidden_union(features: list[SemanticFeature], buffer_m: float):
    """Construit l'union géométrique des zones interdites (avec buffer)."""
    if not _SHAPELY_OK:
        return None
    zones = [f.geom.buffer(buffer_m) for f in features if f.is_forbidden and f.geom is not None]
    if not zones:
        return None
    return unary_union(zones)


def _spatial_dedup(
    candidates: list[ControlCandidate],
    min_separation_m: float,
) -> list[ControlCandidate]:
    """
    Supprime les candidats trop proches par grille spatiale O(N log N).

    Stratégie : tri par composite_score décroissant, puis insertion uniquement
    si aucun voisin retenu n'est à moins de min_separation_m.
    """
    if not candidates:
        return []

    sorted_c = sorted(candidates, key=lambda c: c.composite_score, reverse=True)
    kept: list[ControlCandidate] = []

    for cand in sorted_c:
        too_close = any(
            cand.geom.distance(k.geom) < min_separation_m
            for k in kept
        )
        if not too_close:
            kept.append(cand)

    return kept


def _compute_isolation_scores(
    candidates: list[ControlCandidate],
    radius_m: float = 100.0,
) -> list[ControlCandidate]:
    """
    Calcule l'isolation_score de chaque candidat.

    score = 1 − (nb voisins dans radius_m) / max_voisins
    Plus un candidat est isolé, plus son score est élevé.
    """
    if len(candidates) <= 1:
        return candidates

    max_neighbors = max(1, len(candidates) // 10)

    updated = []
    for cand in candidates:
        nb = sum(
            1 for other in candidates
            if other.id != cand.id
            and cand.geom.distance(other.geom) < radius_m
        )
        iso = max(0.0, 1.0 - nb / max_neighbors)
        # Crée une copie immuable avec isolation_score mis à jour
        from dataclasses import replace
        updated.append(replace(cand, isolation_score=round(iso, 3)))

    return updated


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def generate_control_candidates(
    features: list[SemanticFeature],
    profile: CourseProfile,
    *,
    all_profiles: Optional[list[CourseProfile]] = None,
    min_separation_m: float = _DEFAULT_MIN_SEPARATION_M,
    forbidden_buffer_m: float = _FORBIDDEN_BUFFER_M,
) -> list[ControlCandidate]:
    """
    Génère la liste des ControlCandidate depuis les SemanticFeature d'une carte.

    Pipeline :
      1. Filtrage par catégorie selon le profil.
      2. Extraction de points candidats (géométrie → points candidats).
      3. Filtrage des candidats dans les zones interdites.
      4. Déduplonnage spatial (min_separation_m).
      5. Calcul de l'isolation_score.

    Args:
        features:           SemanticFeatures issues du parser (parse_geojson…).
        profile:            Profil de course pilotant le filtrage.
        all_profiles:       Tous les profils connus (pour allowed_profiles).
                            Si None, seul le profil courant est enregistré.
        min_separation_m:   Distance minimale entre deux candidats (m).
        forbidden_buffer_m: Buffer (m) autour des zones interdites.

    Returns:
        Liste de ControlCandidate filtrée et annotée, triée par composite_score.
    """
    if not _SHAPELY_OK:
        raise ImportError("shapely est requis pour generate_control_candidates.")

    _all_profiles: list[CourseProfile] = all_profiles or [profile]

    # Zones interdites
    forbidden_geom = _build_forbidden_union(features, forbidden_buffer_m)

    # Compteur d'IDs
    ctr = [0]

    all_candidates: list[ControlCandidate] = []

    for feat in features:
        # Ignorer les éléments de mise en page
        if feat.is_layout:
            continue

        info = feat.info

        # Vérifier que la catégorie est autorisée par le profil
        if info.category.value not in profile.allowed_control_categories:
            continue

        # Vérifier qu'il s'agit d'un candidat poste plausible
        if info.base_td == 0:
            continue

        # Calcul des profils autorisés
        allowed = _compute_allowed_profiles(info, _all_profiles)

        # Extraction des points candidats selon la géométrie
        feat_candidates = _candidates_from_feature(feat, info, allowed, ctr)

        # Filtrage par zone interdite
        if forbidden_geom is not None:
            feat_candidates = [
                c for c in feat_candidates
                if not forbidden_geom.contains(c.geom)
            ]

        all_candidates.extend(feat_candidates)

    # Déduplonnage spatial
    deduped = _spatial_dedup(all_candidates, min_separation_m)

    # Calcul de l'isolation
    with_isolation = _compute_isolation_scores(deduped)

    # Tri final par composite_score décroissant
    return sorted(with_isolation, key=lambda c: c.composite_score, reverse=True)
