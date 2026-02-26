# =============================================
# Importeur IOF XML
# Import de fichiers IOF XML 3.0
# =============================================

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


# =============================================
# Types de données
# =============================================
@dataclass
class IOFControl:
    """Un contrôle IOF."""

    number: int
    code: str
    x: float  # Easting ou Longitude
    y: float  # Northing ou Latitude
    description: str = ""


@dataclass
class IOFCourse:
    """Un circuit IOF."""

    course_id: str
    name: str
    length: int = 0  # mètres
    climb: int = 0  # mètres
    controls: List[IOFControl] = field(default_factory=list)


@dataclass
class IOFEvent:
    """Un événement IOF."""

    event_id: str
    name: str
    date: Optional[str] = None
    location: Optional[str] = None
    courses: List[IOFCourse] = field(default_factory=list)


@dataclass
class IOFImport:
    """Résultat de l'import IOF."""

    event: Optional[IOFEvent] = None
    status: str = "pending"
    error: str = ""


# =============================================
# Importeur IOF XML 3.0
# =============================================
class IOFImporter:
    """
    Importe des fichiers IOF XML 3.0.

    IOF (International Orienteering Federation) est le standard
    international pour les données de course d'orientation.
    """

    # Namespaces IOF
    NS = "http://www.orienteering.org/standard/IOF-data-3.0"
    XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

    def import_file(self, file_path: str) -> IOFImport:
        """
        Importe un fichier IOF XML.

        Args:
            file_path: Chemin vers le fichier XML

        Returns:
            IOFImport avec l'événement
        """
        result = IOFImport(status="processing")

        try:
            # Parser le XML
            tree = ET.parse(file_path)
            root = tree.getroot()

            # Détecter le type de document
            if "IOFEventList" in root.tag:
                result.event = self._parse_event_list(root)
            elif "CourseData" in root.tag:
                result.event = self._parse_course_data(root)
            else:
                # Essayer de parser comme IOF générique
                result.event = self._parse_generic(root)

            result.status = "ok"

        except ET.ParseError as e:
            result.status = "error"
            result.error = f"Erreur parsing XML: {e}"
        except Exception as e:
            result.status = "error"
            result.error = str(e)

        return result

    def import_xml_string(self, xml_string: str) -> IOFImport:
        """
        Importe depuis une chaîne XML.

        Args:
            xml_string: Contenu XML

        Returns:
            IOFImport avec l'événement
        """
        result = IOFImport(status="processing")

        try:
            root = ET.fromstring(xml_string)

            # Détecter le type
            if "IOFEventList" in root.tag:
                result.event = self._parse_event_list(root)
            elif "CourseData" in root.tag:
                result.event = self._parse_course_data(root)
            else:
                result.event = self._parse_generic(root)

            result.status = "ok"

        except ET.ParseError as e:
            result.status = "error"
            result.error = f"Erreur parsing XML: {e}"
        except Exception as e:
            result.status = "error"
            result.error = str(e)

        return result

    def _parse_event_list(self, root: ET.Element) -> IOFEvent:
        """Parse une liste d'événements IOF."""
        # Namespace
        ns = {"iof": self.NS}

        # Chercher Event
        event_elem = root.find(".//iof:Event", ns)
        if not event_elem:
            event_elem = root.find(".//Event")

        if not event_elem:
            return IOFEvent(event_id="unknown", name="Import IOF")

        # Extraire les infos
        event_id = event_elem.findtext("iof:Id", "0", ns) or event_elem.findtext(
            "Id", "0"
        )
        name = event_elem.findtext(
            "iof:Name", "Circuit import", ns
        ) or event_elem.findtext("Name", "Circuit import")
        date = event_elem.findtext("iof:Date", "", ns) or event_elem.findtext(
            "Date", ""
        )

        event = IOFEvent(
            event_id=event_id,
            name=name,
            date=date,
        )

        # Chercher les courses
        courses = event_elem.findall(".//iof:Course", ns)
        if not courses:
            courses = event_elem.findall(".//Course")

        for course_elem in courses:
            course = self._parse_course(course_elem, ns)
            if course:
                event.courses.append(course)

        return event

    def _parse_course_data(self, root: ET.Element) -> IOFEvent:
        """Parse un document CourseData IOF."""
        ns = {"iof": self.NS}

        event = IOFEvent(event_id="import", name="Import CourseData")

        # Chercher les courses
        courses = root.findall(".//iof:Course", ns)
        if not courses:
            courses = root.findall(".//Course")

        for course_elem in courses:
            course = self._parse_course(course_elem, ns)
            if course:
                event.courses.append(course)

        return event

    def _parse_generic(self, root: ET.Element) -> IOFEvent:
        """Parse un document IOF générique."""
        # Essayer de trouver des courses n'importe où
        ns = {"iof": self.NS}

        event = IOFEvent(event_id="import", name="Import IOF")

        # Chercher tous les éléments Course
        all_courses = root.findall(".//iof:Course", ns)
        if not all_courses:
            all_courses = root.findall(".//Course")

        for course_elem in all_courses:
            course = self._parse_course(course_elem, ns)
            if course:
                event.courses.append(course)

        return event

    def _parse_course(self, course_elem: ET.Element, ns: Dict) -> Optional[IOFCourse]:
        """Parse un élément Course."""
        # ID
        course_id = course_elem.findtext(
            "iof:CourseId", "0", ns
        ) or course_elem.findtext("CourseId", "0")

        # Name
        name = course_elem.findtext("iof:Name", "Circuit", ns) or course_elem.findtext(
            "Name", "Circuit"
        )

        # Length
        length_text = course_elem.findtext(
            "iof:Length", "0", ns
        ) or course_elem.findtext("Length", "0")
        try:
            length = int(length_text)
        except ValueError:
            length = 0

        # Climb
        climb_text = course_elem.findtext("iof:Climb", "0", ns) or course_elem.findtext(
            "Climb", "0"
        )
        try:
            climb = int(climb_text)
        except ValueError:
            climb = 0

        course = IOFCourse(
            course_id=course_id,
            name=name,
            length=length,
            climb=climb,
        )

        # Chercher les contrôles
        controls = course_elem.findall(".//iof:Control", ns)
        if not controls:
            controls = course_elem.findall(".//Control")

        for ctrl_elem in controls:
            control = self._parse_control(ctrl_elem, ns)
            if control:
                course.controls.append(control)

        return course

    def _parse_control(self, ctrl_elem: ET.Element, ns: Dict) -> Optional[IOFControl]:
        """Parse un élément Control."""
        # ID / number
        ctrl_id_text = ctrl_elem.findtext(
            "iof:ControlId", "0", ns
        ) or ctrl_elem.findtext("ControlId", "0")
        try:
            ctrl_number = int(ctrl_id_text)
        except ValueError:
            ctrl_number = 0

        # Code
        code = ctrl_elem.findtext("iof:ControlCode", "", ns) or ctrl_elem.findtext(
            "ControlCode", ""
        )

        # Position
        pos_elem = ctrl_elem.find(".//iof:Position", ns) or ctrl_elem.find(
            ".//Position"
        )

        x = 0.0
        y = 0.0

        if pos_elem is not None:
            # Longitude / Easting
            lon_text = pos_elem.findtext("iof:Longitude", "0", ns) or pos_elem.findtext(
                "Longitude",
                pos_elem.findtext("iof:Easting", "0", ns)
                or pos_elem.findtext("Easting", "0"),
            )
            # Latitude / Northing
            lat_text = pos_elem.findtext("iof:Latitude", "0", ns) or pos_elem.findtext(
                "Latitude",
                pos_elem.findtext("iof:Northing", "0", ns)
                or pos_elem.findtext("Northing", "0"),
            )

            try:
                x = float(lon_text) if lon_text else 0.0
            except ValueError:
                x = 0.0

            try:
                y = float(lat_text) if lat_text else 0.0
            except ValueError:
                y = 0.0

        return IOFControl(
            number=ctrl_number,
            code=code or f"S{ctrl_number}",
            x=x,
            y=y,
        )


# =============================================
# Convertisseur vers notre format
# =============================================
def convert_iof_to_circuits(iof_import: IOFImport) -> List[Dict]:
    """
    Convertit le résultat IOF en circuits AItraceur.

    Args:
        iof_import: Résultat de l'import

    Returns:
        Liste de circuits au format AItraceur
    """
    circuits = []

    if not iof_import.event:
        return circuits

    for iof_course in iof_import.event.courses:
        circuit = {
            "name": iof_course.name,
            "length_meters": iof_course.length,
            "climb_meters": iof_course.climb,
            "controls": [],
        }

        # Convertir les contrôles
        for ctrl in iof_course.controls:
            control = {
                "order": ctrl.number,
                "x": ctrl.x,
                "y": ctrl.y,
                "code": ctrl.code,
                "description": ctrl.description or f"Poste {ctrl.number}",
            }
            circuit["controls"].append(control)

        if circuit["controls"]:
            circuits.append(circuit)

    return circuits


# =============================================
# Fonctions utilitaires
# =============================================
def import_iof_file(file_path: str) -> IOFImport:
    """Importe un fichier IOF XML."""
    importer = IOFImporter()
    return importer.import_file(file_path)


def import_iof_string(xml_string: str) -> IOFImport:
    """Importe depuis une chaîne XML IOF."""
    importer = IOFImporter()
    return importer.import_xml_string(xml_string)
