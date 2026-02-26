"""
Terrain Descriptor — Phase A
Convertit les features GeoJSON OCAD + ontologie ISOM 2017
en description textuelle structurée pour le modèle ffco-iof-v7.
"""

import json
import math
import os
from typing import Dict, List, Optional, Tuple


# Chemin vers l'ontologie
_SEMANTICS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "ocad_semantics.json",
)

_semantics: Optional[Dict] = None


def _load_semantics() -> Dict:
    global _semantics
    if _semantics is None:
        with open(_SEMANTICS_PATH, "r", encoding="utf-8") as f:
            _semantics = json.load(f)
    return _semantics


def get_symbol_info(sym_code: int) -> Optional[Dict]:
    """
    Retourne les infos sémantiques d'un code symbole OCAD.
    sym_code = ISOM_number * 1000 (format ocad2geojson).
    """
    sem = _load_semantics()
    # Extraire le numéro ISOM (diviser par 1000)
    isom_num = str(sym_code // 1000)
    symbol = sem["symbols"].get(isom_num)
    if symbol and symbol != "_group":
        return symbol
    # Essayer comme string direct
    symbol = sem["symbols"].get(str(sym_code))
    if symbol and symbol != "_group":
        return symbol
    return None


def _distance_m(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _bearing_name(dx: float, dy: float) -> str:
    """Retourne la direction cardinale approximative."""
    angle = math.degrees(math.atan2(dy, dx))
    directions = ["E", "NE", "N", "NO", "O", "SO", "S", "SE"]
    idx = round(angle / 45) % 8
    return directions[idx]


def describe_terrain_around_control(
    control: Dict,
    ocad_features: List[Dict],
    radius_m: float = 150.0,
) -> str:
    """
    Génère une description textuelle du terrain autour d'un poste.

    Args:
        control: {"x": float, "y": float, "number": int}
        ocad_features: liste de features GeoJSON (de ocad2geojson)
        radius_m: rayon de recherche en mètres

    Returns:
        Description texte pour le LLM (ffco-iof-v7)
    """
    cx, cy = control["x"], control["y"]
    num = control.get("number", "?")

    nearby = []
    for feature in ocad_features:
        sym_code = feature.get("properties", {}).get("sym", 0)
        info = get_symbol_info(sym_code)
        if info is None or info.get("terrain_type") in ("course_control", "course_start", "course_finish"):
            continue

        geom = feature.get("geometry", {})
        coords = _extract_closest_point(geom, cx, cy)
        if coords is None:
            continue

        fx, fy = coords
        dist = _distance_m(cx, cy, fx, fy)
        if dist > radius_m:
            continue

        nearby.append({
            "dist": dist,
            "direction": _bearing_name(fx - cx, fy - cy),
            "name_fr": info["name_fr"],
            "terrain_type": info["terrain_type"],
            "passability": info["passability"],
            "control_attractiveness": info["control_attractiveness"],
            "td_contribution": info["td_contribution"],
            "notes": info.get("notes", ""),
        })

    # Trier par distance
    nearby.sort(key=lambda f: f["dist"])

    # Construire la description
    lines = [f"Poste {num} — analyse terrain (rayon {int(radius_m)}m) :"]

    if not nearby:
        lines.append("  Aucun feature OCAD identifié à proximité.")
        lines.append("  -> Terrain non caracterise (foret generique probable).")
    else:
        # Feature le plus proche = feature du poste lui-même
        closest = nearby[0]
        lines.append(
            f"  Feature immédiat : {closest['name_fr']} "
            f"(passabilité: {closest['passability']:.0%}, attractivité poste: {closest['control_attractiveness']})"
        )
        lines.append(f"  -> {closest['notes']}")

        # Autres features proches
        impassables = [f for f in nearby[1:] if f["passability"] == 0.0]
        paths = [f for f in nearby if f["terrain_type"] in ("path", "wide_path", "narrow_path", "road")]
        slow_zones = [f for f in nearby if f["passability"] < 0.5 and f["passability"] > 0.0]

        if impassables:
            ex = impassables[0]
            lines.append(
                f"  Feature bloquant proche : {ex['name_fr']} à {ex['dist']:.0f}m {ex['direction']} "
                f"(IMPASSABLE — influence l'approche)"
            )

        if paths:
            pa = paths[0]
            lines.append(
                f"  Ligne directrice : {pa['name_fr']} à {pa['dist']:.0f}m {pa['direction']}"
            )

        if slow_zones:
            sz = slow_zones[0]
            lines.append(
                f"  Zone lente : {sz['name_fr']} à {sz['dist']:.0f}m {sz['direction']} "
                f"(speed ×{sz['passability']:.1f})"
            )

    return "\n".join(lines)


def describe_course_terrain(
    controls: List[Dict],
    ocad_features: List[Dict],
    category: str = None,
    target_length_m: float = None,
) -> str:
    """
    Génère une description terrain complète d'un parcours entier.
    Destinée à être envoyée au modèle ffco-iof-v7 pour évaluation IOF.

    Args:
        controls: liste de postes [{x, y, number, order}]
        ocad_features: features GeoJSON de la carte OCAD
        category: catégorie du circuit (ex: "M21E", "HM", "Blanc")
        target_length_m: longueur cible en mètres

    Returns:
        Description texte complète du parcours pour le LLM
    """
    lines = ["=== ANALYSE TERRAIN DU PARCOURS ==="]

    if category:
        lines.append(f"Catégorie : {category}")
    if target_length_m:
        lines.append(f"Longueur cible : {target_length_m:.0f}m")

    lines.append(f"Nombre de postes : {len(controls)}")
    lines.append("")

    # Analyser chaque poste
    for ctrl in controls:
        desc = describe_terrain_around_control(ctrl, ocad_features, radius_m=150)
        lines.append(desc)
        lines.append("")

    # Analyse des jambes
    lines.append("=== ANALYSE DES JAMBES ===")
    for i in range(len(controls) - 1):
        c1, c2 = controls[i], controls[i + 1]
        dist = _distance_m(c1["x"], c1["y"], c2["x"], c2["y"])
        direction = _bearing_name(c2["x"] - c1["x"], c2["y"] - c1["y"])

        # Analyser le terrain sur la jambe
        mid_x = (c1["x"] + c2["x"]) / 2
        mid_y = (c1["y"] + c2["y"]) / 2
        blocking = _check_blocking_terrain(mid_x, mid_y, dist / 2, ocad_features)

        line = f"  Jambe {i+1}->{i+2} : {dist:.0f}m vers {direction}"
        if blocking:
            line += f" | OBSTACLES : {', '.join(blocking)}"
        lines.append(line)

    return "\n".join(lines)


def _extract_closest_point(
    geometry: Dict, cx: float, cy: float
) -> Optional[Tuple[float, float]]:
    """Extrait le point le plus proche de (cx,cy) depuis une géométrie GeoJSON."""
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if gtype == "Point":
        return (coords[0], coords[1]) if len(coords) >= 2 else None

    elif gtype in ("LineString", "MultiPoint"):
        return _closest_in_list(coords, cx, cy)

    elif gtype == "Polygon":
        if coords:
            return _closest_in_list(coords[0], cx, cy)

    elif gtype == "MultiPolygon":
        best = None
        best_dist = float("inf")
        for poly in coords:
            if poly:
                pt = _closest_in_list(poly[0], cx, cy)
                if pt:
                    d = _distance_m(cx, cy, pt[0], pt[1])
                    if d < best_dist:
                        best_dist = d
                        best = pt
        return best

    elif gtype == "MultiLineString":
        best = None
        best_dist = float("inf")
        for line in coords:
            pt = _closest_in_list(line, cx, cy)
            if pt:
                d = _distance_m(cx, cy, pt[0], pt[1])
                if d < best_dist:
                    best_dist = d
                    best = pt
        return best

    return None


def _closest_in_list(
    coord_list: List, cx: float, cy: float
) -> Optional[Tuple[float, float]]:
    """Trouve le point le plus proche dans une liste de coordonnées."""
    best = None
    best_dist = float("inf")
    for pt in coord_list:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            d = _distance_m(cx, cy, float(pt[0]), float(pt[1]))
            if d < best_dist:
                best_dist = d
                best = (float(pt[0]), float(pt[1]))
    return best


def _check_blocking_terrain(
    cx: float, cy: float, radius_m: float, ocad_features: List[Dict]
) -> List[str]:
    """Retourne les types de terrain bloquants dans un rayon donné."""
    blocking = []
    seen = set()
    for feature in ocad_features:
        sym_code = feature.get("properties", {}).get("sym", 0)
        info = get_symbol_info(sym_code)
        if info is None:
            continue
        if info["passability"] == 0.0 and info["terrain_type"] not in ("course_control", "course_start", "course_finish"):
            geom = feature.get("geometry", {})
            coords = _extract_closest_point(geom, cx, cy)
            if coords:
                dist = _distance_m(cx, cy, coords[0], coords[1])
                if dist <= radius_m:
                    key = info["terrain_type"]
                    if key not in seen:
                        seen.add(key)
                        blocking.append(info["name_fr"])
    return blocking
