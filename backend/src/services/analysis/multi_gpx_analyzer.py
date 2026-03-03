"""
Analyse multi-GPX consensus — calibration terrain + difficulté par jambe.

Usage :
    tracks = [parse_gpx(content1), parse_gpx(content2), ...]
    controls = [{"x": lng, "y": lat, "order": 1}, ...]
    result = analyze_multi_gpx(tracks, controls)
"""

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .gpx_parser import TrackPoint

# Chemin vers terrain_calibration.json (relatif à ce fichier)
_CALIBRATION_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "terrain_calibration.json")
)


# ── Haversine (pas de dépendance externe) ───────────────────────────────────

def _haversine_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Distance Haversine en mètres entre (lng1, lat1) et (lng2, lat2)."""
    R = 6_371_000.0
    lat1, lat2 = math.radians(p1[1]), math.radians(p2[1])
    dlat = math.radians(p2[1] - p1[1])
    dlng = math.radians(p2[0] - p1[0])
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Conversion RouteGadget → TrackPoint ─────────────────────────────────────

def routegadget_to_trackpoints(rg_route: List[Dict]) -> List[TrackPoint]:
    """
    Convertit une liste de points RouteGadget en TrackPoint.

    RouteGadget format : [{"lat": float, "lon": float, "time": int|None}, ...]
    Le champ "time" est un timestamp Unix en secondes (ou None).
    """
    from datetime import timezone as _tz

    points = []
    for pt in rg_route:
        lat = pt.get("lat")
        lon = pt.get("lon")
        if lat is None or lon is None:
            continue
        time = None
        raw_time = pt.get("time")
        if raw_time is not None:
            try:
                from datetime import datetime as _dt
                time = _dt.fromtimestamp(float(raw_time), tz=_tz.utc)
            except (ValueError, OSError):
                pass
        points.append(TrackPoint(lat=float(lat), lon=float(lon), time=time, ele=None))
    return points


# ── Snap GPX → jambes ────────────────────────────────────────────────────────

def _snap_to_controls(
    track: List[TrackPoint],
    controls: List[Dict],
    snap_radius_m: float,
) -> Optional[List[int]]:
    """
    Pour chaque poste, trouve l'index du TrackPoint le plus proche.

    Returns:
        Liste d'indices (len = len(controls)) dans le track, ou None si
        le snap échoue pour ≥ 1 poste (coureur perdu / track trop court).
    """
    snap_indices = []
    search_from = 0  # on cherche en avant pour garder l'ordre chronologique

    for ctrl in controls:
        best_idx = None
        best_dist = float("inf")
        ctrl_pos = (ctrl["x"], ctrl["y"])

        for i in range(search_from, len(track)):
            pt = track[i]
            d = _haversine_m(ctrl_pos, (pt.lon, pt.lat))
            if d < best_dist:
                best_dist = d
                best_idx = i

        if best_idx is None or best_dist > snap_radius_m:
            return None  # poste non atteint

        snap_indices.append(best_idx)
        search_from = best_idx  # on avance dans le track

    return snap_indices


# ── Persistance calibration ───────────────────────────────────────────────────

def load_terrain_calibration() -> Dict[str, float]:
    """Charge les multiplicateurs depuis terrain_calibration.json. Retourne {} si vide."""
    try:
        with open(_CALIBRATION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("calibrated"):
                return data.get("multipliers", {})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def save_terrain_calibration(
    calibration: Dict[str, float],
    runners_analyzed: int,
    source: str = "multi-gpx",
) -> bool:
    """
    Sauvegarde les multiplicateurs dans terrain_calibration.json.
    Merge avec les valeurs existantes (les nouvelles priment).
    Retourne True si succès.
    """
    try:
        existing = load_terrain_calibration()
        merged = {**existing, **calibration}
        payload = {
            "calibrated": True,
            "source": source,
            "runners_analyzed": runners_analyzed,
            "date": datetime.now(timezone.utc).isoformat(),
            "multipliers": merged,
        }
        with open(_CALIBRATION_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        print(f"[WARNING] Impossible de sauvegarder la calibration terrain : {e}")
        return False


# ── Analyse principale ────────────────────────────────────────────────────────

def analyze_multi_gpx(
    gpx_tracks: List[List[TrackPoint]],
    controls: List[Dict],
    ocad_geojson: Optional[Dict] = None,
    snap_radius_m: float = 50.0,
) -> Dict:
    """
    Analyse un ensemble de tracks GPX issus d'une même course CO.

    Args:
        gpx_tracks: Liste de tracks (chaque track = liste de TrackPoint)
        controls: Liste de postes [{x: lng, y: lat, order: int}, ...]
                  Triés par ordre croissant (départ = order 0 ou 1).
        ocad_geojson: GeoJSON OCAD optionnel pour la calibration terrain.
        snap_radius_m: Rayon de snap poste-GPS en mètres (défaut 50m).

    Returns:
        Dict avec runners_analyzed, legs_analyzed, speed_per_leg,
        difficulty_per_leg, consensus_path, avoided_zones,
        terrain_calibration (si OCAD), training_examples.
    """
    # Trier les postes par order
    controls_sorted = sorted(controls, key=lambda c: c.get("order", 0))
    n_legs = len(controls_sorted) - 1

    if n_legs < 1 or not gpx_tracks:
        return {
            "runners_analyzed": 0,
            "legs_analyzed": 0,
            "speed_per_leg": {},
            "difficulty_per_leg": {},
            "consensus_path": {},
            "avoided_zones": [],
            "terrain_calibration": {},
            "training_examples": [],
        }

    # ── Snap chaque track aux postes ─────────────────────────────────────────
    valid_snaps: List[Tuple[List[TrackPoint], List[int]]] = []
    for track in gpx_tracks:
        if len(track) < 2:
            continue
        indices = _snap_to_controls(track, controls_sorted, snap_radius_m)
        if indices is not None:
            valid_snaps.append((track, indices))

    runners_analyzed = len(valid_snaps)

    # ── Vitesse par jambe ─────────────────────────────────────────────────────
    # speeds_by_leg[leg_idx] = [speed_mpm_runner1, speed_mpm_runner2, ...]
    speeds_by_leg: Dict[int, List[float]] = defaultdict(list)
    # segments_by_leg[leg_idx] = [[(lat,lng), ...], ...]  (tous les tracés)
    segments_by_leg: Dict[int, List[List[Tuple[float, float]]]] = defaultdict(list)

    for track, snap_indices in valid_snaps:
        for leg in range(n_legs):
            i_start = snap_indices[leg]
            i_end = snap_indices[leg + 1]
            if i_start >= i_end:
                continue

            seg_pts = track[i_start : i_end + 1]

            # Longueur GPS du segment (somme des segments)
            dist_m = 0.0
            for k in range(len(seg_pts) - 1):
                dist_m += _haversine_m(
                    (seg_pts[k].lon, seg_pts[k].lat),
                    (seg_pts[k + 1].lon, seg_pts[k + 1].lat),
                )

            # Temps
            t_start = seg_pts[0].time
            t_end = seg_pts[-1].time
            if t_start is None or t_end is None:
                # Pas de temps → estimer depuis la distance (base 150 m/min)
                continue
            delta_s = (t_end - t_start).total_seconds()
            if delta_s <= 0 or dist_m < 10:
                continue

            speed_mpm = dist_m / (delta_s / 60.0)
            # Filtre aberrants : < 50 m/min ou > 400 m/min
            if 50 <= speed_mpm <= 400:
                speeds_by_leg[leg].append(speed_mpm)

            # Conserver les points du tracé
            segments_by_leg[leg].append([(pt.lat, pt.lon) for pt in seg_pts])

    # ── Statistiques par jambe ────────────────────────────────────────────────
    speed_per_leg: Dict[str, Dict] = {}
    difficulty_per_leg: Dict[str, float] = {}

    for leg in range(n_legs):
        speeds = speeds_by_leg.get(leg, [])
        if not speeds:
            continue
        mean_s = sum(speeds) / len(speeds)
        sorted_s = sorted(speeds)
        mid = len(sorted_s) // 2
        median_s = sorted_s[mid] if len(sorted_s) % 2 else (sorted_s[mid - 1] + sorted_s[mid]) / 2
        variance = sum((s - mean_s) ** 2 for s in speeds) / len(speeds)
        std_s = math.sqrt(variance)
        cv = std_s / mean_s if mean_s > 0 else 0.0

        speed_per_leg[str(leg + 1)] = {
            "mean": round(mean_s, 1),
            "median": round(median_s, 1),
            "std": round(std_s, 1),
            "runners": len(speeds),
        }
        # CV > 0.3 → jambe difficile (grande dispersion = navigation complexe)
        difficulty_per_leg[str(leg + 1)] = round(cv, 3)

    # ── Consensus de tracé (heatmap 20m×20m) ─────────────────────────────────
    consensus_path: Dict[str, List[Dict]] = {}
    avoided_zones: List[List[float]] = []

    for leg in range(n_legs):
        segs = segments_by_leg.get(leg, [])
        if not segs:
            continue

        # Grille 20m × 20m — clé = (round_lat, round_lng)
        cell_m = 20.0
        lat_step = cell_m / 111_000.0
        lng_step = cell_m / 72_600.0  # ~49°N

        cell_counts: Dict[Tuple, int] = defaultdict(int)
        for seg in segs:
            for lat, lng in seg:
                key = (round(lat / lat_step) * lat_step, round(lng / lng_step) * lng_step)
                cell_counts[key] += 1

        n_runners = len(segs)
        top_cells = sorted(cell_counts.items(), key=lambda x: -x[1])[:50]
        consensus_path[str(leg + 1)] = [
            {
                "lat": round(k[0], 6),
                "lon": round(k[1], 6),
                "frequency": round(v / n_runners, 2),
            }
            for k, v in top_cells
            if v / n_runners >= 0.1
        ]

        # Zones évitées : cellules où < 10% des coureurs passent → zone difficile
        for k, v in cell_counts.items():
            if v / n_runners < 0.1:
                avoided_zones.append([round(k[0], 6), round(k[1], 6), cell_m])

    # ── Calibration terrain (si OCAD GeoJSON fourni) ─────────────────────────
    terrain_calibration: Dict[str, float] = {}
    if ocad_geojson and valid_snaps:
        terrain_calibration = _calibrate_terrain(valid_snaps, ocad_geojson)

    # ── Exemples d'entraînement pour ffco-iof-v7 ─────────────────────────────
    training_examples = _generate_training_examples(
        speed_per_leg, difficulty_per_leg, controls_sorted, runners_analyzed
    )

    return {
        "runners_analyzed": runners_analyzed,
        "legs_analyzed": len(speed_per_leg),
        "speed_per_leg": speed_per_leg,
        "difficulty_per_leg": difficulty_per_leg,
        "consensus_path": consensus_path,
        "avoided_zones": avoided_zones[:20],  # limiter la taille de la réponse
        "terrain_calibration": terrain_calibration,
        "training_examples": training_examples,
    }


# ── Calibration terrain ───────────────────────────────────────────────────────

def _calibrate_terrain(
    valid_snaps: List[Tuple],
    ocad_geojson: Dict,
) -> Dict[str, float]:
    """
    Corrèle les vitesses GPS avec les symboles ISOM sous les tracés.
    Retourne {terrain_type: multiplier} normalisé sur base_speed=170 m/min.
    """
    try:
        import json
        import os

        # Charger le mapping symbole → terrain_type depuis ocad_semantics.json
        semantics_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "data", "ocad_semantics.json",
        )
        with open(semantics_path, "r", encoding="utf-8") as f:
            semantics = json.load(f)
    except Exception:
        return {}

    # Grouper les vitesses GPS par type de terrain
    terrain_speeds: Dict[str, List[float]] = defaultdict(list)
    features = ocad_geojson.get("features", [])
    BASE_SPEED = 170.0  # m/min référence H21E sur forêt standard

    for track, snap_indices in valid_snaps:
        for i in range(len(track) - 1):
            pt = track[i]
            pt_next = track[i + 1]

            if pt.time is None or pt_next.time is None:
                continue
            delta_s = (pt_next.time - pt.time).total_seconds()
            if delta_s <= 0:
                continue

            dist_m = _haversine_m((pt.lon, pt.lat), (pt_next.lon, pt_next.lat))
            if dist_m < 5:
                continue

            speed_mpm = dist_m / (delta_s / 60.0)
            if not (50 <= speed_mpm <= 400):
                continue

            # Trouver le symbole ISOM sous ce point
            terrain_type = _find_terrain_type(pt.lat, pt.lon, features, semantics)
            if terrain_type:
                terrain_speeds[terrain_type].append(speed_mpm)

    # Calculer les multiplicateurs
    result = {}
    for terrain_type, speeds in terrain_speeds.items():
        if len(speeds) < 5:  # pas assez de données
            continue
        sorted_s = sorted(speeds)
        mid = len(sorted_s) // 2
        median_speed = sorted_s[mid]
        result[terrain_type] = round(median_speed / BASE_SPEED, 3)

    return result


def _find_terrain_type(lat: float, lon: float, features: List[Dict], semantics: Dict) -> Optional[str]:
    """Ray-casting pour trouver le type de terrain ISOM sous un point GPS."""
    for feature in features:
        geom = feature.get("geometry", {})
        props = feature.get("properties", {})
        sym_id = str(props.get("sym", ""))

        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        if not _point_in_feature(lat, lon, geom):
            continue

        # Mapper symbole ISOM → terrain_type
        sym_info = semantics.get("symbols", {}).get(sym_id, {})
        return sym_info.get("terrain_type")

    return None


def _point_in_feature(lat: float, lon: float, geom: Dict) -> bool:
    """Ray-casting simplifié pour Polygon/MultiPolygon (coordonnées WGS84)."""
    polys = []
    if geom["type"] == "Polygon":
        polys = [geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        polys = geom["coordinates"]

    for poly in polys:
        if poly and _ray_cast(lon, lat, poly[0]):  # ring extérieur
            return True
    return False


def _ray_cast(x: float, y: float, ring: List) -> bool:
    """Ray-casting standard pour un anneau de polygone."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ── Exemples d'entraînement pour ffco-iof-v7 ─────────────────────────────────

def _generate_training_examples(
    speed_per_leg: Dict,
    difficulty_per_leg: Dict,
    controls: List[Dict],
    runners_analyzed: int,
) -> List[Dict]:
    """Génère 1-3 paires Q/R pertinentes depuis l'analyse pour enrichir ffco-iof-v7."""
    examples = []

    if not speed_per_leg:
        return examples

    # Jambe la plus difficile (CV le plus élevé)
    if difficulty_per_leg:
        hardest_leg = max(difficulty_per_leg, key=lambda k: difficulty_per_leg[k])
        cv = difficulty_per_leg[hardest_leg]
        speed_info = speed_per_leg.get(hardest_leg, {})
        if speed_info and cv > 0.15:
            level = "difficile (CV>0.3 = navigation complexe)" if cv > 0.3 else "moyen"
            examples.append({
                "instruction": f"Sur un circuit analysé avec {runners_analyzed} coureurs, la jambe {hardest_leg} a une variance de temps de {cv:.2f} (CV). Que signifie cette valeur ?",
                "output": f"CV={cv:.2f} indique un niveau {level}. La vitesse moyenne était {speed_info.get('mean',0):.0f} m/min (médiane {speed_info.get('median',0):.0f} m/min). Un CV élevé signifie que les coureurs ont eu des stratégies d'itinéraire très différentes — signe d'une jambe à choix multiples ou avec un objet ambigu.",
            })

    # Jambe la plus rapide
    if speed_per_leg:
        fastest_leg = max(speed_per_leg, key=lambda k: speed_per_leg[k]["median"])
        s = speed_per_leg[fastest_leg]
        if s["median"] > 100:
            examples.append({
                "instruction": f"Sur quelle jambe les coureurs ont-ils couru le plus vite ?",
                "output": f"La jambe {fastest_leg} — vitesse médiane {s['median']:.0f} m/min ({runners_analyzed} coureurs). Cela correspond typiquement à un chemin ou terrain ouvert (TD1-TD2). En forêt classique TD3, la vitesse attendue est 120-150 m/min pour H21E.",
            })

    return examples
