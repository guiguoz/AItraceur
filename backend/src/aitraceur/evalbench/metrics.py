"""Indicateurs de qualité d'un circuit de CO.

Entrée : points en mètres (projection locale quelconque, y vers le nord).
Indépendant de tout moteur — utiliser lnglat_to_local_m() pour convertir
les sorties du moteur v1 (WGS84).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

try:
    import pyproj
    _PYPROJ_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYPROJ_AVAILABLE = False

try:
    from shapely.geometry import Point, Polygon, LineString
    _SHAPELY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SHAPELY_AVAILABLE = False


@dataclass(frozen=True)
class CourseMetrics:
    n_controls: int               # postes hors départ et arrivée
    length_m: float               # somme des jambes à vol d'oiseau
    leg_min_m: float
    leg_max_m: float
    leg_cv: float                 # écart-type / moyenne des longueurs de jambe
    min_pair_dist_m: float        # plus petite distance entre deux points (toutes paires, sauf départ–arrivée)
    n_pairs_below_30m: int        # paires de postes à moins de 30 m (strict, postes seuls)
    n_pairs_below_60m: int
    crossings: int                # paires de jambes non adjacentes qui se coupent
    doglegs: int                  # postes où le changement de cap est >= 150 degrés
    max_in_radius: int            # K2 : plus grand nombre de postes dans un disque de rayon R centré sur un poste (lui compris)
    n_clustered: int              # postes ayant au moins 2 autres postes à moins de R
    coverage_4x4: float           # K4 : part des 16 cases de la zone contenant au moins un point
    hull_ratio: float             # aire enveloppe convexe des points / aire de la zone
    is_loop: bool                 # départ et arrivée à moins de 1 m
    forbidden_hits: int           # points strictement à l'intérieur d'un polygone interdit


# ---------------------------------------------------------------------------
# Fonctions géométriques de base (sans dépendance externe)
# ---------------------------------------------------------------------------

def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _segments_intersect(
    p1: tuple[float, float], p2: tuple[float, float],
    p3: tuple[float, float], p4: tuple[float, float],
) -> bool:
    """Renvoie True si les segments [p1p2] et [p3p4] se croisent (hors extrémités communes)."""
    def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)

    # Les segments se croisent si d1 et d2 ont des signes opposés ET d3 et d4 aussi
    if (d1 * d2 < 0) and (d3 * d4 < 0):
        return True

    # Cas colinéaires : on les considère comme non-croisants
    return False


def _point_in_polygon(pt: tuple[float, float], poly: Sequence[tuple[float, float]]) -> bool:
    """Ray-casting : True si pt est strictement à l'intérieur de poly."""
    x, y = pt
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _convex_hull_area(pts: list[tuple[float, float]]) -> float:
    """Renvoie l'aire de l'enveloppe convexe via l'algorithme de Graham scan."""
    if len(pts) < 3:
        return 0.0
    # Graham scan
    pivot = min(pts, key=lambda p: (p[1], p[0]))

    def _angle(p: tuple[float, float]) -> float:
        return math.atan2(p[1] - pivot[1], p[0] - pivot[0])

    sorted_pts = sorted(pts, key=_angle)
    hull: list[tuple[float, float]] = []
    for p in sorted_pts:
        while len(hull) >= 2:
            o, a = hull[-2], hull[-1]
            if (a[0] - o[0]) * (p[1] - o[1]) - (a[1] - o[1]) * (p[0] - o[0]) <= 0:
                hull.pop()
            else:
                break
        hull.append(p)
    # Shoelace
    n = len(hull)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += hull[i][0] * hull[j][1]
        area -= hull[j][0] * hull[i][1]
    return abs(area) / 2.0


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def course_metrics(
    points_xy: Sequence[tuple[float, float]],
    *,
    area_bbox: tuple[float, float, float, float],  # (xmin, ymin, xmax, ymax)
    forbidden: Sequence[Sequence[tuple[float, float]]] = (),
    cluster_radius_m: float,
) -> CourseMetrics:
    """Calcule les indicateurs d'un circuit.

    Args:
        points_xy: départ, postes…, arrivée, dans l'ordre.
        area_bbox: boîte englobante de la zone (mètres).
        forbidden: séquences de polygones interdits (liste de sommets xy).
        cluster_radius_m: rayon pour les indicateurs d'amas (K2, n_clustered).

    Returns:
        CourseMetrics avec tous les indicateurs calculés.
    """
    pts = list(points_xy)
    if len(pts) < 2:
        raise ValueError("Un circuit nécessite au moins un départ et une arrivée.")

    start = pts[0]
    end = pts[-1]
    controls = pts[1:-1]  # postes internes uniquement
    n_controls = len(controls)

    # --- Jambes ---
    legs: list[float] = [_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    length_m = sum(legs)
    leg_min_m = min(legs) if legs else 0.0
    leg_max_m = max(legs) if legs else 0.0
    if len(legs) >= 2:
        mean_l = length_m / len(legs)
        variance = sum((l - mean_l) ** 2 for l in legs) / len(legs)
        leg_cv = math.sqrt(variance) / mean_l if mean_l > 0 else 0.0
    else:
        leg_cv = 0.0

    # --- Distance minimale entre toutes les paires (sauf paire départ–arrivée) ---
    all_pts = pts
    min_pair = math.inf
    for i in range(len(all_pts)):
        for j in range(i + 1, len(all_pts)):
            # exclure la paire (start, end) si c'est bien départ–arrivée
            if (i == 0 and j == len(all_pts) - 1):
                continue
            d = _dist(all_pts[i], all_pts[j])
            if d < min_pair:
                min_pair = d
    min_pair_dist_m = min_pair if min_pair != math.inf else 0.0

    # --- Paires de postes (hors départ et arrivée) ---
    n_pairs_below_30 = 0
    n_pairs_below_60 = 0
    for i in range(len(controls)):
        for j in range(i + 1, len(controls)):
            d = _dist(controls[i], controls[j])
            if d < 30.0:
                n_pairs_below_30 += 1
            if d < 60.0:
                n_pairs_below_60 += 1

    # --- Croisements ---
    # Segments = [(pts[0],pts[1]), (pts[1],pts[2]), ...]
    segments = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    n_seg = len(segments)
    crossings = 0
    # Boucle : circuit = départ et arrivée adjacents si boucle
    is_loop = _dist(start, end) < 1.0
    for i in range(n_seg):
        for j in range(i + 2, n_seg):
            # adjacents = partagent une extrémité
            if j == n_seg - 1 and i == 0 and is_loop:
                continue  # première et dernière jambe adjacentes si boucle
            if _segments_intersect(segments[i][0], segments[i][1],
                                    segments[j][0], segments[j][1]):
                crossings += 1

    # --- Dog-legs (changement de cap >= 150°) ---
    doglegs = 0
    for i in range(1, len(pts) - 1):
        ax, ay = pts[i - 1][0] - pts[i][0], pts[i - 1][1] - pts[i][1]
        bx, by = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        norm_a = math.hypot(ax, ay)
        norm_b = math.hypot(bx, by)
        if norm_a < 1e-9 or norm_b < 1e-9:
            continue
        cos_angle = (ax * bx + ay * by) / (norm_a * norm_b)
        cos_angle = max(-1.0, min(1.0, cos_angle))
        # Angle entre vecteur d'arrivée et vecteur de départ
        # vecteur d'arrivée = pts[i-1] → pts[i], vecteur de départ = pts[i] → pts[i+1]
        # changement de cap = angle entre (pts[i] → pts[i-1]) retourné et (pts[i] → pts[i+1])
        # = π - arccos(dot(arrivée, départ) / (|arrivée| |départ|))
        # avec arrivée = pts[i] - pts[i-1] et départ = pts[i+1] - pts[i]
        in_x, in_y = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        out_x, out_y = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        norm_in = math.hypot(in_x, in_y)
        norm_out = math.hypot(out_x, out_y)
        if norm_in < 1e-9 or norm_out < 1e-9:
            continue
        cos_cap = (in_x * out_x + in_y * out_y) / (norm_in * norm_out)
        cos_cap = max(-1.0, min(1.0, cos_cap))
        # changement de cap = π - arccos(cos_cap) si cos_cap → 1 (tout droit = 0°)
        # ou arccos(-cos_cap) si l'on définit 0° = tout droit, 180° = demi-tour
        # Définition plan §0.6 : 0° = tout droit, 180° = demi-tour
        # vecteur d'arrivée (direction courante) · vecteur de départ → cos(δ)
        # δ = 0° si même direction, 180° si demi-tour → dog-leg si δ >= 150°
        delta_deg = math.degrees(math.acos(cos_cap))
        if delta_deg >= 150.0:
            doglegs += 1

    # --- Amas (sur postes uniquement) ---
    max_in_radius = 0
    n_clustered = 0
    for i, c in enumerate(controls):
        count_in = sum(1 for other in controls if _dist(c, other) <= cluster_radius_m)
        if count_in > max_in_radius:
            max_in_radius = count_in
        others_in = sum(1 for j, other in enumerate(controls) if j != i and _dist(c, other) < cluster_radius_m)
        if others_in >= 2:
            n_clustered += 1

    # --- Couverture 4×4 ---
    xmin, ymin, xmax, ymax = area_bbox
    bw = (xmax - xmin) / 4
    bh = (ymax - ymin) / 4
    occupied = set()
    for p in pts:
        col = min(int((p[0] - xmin) / bw), 3) if bw > 0 else 0
        row = min(int((p[1] - ymin) / bh), 3) if bh > 0 else 0
        occupied.add((row, col))
    coverage_4x4 = len(occupied) / 16.0

    # --- Hull ratio ---
    bbox_area = (xmax - xmin) * (ymax - ymin)
    hull_area = _convex_hull_area(list(pts))
    hull_ratio = hull_area / bbox_area if bbox_area > 0 else 0.0

    # --- Zones interdites ---
    forbidden_hits = 0
    for p in pts:
        for poly in forbidden:
            if _point_in_polygon(p, poly):
                forbidden_hits += 1
                break

    return CourseMetrics(
        n_controls=n_controls,
        length_m=round(length_m, 2),
        leg_min_m=round(leg_min_m, 2),
        leg_max_m=round(leg_max_m, 2),
        leg_cv=round(leg_cv, 4),
        min_pair_dist_m=round(min_pair_dist_m, 2),
        n_pairs_below_30m=n_pairs_below_30,
        n_pairs_below_60m=n_pairs_below_60,
        crossings=crossings,
        doglegs=doglegs,
        max_in_radius=max_in_radius,
        n_clustered=n_clustered,
        coverage_4x4=round(coverage_4x4, 6),
        hull_ratio=round(hull_ratio, 6),
        is_loop=is_loop,
        forbidden_hits=forbidden_hits,
    )


def lnglat_to_local_m(
    points_lnglat: Sequence[tuple[float, float]],
    center_lnglat: tuple[float, float],
) -> list[tuple[float, float]]:
    """Projection azimutale équidistante centrée (pyproj, +proj=aeqd).

    Pour les sorties du moteur v1 (WGS84 lng/lat).
    Nécessite pyproj.
    """
    if not _PYPROJ_AVAILABLE:
        raise ImportError("pyproj est requis pour lnglat_to_local_m.")
    crs = pyproj.CRS.from_proj4(
        f"+proj=aeqd +lat_0={center_lnglat[1]} +lon_0={center_lnglat[0]} +units=m"
    )
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return [transformer.transform(lng, lat) for lng, lat in points_lnglat]
