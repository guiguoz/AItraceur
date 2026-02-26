# =============================================
# Importeur IOF XML 3.0 Course Data
# =============================================

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from pathlib import Path


@dataclass
class XMLControl:
    """Poste lu depuis XML."""

    id: str  # "31", "S1", "F1"
    control_type: str  # "Start", "Control", "Finish"
    lat: float  # WGS84 latitude
    lng: float  # WGS84 longitude
    map_x: Optional[float] = None  # Position sur la carte (mm)
    map_y: Optional[float] = None


@dataclass
class XMLCourse:
    """Circuit lu depuis XML."""

    name: str
    length_meters: Optional[int] = None
    climb_meters: Optional[int] = None
    controls: List[str] = field(default_factory=list)  # Liste des IDs de contrôles


@dataclass
class XMLRaceData:
    """Données complètes du fichier XML."""

    controls: Dict[str, XMLControl] = field(default_factory=dict)  # Map id -> control
    courses: List[XMLCourse] = field(default_factory=list)


class IOFXMLImporter:
    """
    Importeur pour fichiers IOF XML 3.0 Course Data.
    Format standard utilisé par OCAD pour exporter les circuits.
    """

    # Namespaces IOF
    NS = {
        "iof": "http://www.orienteering.org/datastandard/3.0",
    }

    def parse(self, file_path: Path) -> XMLRaceData:
        """Parse un fichier XML IOF."""
        tree = ET.parse(file_path)
        root = tree.getroot()

        return self._parse_element(root)

    def parse_bytes(self, data: bytes, filename: str) -> XMLRaceData:
        """Parse des données XML."""
        root = ET.fromstring(data)
        return self._parse_element(root)

    def _parse_element(self, root: ET.Element) -> XMLRaceData:
        """Parse l'élément root du XML."""
        race_data = XMLRaceData()

        # Find RaceCourseData element
        race_course_data = root.find(".//iof:RaceCourseData", self.NS)
        if race_course_data is None:
            race_course_data = root  # Try without namespace

        # Parse all Control elements
        for control_elem in race_course_data.findall(".//iof:Control", self.NS):
            control = self._parse_control(control_elem)
            if control:
                race_data.controls[control.id] = control

        # Also try without namespace
        if not race_data.controls:
            for control_elem in race_course_data.findall(".//Control"):
                control = self._parse_control(control_elem)
                if control:
                    race_data.controls[control.id] = control

        # Parse Course elements
        for course_elem in race_course_data.findall(".//iof:Course", self.NS):
            course = self._parse_course(course_elem)
            if course:
                race_data.courses.append(course)

        # Also try without namespace
        if not race_data.courses:
            for course_elem in race_course_data.findall(".//Course"):
                course = self._parse_course(course_elem)
                if course:
                    race_data.courses.append(course)

        return race_data

    def _parse_control(self, elem: ET.Element) -> Optional[XMLControl]:
        """Parse un élément Control."""
        # Get control type
        control_type = elem.get("type", "Control")

        # Get ID
        id_elem = elem.find(".//iof:Id", self.NS)
        if id_elem is None:
            id_elem = elem.find(".//Id", {})
        if id_elem is None or not id_elem.text:
            return None
        control_id = id_elem.text.strip()

        # Get GPS position
        position = elem.find(".//iof:Position", self.NS)
        if position is None:
            position = elem.find(".//Position", {})

        lat = None
        lng = None
        if position is not None:
            lat_str = position.get("lat")
            lng_str = position.get("lng")
            if lat_str and lng_str:
                lat = float(lat_str)
                lng = float(lng_str)

        if lat is None or lng is None:
            return None

        # Get map position (optional)
        map_pos = elem.find(".//iof:MapPosition", self.NS)
        if map_pos is None:
            map_pos = elem.find(".//MapPosition", {})

        map_x = None
        map_y = None
        if map_pos is not None:
            map_x_str = map_pos.get("x")
            map_y_str = map_pos.get("y")
            if map_x_str and map_y_str:
                map_x = float(map_x_str)
                map_y = float(map_y_str)

        return XMLControl(
            id=control_id,
            control_type=control_type,
            lat=lat,
            lng=lng,
            map_x=map_x,
            map_y=map_y,
        )

    def _parse_course(self, elem: ET.Element) -> Optional[XMLCourse]:
        """Parse un élément Course."""
        # Get name
        name_elem = elem.find(".//iof:Name", self.NS)
        if name_elem is None:
            name_elem = elem.find(".//Name", {})
        if name_elem is None or not name_elem.text:
            return None
        course_name = name_elem.text.strip()

        # Get length
        length = None
        length_elem = elem.find(".//iof:Length", self.NS)
        if length_elem is None:
            length_elem = elem.find(".//Length", {})
        if length_elem is not None and length_elem.text:
            length = int(length_elem.text)

        # Get climb
        climb = None
        climb_elem = elem.find(".//iof:Climb", self.NS)
        if climb_elem is None:
            climb_elem = elem.find(".//Climb", {})
        if climb_elem is not None and climb_elem.text:
            climb = int(climb_elem.text)

        # Get controls in order
        controls = []
        for cc_elem in elem.findall(".//iof:CourseControl", self.NS):
            control_elem = cc_elem.find(".//iof:Control", self.NS)
            if control_elem is None:
                control_elem = cc_elem.find(".//Control", {})
            if control_elem is not None and control_elem.text:
                controls.append(control_elem.text.strip())

        # Also try without namespace
        if not controls:
            for cc_elem in elem.findall(".//CourseControl"):
                control_elem = cc_elem.find(".//Control")
                if control_elem is not None and control_elem.text:
                    controls.append(control_elem.text.strip())

        return XMLCourse(
            name=course_name,
            length_meters=length,
            climb_meters=climb,
            controls=controls,
        )


def parse_iof_xml(file_path: Path) -> XMLRaceData:
    """Fonction utilitaire pour parser un fichier IOF XML."""
    importer = IOFXMLImporter()
    return importer.parse(file_path)


def parse_iof_xml_bytes(data: bytes) -> XMLRaceData:
    """Fonction utilitaire pour parser du XML IOF depuis bytes."""
    importer = IOFXMLImporter()
    return importer.parse_bytes(data, "unknown.xml")
