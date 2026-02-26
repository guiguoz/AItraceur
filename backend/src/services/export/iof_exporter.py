# =============================================
# Exporteur IOF XML - IOF Data Standard 3.0
# Sprint 9: Exports & Polish
# =============================================

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


# =============================================
# Types de données
# =============================================
@dataclass
class IOFControl:
    """Un contrôle/poteau IOF."""

    number: int
    code: str
    x: float  # Longitude (WGS84)
    y: float  # Latitude (WGS84)
    description: str = ""


@dataclass
class IOFCourse:
    """Un circuit IOF."""

    name: str
    course_id: str
    length: int  # en mètres
    climb: int  # en mètres
    controls: List[IOFControl]
    controls_count: int
    forbidden_area: Optional[int] = None  # en m²


# =============================================
# Exporteur IOF XML 3.0 (CourseData)
# =============================================
class IOFExporter:
    """
    Exporte les circuits au format IOF XML 3.0 CourseData.

    Conforme au IOF Data Standard 3.0:
    https://github.com/international-orienteering-federation/datastandard-v3
    """

    NS = "http://www.orienteering.org/datastandard/3.0"

    def export_courses(
        self,
        courses: List[IOFCourse],
        event_name: str = "AItraceur Event",
        event_date: str = None,
    ) -> str:
        """
        Exporte les circuits au format IOF XML 3.0 CourseData.

        Args:
            courses: Liste des circuits
            event_name: Nom de l'événement
            event_date: Date de l'événement (YYYY-MM-DD)

        Returns:
            XML string conforme IOF 3.0
        """
        root = ET.Element("CourseData")
        root.set("xmlns", self.NS)
        root.set("iofVersion", "3.0")
        root.set("createTime", datetime.now().astimezone().isoformat())
        root.set("creator", "AItraceur")

        # Event
        event = ET.SubElement(root, "Event")
        name_elem = ET.SubElement(event, "Name")
        name_elem.text = event_name
        if event_date:
            start_time = ET.SubElement(event, "StartTime")
            date_elem = ET.SubElement(start_time, "Date")
            date_elem.text = event_date

        # RaceCourseData
        race = ET.SubElement(root, "RaceCourseData")

        # Collect all unique controls across all courses
        seen_controls: Dict[str, IOFControl] = {}
        for course in courses:
            for ctrl in course.controls:
                ctrl_id = self._control_id(ctrl)
                if ctrl_id not in seen_controls:
                    seen_controls[ctrl_id] = ctrl

        # Write Control definitions first
        for ctrl_id, ctrl in seen_controls.items():
            control_elem = ET.SubElement(race, "Control")
            id_elem = ET.SubElement(control_elem, "Id")
            id_elem.text = ctrl_id
            pos = ET.SubElement(control_elem, "Position")
            pos.set("lat", str(ctrl.y))  # y = latitude
            pos.set("lng", str(ctrl.x))  # x = longitude

        # Write Course definitions
        for course in courses:
            self._create_course_element(race, course)

        return self._to_xml_string(root)

    def _control_id(self, ctrl: IOFControl) -> str:
        """Retourne l'identifiant du contrôle pour le XML."""
        return ctrl.code if ctrl.code else str(ctrl.number)

    def _create_course_element(
        self, parent: ET.Element, course: IOFCourse
    ) -> None:
        """Crée un élément Course dans le parent RaceCourseData."""
        course_elem = ET.SubElement(parent, "Course")

        name = ET.SubElement(course_elem, "Name")
        name.text = course.name

        length = ET.SubElement(course_elem, "Length")
        length.text = str(course.length)

        climb = ET.SubElement(course_elem, "Climb")
        climb.text = str(course.climb)

        # CourseControl elements
        for i, ctrl in enumerate(course.controls):
            is_first = i == 0
            is_last = i == len(course.controls) - 1

            if is_first:
                ctrl_type = "Start"
            elif is_last:
                ctrl_type = "Finish"
            else:
                ctrl_type = "Control"

            cc = ET.SubElement(course_elem, "CourseControl")
            cc.set("type", ctrl_type)

            control_ref = ET.SubElement(cc, "Control")
            control_ref.text = self._control_id(ctrl)

    def _to_xml_string(self, root: ET.Element) -> str:
        """Convertit l'arbre en string XML avec indentation 2 espaces."""
        ET.indent(root, space="  ")
        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_str += ET.tostring(root, encoding="unicode")
        return xml_str


# =============================================
# Convertisseur depuis notre format
# =============================================
def export_circuit_to_iof(
    circuit_data: Dict,
    controls: List[Dict],
) -> str:
    """
    Convertit un circuit AItraceur en IOF XML 3.0 CourseData.

    Args:
        circuit_data: Données du circuit {name, length_meters, climb_meters, ...}
        controls: Liste des contrôles [{order, x, y, code, description}, ...]

    Returns:
        XML IOF 3.0
    """
    exporter = IOFExporter()

    iof_controls = []
    for ctrl in controls:
        iof_control = IOFControl(
            number=ctrl.get("order", 1),
            code=ctrl.get("symbol_code", f"S{ctrl.get('order', 1)}"),
            x=ctrl.get("x", 0),
            y=ctrl.get("y", 0),
            description=ctrl.get("description", ""),
        )
        iof_controls.append(iof_control)

    iof_course = IOFCourse(
        name=circuit_data.get("name", "Circuit"),
        course_id=str(circuit_data.get("id", "1")),
        length=int(circuit_data.get("length_meters", 0)),
        climb=int(circuit_data.get("climb_meters", 0)),
        controls=iof_controls,
        controls_count=len(controls),
    )

    return exporter.export_courses(
        [iof_course], event_name=circuit_data.get("name", "Event")
    )
