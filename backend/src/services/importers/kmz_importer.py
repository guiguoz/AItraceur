"""
Parser KMZ/KML pour circuits de CO.
KMZ = ZIP contenant un fichier .kml + images (ignorées pour le ML).
Extrait les placemarks ordonnés (postes de contrôle).
Pas de dépendance externe : zipfile + xml.etree.ElementTree (stdlib).
"""

import io
import xml.etree.ElementTree as ET
import zipfile
from typing import List, Optional

_KML_NS = [
    "http://www.opengis.net/kml/2.2",
    "http://earth.google.com/kml/2.1",
    "http://earth.google.com/kml/2.0",
    "",
]


def _find(elem, tag: str):
    for ns in _KML_NS:
        found = elem.find(f"{{{ns}}}{tag}" if ns else tag)
        if found is not None:
            return found
    return None


def _findall(elem, tag: str) -> list:
    for ns in _KML_NS:
        results = elem.findall(f"{{{ns}}}{tag}" if ns else tag)
        if results:
            return results
    return []


def _iter_descendants(elem, tag: str):
    """Cherche récursivement tous les éléments <tag> (avec ou sans namespace)."""
    results = []
    for ns in _KML_NS:
        full_tag = f"{{{ns}}}{tag}" if ns else tag
        results.extend(elem.iter(full_tag))
    # Dédupliquer (iter peut retourner des doublons via plusieurs namespaces)
    seen = set()
    out = []
    for r in results:
        if id(r) not in seen:
            seen.add(id(r))
            out.append(r)
    return out


def parse_kmz(content: bytes) -> List[dict]:
    """
    Parse un fichier KMZ (bytes) et retourne les postes de contrôle.

    Returns:
        Liste de dicts {"lat": float, "lon": float, "name": str}
        ordonnés par apparition dans le KML (= ordre du circuit).
        Liste vide si format invalide ou aucun placemark géolocalisé.
    """
    if not content:
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            # Trouver le fichier KML principal
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                return []
            # Prendre le KML à la racine en priorité (doc.kml), sinon le premier
            root_kml = next((n for n in kml_names if "/" not in n), kml_names[0])
            kml_bytes = z.read(root_kml)
    except (zipfile.BadZipFile, KeyError):
        return []

    return parse_kml(kml_bytes)


def parse_kml(content: bytes) -> List[dict]:
    """
    Parse un fichier KML (bytes) et retourne les placemarks géolocalisés.

    Gère les placemarks simples (<Point>) et ignore les LineString/Polygon.
    Retourne une liste ordonnée par apparition dans le fichier.
    """
    if not content:
        return []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    points = []
    for pm in _iter_descendants(root, "Placemark"):
        name_elem = _find(pm, "name")
        name = (name_elem.text or "").strip() if name_elem is not None else ""

        # Chercher un <Point><coordinates>
        point_elem = _find(pm, "Point")
        if point_elem is None:
            continue
        coords_elem = _find(point_elem, "coordinates")
        if coords_elem is None or not coords_elem.text:
            continue

        # Format KML : "lon,lat[,alt]"
        try:
            parts = coords_elem.text.strip().split(",")
            lon = float(parts[0])
            lat = float(parts[1])
        except (ValueError, IndexError):
            continue

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        points.append({"lat": lat, "lon": lon, "name": name})

    return points
