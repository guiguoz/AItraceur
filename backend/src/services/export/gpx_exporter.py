# =============================================
# Exporteur GPX
# Sprint 9: Exports & Polish
# =============================================

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


# =============================================
# Exporteur GPX
# =============================================
class GPXExporter:
    """
    Exporte les circuits au format GPX.

    GPX est un format standard pour les données GPS.
    Utile pour:
    - Importer dans les applications de navigation
    - Visualiser sur des cartes en ligne
    - Trace GPS théorique du circuit
    """

    # Namespace GPX
    GPX_NS = "http://www.topografix.com/GPX/1/1"
    XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

    def export_circuit(
        self,
        name: str,
        controls: List[Dict],
        description: str = "",
        author: str = "AItraceur",
    ) -> str:
        """
        Exporte un circuit en GPX.

        Args:
            name: Nom du circuit
            controls: Liste des contrôles [(x, y, order, code), ...]
            description: Description
            author: Auteur

        Returns:
            XML GPX string
        """
        # Créer la racine
        root = ET.Element("gpx")
        root.set("version", "1.1")
        root.set("creator", f"AItraceur - {author}")
        root.set("xmlns", self.GPX_NS)
        root.set("xmlns:xsi", self.XSI_NS)

        # Metadata
        metadata = ET.SubElement(root, "metadata")

        # Name
        name_elem = ET.SubElement(metadata, "name")
        name_elem.text = name

        # Description
        desc = ET.SubElement(metadata, "desc")
        desc.text = description or f"Circuit de course d'orientation - {name}"

        # Time
        time_elem = ET.SubElement(metadata, "time")
        time_elem.text = datetime.now().isoformat()

        # Extensions (données personnalisées)
        extensions = ET.SubElement(metadata, "extensions")

        # Ajouter les infos du circuit
        circuit_info = ET.SubElement(extensions, "circuit")
        circuit_info.set("xmlns", "http://aitraceur.com/gpx-extensions")

        total_length = ET.SubElement(circuit_info, "totalLength")
        total_length.text = str(self._calculate_length(controls))

        controls_count = ET.SubElement(circuit_info, "controlsCount")
        controls_count.text = str(len(controls))

        # Créer le parcours (waypoints reliés)
        route = ET.SubElement(root, "rte")

        route_name = ET.SubElement(route, "name")
        route_name.text = name

        # Ajouter chaque contrôle comme waypoint
        for ctrl in controls:
            rtept = ET.SubElement(route, "rtept")

            lat = ET.SubElement(rtept, "lat")
            lat.text = str(ctrl.get("y", 0))  # y = latitude

            lon = ET.SubElement(rtept, "lon")
            lon.text = str(ctrl.get("x", 0))  # x = longitude

            # Élévation (si disponible)
            if ctrl.get("elevation"):
                ele = ET.SubElement(rtept, "ele")
                ele.text = str(ctrl.get("elevation"))

            # Nom (numéro du contrôle)
            point_name = ET.SubElement(rtept, "name")
            point_name.text = f"CP{ctrl.get('order', '')}"

            # Description
            point_desc = ET.SubElement(rtept, "desc")
            point_desc.text = ctrl.get(
                "description", f"Contrôle {ctrl.get('order', '')}"
            )

            # Symbole
            sym = ET.SubElement(rtept, "sym")
            sym.text = "Flag"

            # Extensions pour le contrôle
            pt_extensions = ET.SubElement(rtept, "extensions")
            control_ext = ET.SubElement(pt_extensions, "control")

            ctrl_number = ET.SubElement(control_ext, "number")
            ctrl_number.text = str(ctrl.get("order", 0))

            ctrl_code = ET.SubElement(control_ext, "code")
            ctrl_code.text = str(ctrl.get("code", ""))

        # Créer aussi les points individuels (waypoints)
        for ctrl in controls:
            wpt = ET.SubElement(root, "wpt")

            lat = ET.SubElement(wpt, "lat")
            lat.text = str(ctrl.get("y", 0))

            lon = ET.SubElement(wpt, "lon")
            lon.text = str(ctrl.get("x", 0))

            if ctrl.get("elevation"):
                ele = ET.SubElement(wpt, "ele")
                ele.text = str(ctrl.get("elevation"))

            name_elem = ET.SubElement(wpt, "name")
            name_elem.text = f"CP{ctrl.get('order', '')}"

            desc = ET.SubElement(wpt, "desc")
            desc.text = ctrl.get("description", f"Contrôle {ctrl.get('order', '')}")

            sym = ET.SubElement(wpt, "sym")
            sym.text = "Flag"

        # Convertir en string
        return self._to_xml_string(root)

    def export_with_track(
        self,
        name: str,
        controls: List[Dict],
        route_points: List[tuple] = None,
    ) -> str:
        """
        Exporte avec une trace (track) en plus des waypoints.

        Args:
            name: Nom du circuit
            controls: Liste des contrôles
            route_points: Points de la route détaillée [(x, y, ele), ...]

        Returns:
            XML GPX string
        """
        # Reprendre la base
        gpx_content = self.export_circuit(name, controls)

        # Parser et ajouter le track
        root = ET.fromstring(gpx_content)

        # Créer le track
        trk = ET.SubElement(root, "trk")

        trk_name = ET.SubElement(trk, "name")
        trk_name.text = f"{name} - Route"

        # Segment
        trkseg = ET.SubElement(trk, "trkseg")

        # Ajouter les points de la route
        if route_points:
            for point in route_points:
                trkpt = ET.SubElement(trkseg, "trkpt")

                lat = ET.SubElement(trkpt, "lat")
                lat.text = str(point[1])  # y = lat

                lon = ET.SubElement(trkpt, "lon")
                lon.text = str(point[0])  # x = lon

                if len(point) > 2 and point[2]:
                    ele = ET.SubElement(trkpt, "ele")
                    ele.text = str(point[2])

        return self._to_xml_string(root)

    def export_track_only(
        self,
        name: str,
        points: List[tuple],
        description: str = "",
    ) -> str:
        """
        Exporte uniquement une trace (pour traces GPS).

        Args:
            name: Nom
            points: Points [(lon, lat, ele?, time?), ...]
            description: Description

        Returns:
            XML GPX string
        """
        root = ET.Element("gpx")
        root.set("version", "1.1")
        root.set("creator", "AItraceur")
        root.set("xmlns", self.GPX_NS)

        # Metadata
        metadata = ET.SubElement(root, "metadata")

        name_elem = ET.SubElement(metadata, "name")
        name_elem.text = name

        desc = ET.SubElement(metadata, "desc")
        desc.text = description

        time_elem = ET.SubElement(metadata, "time")
        time_elem.text = datetime.now().isoformat()

        # Track
        trk = ET.SubElement(root, "trk")

        trk_name = ET.SubElement(trk, "name")
        trk_name.text = name

        # Segment
        trkseg = ET.SubElement(trk, "trkseg")

        for point in points:
            trkpt = ET.SubElement(trkseg, "trkpt")

            lat = ET.SubElement(trkpt, "lat")
            lat.text = str(point[1])

            lon = ET.SubElement(trkpt, "lon")
            lon.text = str(point[0])

            if len(point) > 2 and point[2]:
                ele = ET.SubElement(trkpt, "ele")
                ele.text = str(point[2])

            if len(point) > 3 and point[3]:
                time = ET.SubElement(trkpt, "time")
                time.text = point[3]

        return self._to_xml_string(root)

    def _calculate_length(self, controls: List[Dict]) -> float:
        """Calcule la longueur totale."""
        import math

        total = 0
        for i in range(len(controls) - 1):
            dx = controls[i + 1].get("x", 0) - controls[i].get("x", 0)
            dy = controls[i + 1].get("y", 0) - controls[i].get("y", 0)
            total += math.sqrt(dx * dx + dy * dy)

        return total

    def _to_xml_string(self, root: ET.Element) -> str:
        """Convertit en string XML."""
        ET.indent(root, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )


# =============================================
# Fonctions utilitaires
# =============================================
def export_circuit_to_gpx(circuit_data: Dict, controls: List[Dict]) -> str:
    """Exporte un circuit AItraceur en GPX."""
    exporter = GPXExporter()

    return exporter.export_circuit(
        name=circuit_data.get("name", "Circuit"),
        controls=controls,
        description=f"Circuit {circuit_data.get('name', '')} - {circuit_data.get('category', '')}",
    )


def export_track_to_gpx(track_points: List[tuple], name: str = "Track") -> str:
    """Exporte une trace GPS en GPX."""
    exporter = GPXExporter()

    return exporter.export_track_only(name=name, points=track_points)
