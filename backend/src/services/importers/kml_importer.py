# =============================================
# Importeur KMZ/KML
# Import de fichiers Google Earth
# =============================================

import io
import json
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import base64


# =============================================
# Types de données
# =============================================
@dataclass
class KMLPlacemark:
    """Un lieu KML."""

    name: str
    description: str = ""
    coordinates: List[Tuple[float, float, float]] = field(
        default_factory=list
    )  # lon, lat, alt
    style: str = ""


@dataclass
class KMLCircuit:
    """Un circuit issu du KML."""

    name: str
    placemarks: List[KMLPlacemark] = field(default_factory=list)
    color: str = ""


@dataclass
class KMZImport:
    """Résultat de l'import KMZ."""

    circuits: List[KMLCircuit] = field(default_factory=list)
    map_image: Optional[bytes] = None
    map_filename: str = ""
    bounds: Dict = field(default_factory=dict)
    status: str = "pending"
    rotation: float = 0.0  # Rotation de l'image overlay
    image_width: int = 0  # Largeur de l'image en pixels
    image_height: int = 0  # Hauteur de l'image en pixels


# =============================================
# Importeur KML/KMZ
# =============================================
class KMLImporter:
    """
    Importe des fichiers KML et KMZ.

    KML (Keyhole Markup Language) est le format Google Earth.
    KMZ est la version compressée (zippée) de KML.
    """

    # Namespace KML
    KML_NS = "http://www.opengis.net/kml/2.2"

    def __init__(self):
        """Initialise l'importeur."""
        self.content = None

    def import_kmz(self, file_path: str) -> KMZImport:
        """
        Importe un fichier KMZ.

        Args:
            file_path: Chemin vers le fichier KMZ

        Returns:
            KMZImport avec les circuits et l'image
        """
        result = KMZImport(status="processing")

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                # Chercher le fichier KML
                kml_file = None
                for name in zf.namelist():
                    if name.endswith(".kml"):
                        kml_file = name
                        break

                if not kml_file:
                    result.status = "error"
                    result.error = "Aucun fichier KML trouvé dans le KMZ"
                    return result

                # Lire le KML
                kml_content = zf.read(kml_file)
                result.circuits = self._parse_kml(kml_content)

                # Parser les bounds du GroundOverlay (pour l'image de carte)
                overlay_bounds = self._parse_ground_overlay_bounds(kml_content)
                if overlay_bounds:
                    result.bounds = overlay_bounds
                    result.rotation = overlay_bounds.get("rotation", 0.0)
                    print(f"[DEBUG] Found GroundOverlay bounds: {result.bounds}")

                # Chercher une image de carte (à la racine et dans les sous-dossiers)
                image_extensions = [
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".tif",
                    ".tiff",
                    ".gif",
                    ".bmp",
                ]
                for name in zf.namelist():
                    # Skip the KML file itself
                    if name.endswith(".kml"):
                        continue
                    if any(name.lower().endswith(ext) for ext in image_extensions):
                        result.map_filename = name
                        result.map_image = zf.read(name)

                        # Get image dimensions
                        try:
                            from PIL import Image
                            from io import BytesIO

                            img = Image.open(BytesIO(result.map_image))
                            result.image_width = img.width
                            result.image_height = img.height
                            print(
                                f"[DEBUG] Found image: {name}, size: {len(result.map_image)} bytes, dimensions: {img.width}x{img.height}"
                            )
                        except Exception as e:
                            print(f"[DEBUG] Could not get image dimensions: {e}")

                        break

                result.status = "ok"

        except zipfile.BadZipFile:
            result.status = "error"
            result.error = "Fichier KMZ invalide"
        except Exception as e:
            result.status = "error"
            result.error = str(e)

        return result

    def import_kml(self, file_path: str) -> KMZImport:
        """
        Importe un fichier KML.

        Args:
            file_path: Chemin vers le fichier KML

        Returns:
            KMZImport avec les circuits
        """
        result = KMZImport(status="processing")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                kml_content = f.read()

            result.circuits = self._parse_kml(kml_content)
            result.status = "ok"

        except Exception as e:
            result.status = "error"
            result.error = str(e)

        return result

    def _parse_kml(self, kml_content: bytes) -> List[KMLCircuit]:
        """Parse le contenu KML."""
        circuits = []

        try:
            # Parser le XML
            root = ET.fromstring(kml_content)

            # Registre le namespace
            ns = {"kml": self.KML_NS}

            # Chercher tous les Folder ou Document
            folders = root.findall(".//kml:Folder", ns)
            if not folders:
                folders = root.findall(".//Folder")

            # Get namespace URI for finding child elements
            ns_uri = ns.get("kml", "")

            for folder in folders:
                # Chercher les Placemarks dans le folder - use fully qualified name
                if ns_uri:
                    placemarks = folder.findall(f"{{{ns_uri}}}Placemark")
                else:
                    placemarks = folder.findall("Placemark")

                if not placemarks:
                    placemarks = folder.findall("Placemark")

                if placemarks:
                    # Use fully qualified name for folder name too
                    if ns_uri:
                        folder_name = folder.find(f"{{{ns_uri}}}name")
                        folder_name = (
                            folder_name.text if folder_name is not None else "Circuit"
                        )
                    else:
                        folder_name = folder.findtext("name", "Circuit")

                    circuit = KMLCircuit(name=folder_name or "Circuit")

                    for pm in placemarks:
                        placemark = self._parse_placemark(pm, ns)
                        if placemark:
                            circuit.placemarks.append(placemark)

                    if circuit.placemarks:
                        circuits.append(circuit)

            # Si pas de folders, chercher les Placemarks au racine
            if not circuits:
                if ns_uri:
                    placemarks = root.findall(f"{{{ns_uri}}}Placemark")
                else:
                    placemarks = root.findall(".//kml:Placemark", ns)

                if not placemarks:
                    placemarks = root.findall(".//Placemark")

                if placemarks:
                    circuit = KMLCircuit(name="Circuit import")
                    for pm in placemarks:
                        placemark = self._parse_placemark(pm, ns)
                        if placemark:
                            circuit.placemarks.append(placemark)

                    if circuit.placemarks:
                        circuits.append(circuit)

        except ET.ParseError as e:
            print(f"Erreur parsing KML: {e}")

        return circuits

    def _parse_ground_overlay_bounds(self, kml_content: bytes) -> Optional[Dict]:
        """
        Parse les bounds d'un GroundOverlay dans le KML.

        Returns:
            Dict avec min_lat, max_lat, min_lon, max_lon, rotation, et les 4 coins
        """
        import math

        try:
            root = ET.fromstring(kml_content)
            ns = {"kml": self.KML_NS}
            ns_uri = ns.get("kml", "")

            # Chercher le GroundOverlay
            if ns_uri:
                ground_overlays = root.findall(f".//{{{ns_uri}}}GroundOverlay")
                if not ground_overlays:
                    ground_overlays = root.findall(".//GroundOverlay")
            else:
                ground_overlays = root.findall(".//GroundOverlay")

            for overlay in ground_overlays:
                # Chercher LatLonBox
                if ns_uri:
                    lat_lon_box = overlay.find(f"{{{ns_uri}}}LatLonBox")
                    if lat_lon_box is None:
                        lat_lon_box = overlay.find("LatLonBox")
                else:
                    lat_lon_box = overlay.find("LatLonBox")

                if lat_lon_box is not None:
                    # Extraire les coordonnées - avec le namespace car les enfants l'ont aussi
                    if ns_uri:
                        north = lat_lon_box.find(f"{{{ns_uri}}}north")
                        south = lat_lon_box.find(f"{{{ns_uri}}}south")
                        east = lat_lon_box.find(f"{{{ns_uri}}}east")
                        west = lat_lon_box.find(f"{{{ns_uri}}}west")
                        rotation_elem = lat_lon_box.find(f"{{{ns_uri}}}rotation")
                    else:
                        north = lat_lon_box.find("north")
                        south = lat_lon_box.find("south")
                        east = lat_lon_box.find("east")
                        west = lat_lon_box.find("west")
                        rotation_elem = lat_lon_box.find("rotation")

                    # Fallback: try without namespace for children
                    if north is None:
                        north = lat_lon_box.find("north")
                    if south is None:
                        south = lat_lon_box.find("south")
                    if east is None:
                        east = lat_lon_box.find("east")
                    if west is None:
                        west = lat_lon_box.find("west")
                    if rotation_elem is None:
                        rotation_elem = lat_lon_box.find("rotation")

                    if (
                        north is not None
                        and south is not None
                        and east is not None
                        and west is not None
                    ):
                        north_val = float(north.text)
                        south_val = float(south.text)
                        east_val = float(east.text)
                        west_val = float(west.text)

                        rotation = 0.0
                        if rotation_elem is not None and rotation_elem.text:
                            rotation = float(rotation_elem.text)

                        # Center of the overlay
                        center_lat = (north_val + south_val) / 2
                        center_lon = (east_val + west_val) / 2

                        # Unrotated corners
                        tl = [north_val, west_val]
                        tr = [north_val, east_val]
                        br = [south_val, east_val]
                        bl = [south_val, west_val]

                        # Apply rotation if present
                        # KML spec: rotation is counterclockwise (CCW) in degrees
                        if abs(rotation) > 0.01:
                            rot_rad = math.radians(rotation)
                            cos_r = math.cos(rot_rad)
                            sin_r = math.sin(rot_rad)

                            def rotate_corner(lat, lon):
                                dy = lat - center_lat
                                dx = lon - center_lon
                                # CCW rotation: x'=x*cos-y*sin, y'=x*sin+y*cos
                                new_dx = dx * cos_r - dy * sin_r
                                new_dy = dx * sin_r + dy * cos_r
                                return [center_lat + new_dy, center_lon + new_dx]

                            tl = rotate_corner(north_val, west_val)
                            tr = rotate_corner(north_val, east_val)
                            br = rotate_corner(south_val, east_val)
                            bl = rotate_corner(south_val, west_val)

                        bounds = {
                            "min_lat": south_val,
                            "max_lat": north_val,
                            "min_lon": west_val,
                            "max_lon": east_val,
                            "rotation": rotation,
                            "center_lat": center_lat,
                            "center_lon": center_lon,
                            "corners": {
                                "topLeft": tl,
                                "topRight": tr,
                                "bottomRight": br,
                                "bottomLeft": bl,
                            },
                        }

                        return bounds

            return None

        except ET.ParseError as e:
            print(f"Erreur parsing GroundOverlay: {e}")
            return None

    def _parse_placemark(self, pm: ET.Element, ns: Dict) -> Optional[KMLPlacemark]:
        """Parse un Placemark KML."""
        name = pm.findtext("kml:name", "", ns) or pm.findtext("name", "", ns)
        description = pm.findtext("kml:description", "", ns) or pm.findtext(
            "description", "", ns
        )

        # Chercher les coordonnées
        coords_text = ""

        # Get the namespace URI from the dict
        ns_uri = ns.get("kml", "")

        # Point - use fully qualified tag name since element is already in namespace
        point = pm.find("kml:Point", ns) or pm.find("Point", ns)
        if point:
            # When finding children of namespaced element, use fully qualified name
            if ns_uri:
                coords = point.find(f"{{{ns_uri}}}coordinates")
                if coords is None:
                    coords = point.find("coordinates")
            else:
                coords = point.find("coordinates")
            if coords is not None:
                coords_text = coords.text or ""

        # LineString
        if not coords_text:
            line = pm.find("kml:LineString", ns) or pm.find("LineString", ns)
            if line:
                if ns_uri:
                    coords = line.find(f"{{{ns_uri}}}coordinates")
                    if coords is None:
                        coords = line.find("coordinates")
                else:
                    coords = line.find("coordinates")
                if coords is not None:
                    coords_text = coords.text or ""

        # Parser les coordonnées
        coordinates = []
        if coords_text:
            for coord in coords_text.strip().split():
                parts = coord.split(",")
                if len(parts) >= 2:
                    try:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        alt = float(parts[2]) if len(parts) > 2 else 0.0
                        coordinates.append((lon, lat, alt))
                    except ValueError:
                        continue

        if not coordinates:
            return None

        # Style (couleur)
        style = ""
        style_url = pm.find("kml:styleUrl", ns) or pm.find("styleUrl", ns)
        if style_url is not None:
            style = style_url.text or ""

        return KMLPlacemark(
            name=name,
            description=description,
            coordinates=coordinates,
            style=style,
        )


# =============================================
# Convertisseur vers notre format
# =============================================
def convert_kmz_to_circuits(kmz_import: KMZImport) -> List[Dict]:
    """
    Convertit le résultat KMZ en circuits AItraceur.

    Args:
        kmz_import: Résultat de l'import

    Returns:
        Liste de circuits au format AItraceur
    """
    circuits = []
    all_lats = []
    all_lons = []

    for kml_circuit in kmz_import.circuits:
        circuit = {
            "name": kml_circuit.name,
            "controls": [],
        }

        # Convertir les placemarks en contrôles
        for i, placemark in enumerate(kml_circuit.placemarks):
            if placemark.coordinates:
                # Prendre le premier point
                lon, lat, alt = placemark.coordinates[0]

                # Collecter pour les bounds
                all_lats.append(lat)
                all_lons.append(lon)

                control = {
                    "order": i + 1,
                    "x": lon,  # Longitude
                    "y": lat,  # Latitude
                    "z": alt,  # Altitude
                    "description": placemark.name or f"Poste {i + 1}",
                }
                circuit["controls"].append(control)

        if circuit["controls"]:
            circuits.append(circuit)

    # Calculer les bounds depuis les coordonnées
    if all_lats and all_lons:
        kmz_import.bounds = {
            "min_lat": min(all_lats),
            "max_lat": max(all_lats),
            "min_lon": min(all_lons),
            "max_lon": max(all_lons),
        }

    return circuits


# =============================================
# Fonctions utilitaires
# =============================================
def import_kmz_file(file_path: str) -> KMZImport:
    """Importe un fichier KMZ."""
    importer = KMLImporter()
    return importer.import_kmz(file_path)


def import_kml_file(file_path: str) -> KMZImport:
    """Importe un fichier KML."""
    importer = KMLImporter()
    return importer.import_kml(file_path)
