# =============================================
# Exporteur KMZ/KML
# Sprint 9: Exports & Polish
# =============================================

import io
import json
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime


# =============================================
# Types de données
# =============================================
@dataclass
class KMLControl:
    """Un contrôle KML."""

    number: int
    name: str
    x: float  # Longitude
    y: float  # Latitude
    z: float = 0.0  # Altitude
    description: str = ""


@dataclass
class KMLCircuit:
    """Un circuit KML."""

    name: str
    controls: List[KMLControl]
    color: str = "ff0000ff"  # RGBA (bleu)


# =============================================
# Exporteur KML/KMZ
# =============================================
class KMLExporter:
    """
    Exporte les circuits au format KML et KMZ.

    KML (Keyhole Markup Language) est le format Google Earth.
    KMZ est la version compressée (zippée) de KML.
    """

    # Namespace KML
    KML_NS = "http://www.opengis.net/kml/2.2"
    KML_NS_PREFIX = "{http://www.opengis.net/kml/2.2}"

    # Couleurs par défaut (ABGR format for KML)
    COLORS = {
        "blue": "ff0000ff",
        "red": "ff0000ff",
        "green": "ff00ff00",
        "yellow": "ff00ffff",
        "orange": "ff0080ff",
        "purple": "ff8000ff",
        "white": "ffffffff",
        "black": "ff000000",
    }

    def __init__(self):
        """Initialise l'exporteur."""
        self.circuits: List[KMLCircuit] = []

    def add_circuit(self, circuit: KMLCircuit):
        """Ajoute un circuit à exporter."""
        self.circuits.append(circuit)

    def export_kml(self) -> str:
        """
        Exporte au format KML.

        Returns:
            Contenu KML
        """
        # Créer le document KML
        kml = ET.Element("kml")
        kml.set("xmlns", self.KML_NS)

        document = ET.SubElement(kml, "Document")

        # Nom du document
        doc_name = ET.SubElement(document, "name")
        doc_name.text = "AItraceur Circuits"

        # Styles
        for circuit in self.circuits:
            style_id = f"style_{circuit.name.replace(' ', '_')}"
            self._add_style(document, style_id, circuit.color)

        # Circuits (Folders)
        for circuit in self.circuits:
            folder = self._create_circuit_folder(circuit)
            document.append(folder)

        # Convertir en string
        return self._to_kml_string(kml)

    def export_kmz(
        self, map_image: bytes = None, map_filename: str = "map.png"
    ) -> bytes:
        """
        Exporte au format KMZ (ZIP).

        Args:
            map_image: Image de la carte (optionnel)
            map_filename: Nom du fichier image dans le KMZ

        Returns:
            Contenu KMZ (bytes)
        """
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Ajouter le fichier KML
            kml_content = self.export_kml()
            zf.writestr("doc.kml", kml_content)

            # Ajouter l'image si fournie
            if map_image:
                zf.writestr(map_filename, map_image)

        return buffer.getvalue()

    def _add_style(self, parent: ET.Element, style_id: str, color: str):
        """Ajoute un style KML."""
        style = ET.SubElement(parent, "Style")
        style.set("id", style_id)

        # Style de la ligne (LineStyle)
        line_style = ET.SubElement(style, "LineStyle")
        color_elem = ET.SubElement(line_style, "color")
        color_elem.text = color
        width = ET.SubElement(line_style, "width")
        width.text = "3"

        # Style du point (IconStyle)
        icon_style = ET.SubElement(style, "IconStyle")
        color_elem2 = ET.SubElement(icon_style, "color")
        color_elem2.text = color
        scale = ET.SubElement(icon_style, "scale")
        scale.text = "1.2"

        # Icône
        icon = ET.SubElement(icon_style, "Icon")
        href = ET.SubElement(icon, "href")
        href.text = "http://maps.google.com/mapfiles/kml/paddle/wht-circle.png"

    def _create_circuit_folder(self, circuit: KMLCircuit) -> ET.Element:
        """Crée un folder pour un circuit."""
        folder = ET.Element("Folder")

        # Nom du folder
        name = ET.SubElement(folder, "name")
        name.text = circuit.name

        # Description
        desc = ET.SubElement(folder, "description")
        desc.text = f"Circuit: {circuit.name} - {len(circuit.controls)} postes"

        # Contrôles (Points)
        for ctrl in circuit.controls:
            placemark = self._create_control_placemark(ctrl, circuit.name)
            folder.append(placemark)

        # Ligne reliant les contrôles (LineString)
        if len(circuit.controls) > 1:
            line_placemark = self._create_line_placemark(circuit)
            folder.append(line_placemark)

        return placemark

    def _create_control_placemark(
        self, ctrl: KMLControl, circuit_name: str
    ) -> ET.Element:
        """Crée un placemark pour un contrôle."""
        pm = ET.Element("Placemark")

        # Nom
        name = ET.SubElement(pm, "name")
        name.text = ctrl.name or f"Poste {ctrl.number}"

        # Description
        desc = ET.SubElement(pm, "description")
        desc.text = ctrl.description or f"Contrôle #{ctrl.number}"

        # Style
        style_url = ET.SubElement(pm, "styleUrl")
        style_url.text = f"#style_{circuit_name.replace(' ', '_')}"

        # Point
        point = ET.SubElement(pm, "Point")
        coords = ET.SubElement(point, "coordinates")
        coords.text = f"{ctrl.x},{ctrl.y},{ctrl.z}"

        return pm

    def _create_line_placemark(self, circuit: KMLCircuit) -> ET.Element:
        """Crée un placemark avec la ligne du circuit."""
        pm = ET.Element("Placemark")

        # Nom
        name = ET.SubElement(pm, "name")
        name.text = f"{circuit.name} - Parcours"

        # Style
        style_url = ET.SubElement(pm, "styleUrl")
        style_url.text = f"#style_{circuit.name.replace(' ', '_')}"

        # LineString
        line = ET.SubElement(pm, "LineString")
        tessellate = ET.SubElement(line, "tessellate")
        tessellate.text = "1"

        coords = ET.SubElement(line, "coordinates")
        # Coordonnées: longitude,latitude,altitude (espace entre les points)
        coords_list = [f"{ctrl.x},{ctrl.y},{ctrl.z}" for ctrl in circuit.controls]
        coords.text = " ".join(coords_list)

        return pm

    def _to_kml_string(self, root: ET.Element) -> str:
        """Convertit l'arbre en string KML."""
        # Pretty print
        ET.indent(root, space="  ")

        # Ajouter la declaration KML
        kml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
        kml_str += ET.tostring(root, encoding="unicode")

        return kml_str


# =============================================
# Convertisseur vers notre format
# =============================================
def export_circuit_to_kml(
    circuit_data: Dict,
    controls: List[Dict],
    color: str = "blue",
) -> str:
    """
    Convertit un circuit AItraceur en KML.

    Args:
        circuit_data: Données du circuit {name, ...}
        controls: Liste des contrôles [{order, x, y, description}, ...]
        color: Couleur du circuit (blue, red, green, yellow, orange, purple)

    Returns:
        Contenu KML
    """
    exporter = KMLExporter()

    # Convertir les contrôles
    kml_controls = []
    for ctrl in controls:
        kml_control = KMLControl(
            number=ctrl.get("order", 1),
            name=ctrl.get("description", f"Poste {ctrl.get('order', 1)}"),
            x=ctrl.get("x", 0),
            y=ctrl.get("y", 0),
            z=ctrl.get("z", 0),
            description=ctrl.get("description", ""),
        )
        kml_controls.append(kml_control)

    # Couleur
    color_hex = KMLExporter.COLORS.get(color, "ff0000ff")

    # Créer le circuit
    circuit = KMLCircuit(
        name=circuit_data.get("name", "Circuit"),
        controls=kml_controls,
        color=color_hex,
    )

    exporter.add_circuit(circuit)

    return exporter.export_kml()


def export_circuit_to_kmz(
    circuit_data: Dict,
    controls: List[Dict],
    color: str = "blue",
    map_image: bytes = None,
) -> bytes:
    """
    Convertit un circuit AItraceur en KMZ.

    Args:
        circuit_data: Données du circuit {name, ...}
        controls: Liste des contrôles [{order, x, y, description}, ...]
        color: Couleur du circuit
        map_image: Image de la carte à inclure (optionnel)

    Returns:
        Contenu KMZ (bytes)
    """
    exporter = KMLExporter()

    # Convertir les contrôles
    kml_controls = []
    for ctrl in controls:
        kml_control = KMLControl(
            number=ctrl.get("order", 1),
            name=ctrl.get("description", f"Poste {ctrl.get('order', 1)}"),
            x=ctrl.get("x", 0),
            y=ctrl.get("y", 0),
            z=ctrl.get("z", 0),
            description=ctrl.get("description", ""),
        )
        kml_controls.append(kml_control)

    # Couleur
    color_hex = KMLExporter.COLORS.get(color, "ff0000ff")

    # Créer le circuit
    circuit = KMLCircuit(
        name=circuit_data.get("name", "Circuit"),
        controls=kml_controls,
        color=color_hex,
    )

    exporter.add_circuit(circuit)

    return exporter.export_kmz(map_image=map_image)


def export_circuits_to_kmz(
    circuits: List[Dict],
    colors: List[str] = None,
) -> bytes:
    """
    Exporte plusieurs circuits en un seul KMZ.

    Args:
        circuits: Liste de circuits [{name, controls: [...]}, ...]
        colors: Liste de couleurs (une par circuit)

    Returns:
        Contenu KMZ (bytes)
    """
    exporter = KMLExporter()

    # Couleurs par défaut
    if colors is None:
        colors = ["blue", "red", "green", "yellow", "orange", "purple"]

    for i, circuit_data in enumerate(circuits):
        controls = circuit_data.get("controls", [])
        color = colors[i % len(colors)]

        # Convertir les contrôles
        kml_controls = []
        for ctrl in controls:
            kml_control = KMLControl(
                number=ctrl.get("order", 1),
                name=ctrl.get("description", f"Poste {ctrl.get('order', 1)}"),
                x=ctrl.get("x", 0),
                y=ctrl.get("y", 0),
                z=ctrl.get("z", 0),
                description=ctrl.get("description", ""),
            )
            kml_controls.append(kml_control)

        # Couleur
        color_hex = KMLExporter.COLORS.get(color, "ff0000ff")

        # Créer le circuit
        circuit = KMLCircuit(
            name=circuit_data.get("name", f"Circuit {i + 1}"),
            controls=kml_controls,
            color=color_hex,
        )

        exporter.add_circuit(circuit)

    return exporter.export_kmz()
