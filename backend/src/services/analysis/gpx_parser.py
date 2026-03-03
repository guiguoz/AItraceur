"""
Parser GPX — lit des fichiers GPX (1.0/1.1) et retourne des TrackPoint.
Pas de dépendance externe : xml.etree.ElementTree (stdlib).
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class TrackPoint:
    lat: float
    lon: float
    time: Optional[datetime]
    ele: Optional[float]


# Namespaces GPX 1.0 et 1.1
_GPX_NS = [
    "http://www.topografix.com/GPX/1/1",
    "http://www.topografix.com/GPX/1/0",
    "",
]


def _find(elem, tag):
    """Cherche <tag> avec ou sans namespace."""
    for ns in _GPX_NS:
        if ns:
            found = elem.find(f"{{{ns}}}{tag}")
        else:
            found = elem.find(tag)
        if found is not None:
            return found
    return None


def _findall(elem, tag):
    """Cherche tous les <tag> avec ou sans namespace."""
    results = []
    for ns in _GPX_NS:
        if ns:
            results = elem.findall(f"{{{ns}}}{tag}")
        else:
            results = elem.findall(tag)
        if results:
            return results
    return []


def _parse_time(text: str) -> Optional[datetime]:
    """Parse ISO 8601 datetime (GPX standard). Retourne None si invalide."""
    if not text:
        return None
    text = text.strip()
    # Formats courants : 2024-03-01T10:00:00Z, 2024-03-01T10:00:00+01:00
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text[:19], fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def parse_gpx(content: str) -> List[TrackPoint]:
    """
    Parse un fichier GPX (XML) et retourne la liste des TrackPoint.

    Gère GPX 1.0 et 1.1. Lit les <trk>/<trkseg>/<trkpt> en priorité,
    puis les <wpt> si aucun track n'est trouvé.

    Args:
        content: Contenu brut du fichier GPX (string UTF-8)

    Returns:
        Liste de TrackPoint. Liste vide si format invalide ou aucun point.
    """
    if not content or not content.strip():
        return []

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    points: List[TrackPoint] = []

    # Chercher dans les tracks d'abord
    for trk in _findall(root, "trk"):
        for trkseg in _findall(trk, "trkseg"):
            for trkpt in _findall(trkseg, "trkpt"):
                pt = _parse_trkpt(trkpt)
                if pt is not None:
                    points.append(pt)

    # Fallback : waypoints si aucun track
    if not points:
        for wpt in _findall(root, "wpt"):
            pt = _parse_trkpt(wpt)
            if pt is not None:
                points.append(pt)

    return points


def _parse_trkpt(elem) -> Optional[TrackPoint]:
    """Parse un élément <trkpt> ou <wpt>."""
    try:
        lat = float(elem.get("lat", ""))
        lon = float(elem.get("lon", ""))
    except (ValueError, TypeError):
        return None

    # Élévation (optionnelle)
    ele = None
    ele_elem = _find(elem, "ele")
    if ele_elem is not None and ele_elem.text:
        try:
            ele = float(ele_elem.text)
        except ValueError:
            pass

    # Temps (optionnel)
    time = None
    time_elem = _find(elem, "time")
    if time_elem is not None:
        time = _parse_time(time_elem.text)

    return TrackPoint(lat=lat, lon=lon, time=time, ele=ele)


def build_synthetic_gpx(
    controls: List[tuple],
    speed_mpm: float = 150.0,
    start_time: Optional[datetime] = None,
    noise_m: float = 10.0,
) -> str:
    """
    Génère un GPX synthétique pour les tests.

    Args:
        controls: Liste de (lng, lat) dans l'ordre du circuit
        speed_mpm: Vitesse en m/min
        start_time: Heure de départ (UTC), défaut = maintenant
        noise_m: Bruit GPS en mètres (±)

    Returns:
        Contenu GPX XML (string)
    """
    import math
    import random

    if start_time is None:
        start_time = datetime(2024, 3, 1, 9, 0, 0, tzinfo=timezone.utc)

    # Génère des intermédiaires entre chaque poste
    def haversine_m(p1, p2):
        R = 6371000.0
        lat1, lat2 = math.radians(p1[1]), math.radians(p2[1])
        dlat = math.radians(p2[1] - p1[1])
        dlng = math.radians(p2[0] - p1[0])
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">')
    lines.append("  <trk><trkseg>")

    current_time = start_time
    for i in range(len(controls) - 1):
        p1 = controls[i]
        p2 = controls[i + 1]
        dist = haversine_m(p1, p2)
        n_pts = max(2, int(dist / 20))  # un point tous les 20m

        for j in range(n_pts + 1):
            frac = j / n_pts
            lng = p1[0] + (p2[0] - p1[0]) * frac
            lat = p1[1] + (p2[1] - p1[1]) * frac
            # Bruit GPS
            lat += random.gauss(0, noise_m / 111000)
            lng += random.gauss(0, noise_m / 72600)
            # Temps
            seg_time = (dist * frac) / speed_mpm * 60  # secondes
            pt_time = start_time.replace(second=0)
            from datetime import timedelta
            pt_time = start_time + timedelta(seconds=int(i * dist / speed_mpm * 60 + seg_time))
            ts = pt_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(f'    <trkpt lat="{lat:.7f}" lon="{lng:.7f}"><time>{ts}</time></trkpt>')

    lines.append("  </trkseg></trk>")
    lines.append("</gpx>")
    return "\n".join(lines)
