"""
Pipeline Eventor → ML features (sprint urbain).

Flux :
  1. Fetch liste d'événements Eventor (filtre sprint)
  2. Pour chaque événement : fetch CourseData IOF XML
  3. Extraire positions WGS84 des contrôles
  4. Calculer features terrain depuis OSM (réutilise gpx_feature_extractor)
  5. Stocker en DB (source_format="xml_osm")

Filtrage sprint :
  - Nom de l'événement contient "sprint" (insensible à la casse)
  - OU classe détectée dans la liste des catégories sprint FFCO/IOF
  - Événements sans positions WGS84 sont ignorés (données insuffisantes pour OSM)
"""

import hashlib
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from .eventor_client import EventorClient

# Namespaces IOF XML 3.0
_NS = {
    "iof3": "https://www.orienteering.org/datastandard/3.0",
    "iof3b": "http://www.orienteering.org/datastandard/3.0",
    "iof2": "http://www.orienteering.org/datastandard/2.0.3",
}

# Mots-clés identifiant un sprint dans le nom de l'événement
_SPRINT_KEYWORDS = {"sprint", "sprinten", "sprintti", "city", "urban", "natt"}

# Catégories typiquement courues en sprint
_SPRINT_CLASSES = {
    "H21E", "D21E", "H20", "D20", "H18", "D18",
    "H16", "D16", "H14", "D14", "H12", "D12",
    "HOPEN", "DOPEN", "OPEN", "ELITE",
}


# ---------------------------------------------------------------------------
# Parsing IOF XML
# ---------------------------------------------------------------------------

def _find_ns(elem: ET.Element, tag: str) -> Optional[ET.Element]:
    """Cherche un élément avec ou sans namespace IOF."""
    for prefix, ns in _NS.items():
        found = elem.find(f"{{{ns}}}{tag}")
        if found is not None:
            return found
    return elem.find(tag)  # sans namespace


def _findall_ns(elem: ET.Element, tag: str) -> List[ET.Element]:
    results = []
    for prefix, ns in _NS.items():
        results.extend(elem.findall(f".//{{{ns}}}{tag}"))
    if not results:
        results = elem.findall(f".//{tag}")
    # Déduplique (peut apparaître sous plusieurs namespaces)
    seen = set()
    unique = []
    for r in results:
        key = (r.tag, id(r))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _get_text(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    return (elem.text or "").strip()


def parse_iof_course_data(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse un IOF XML 3.0 CourseData ou ResultList.

    Returns une liste de circuits :
    [
        {
            "name": str,           # Nom du circuit / classe
            "length_m": float,     # Longueur déclarée (ou None)
            "climb_m": float,      # Dénivelé (ou None)
            "controls": [(lng, lat), ...]  # Positions WGS84 ordonnées
        },
        ...
    ]
    Seuls les circuits avec TOUTES les positions WGS84 sont retournés.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"XML invalide : {e}")

    # -- Construire index : control_id → (lng, lat)
    positions: Dict[str, Tuple[float, float]] = {}
    for ctrl_elem in _findall_ns(root, "Control"):
        ctrl_id_elem = _find_ns(ctrl_elem, "Id")
        pos_elem = _find_ns(ctrl_elem, "Position")
        if ctrl_id_elem is None or pos_elem is None:
            continue
        try:
            lat = float(pos_elem.get("lat", pos_elem.get("Lat", "")))
            lng = float(pos_elem.get("lng", pos_elem.get("Lng", pos_elem.get("lon", pos_elem.get("Lon", "")))))
            positions[_get_text(ctrl_id_elem)] = (lng, lat)
        except (ValueError, TypeError):
            continue

    if not positions:
        return []

    # -- Parser les courses
    circuits = []
    for course_elem in _findall_ns(root, "Course"):
        name_elem = _find_ns(course_elem, "Name")
        name = _get_text(name_elem) or "Unknown"

        length_m = None
        length_elem = _find_ns(course_elem, "Length")
        if length_elem is not None and length_elem.text:
            try:
                length_m = float(length_elem.text.strip())
            except ValueError:
                pass

        climb_m = None
        climb_elem = _find_ns(course_elem, "Climb")
        if climb_elem is not None and climb_elem.text:
            try:
                climb_m = float(climb_elem.text.strip())
            except ValueError:
                pass

        # Extraire les contrôles dans l'ordre
        ordered_ids: List[str] = []
        for cc_elem in _findall_ns(course_elem, "CourseControl"):
            ctrl_ref = _find_ns(cc_elem, "Control")
            if ctrl_ref is not None:
                ordered_ids.append(_get_text(ctrl_ref))

        if len(ordered_ids) < 3:
            continue

        # Résoudre les positions
        ctrl_positions = []
        missing = False
        for cid in ordered_ids:
            pos = positions.get(cid)
            if pos is None:
                missing = True
                break
            ctrl_positions.append(pos)

        if missing or len(ctrl_positions) < 3:
            continue

        circuits.append({
            "name": name,
            "length_m": length_m,
            "climb_m": climb_m,
            "controls": ctrl_positions,
        })

    return circuits


def parse_iof_events(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse une liste d'événements Eventor (EventList XML).

    Returns:
        [{"id": int, "name": str, "date": str, "discipline": str}, ...]
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    events = []
    for ev in _findall_ns(root, "Event"):
        eid_elem = _find_ns(ev, "EventId")
        name_elem = _find_ns(ev, "Name")
        date_elem = _find_ns(ev, "StartDate")
        if date_elem is not None:
            date_val = _find_ns(date_elem, "Date")
            date_str = _get_text(date_val) if date_val is not None else _get_text(date_elem)
        else:
            date_str = ""

        if eid_elem is None or name_elem is None:
            continue

        events.append({
            "id": int(_get_text(eid_elem)),
            "name": _get_text(name_elem),
            "date": date_str,
        })

    return events


def _is_sprint_event(event_name: str) -> bool:
    """Heuristique : l'événement est-il un sprint ?"""
    name_lower = event_name.lower()
    return any(kw in name_lower for kw in _SPRINT_KEYWORDS)


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

class EventorImporter:
    """
    Orchestre le pipeline Eventor → features ML.

    Usage:
        importer = EventorImporter(client, db)
        stats = importer.ingest(from_date="2024-01-01", to_date="2024-12-31")
    """

    def __init__(self, client: EventorClient, db=None):
        self.client = client
        self.db = db  # Session SQLAlchemy (None = dry run)

    def ingest(
        self,
        from_date: str,
        to_date: str,
        sprint_only: bool = True,
        dry_run: bool = False,
        verbose: bool = True,
    ) -> Dict[str, int]:
        """
        Ingère tous les événements Eventor dans la plage de dates.

        Args:
            from_date: "YYYY-MM-DD"
            to_date:   "YYYY-MM-DD"
            sprint_only: Si True, ignore les événements non-sprint
            dry_run: Si True, parse mais ne stocke pas en DB
            verbose: Affiche les logs

        Returns:
            {"fetched": n, "sprint": n, "stored": n, "skipped": n, "errors": n}
        """
        from ..learning.gpx_feature_extractor import _compute_osm_terrain, _circuit_quality_score, _grade_td

        stats = {"fetched": 0, "sprint": 0, "stored": 0, "skipped": 0, "errors": 0}

        # 1. Fetch liste des événements
        if verbose:
            print(f"[Eventor] Fetching events {from_date} → {to_date} ...")
        try:
            events_xml = self.client.get_events(from_date, to_date)
            events = parse_iof_events(events_xml)
        except Exception as e:
            print(f"[Eventor] Erreur fetch events : {e}")
            return stats

        stats["fetched"] = len(events)
        if verbose:
            print(f"[Eventor] {len(events)} événements trouvés")

        # 2. Filtrer les sprints
        if sprint_only:
            events = [e for e in events if _is_sprint_event(e["name"])]
        stats["sprint"] = len(events)
        if verbose:
            print(f"[Eventor] {len(events)} événements sprint retenus")

        # 3. Pour chaque événement, fetch + parse + stocker
        for event in events:
            eid = event["id"]
            ename = event["name"]
            edate = event["date"]

            if verbose:
                print(f"\n→ [{eid}] {ename} ({edate})")

            try:
                course_xml = self.client.get_course_data(eid)
            except Exception as e:
                if verbose:
                    print(f"  ✗ Erreur fetch courseData : {e}")
                stats["errors"] += 1
                continue

            try:
                circuits = parse_iof_course_data(course_xml)
            except Exception as e:
                if verbose:
                    print(f"  ✗ Erreur parse IOF XML : {e}")
                stats["errors"] += 1
                continue

            if not circuits:
                if verbose:
                    print(f"  ~ Aucun circuit avec positions WGS84")
                stats["skipped"] += 1
                continue

            for circuit in circuits:
                controls = circuit["controls"]  # [(lng, lat), ...]
                if len(controls) < 3:
                    continue

                # Hash de déduplication : event_id + nom circuit + positions
                hash_input = f"{eid}|{circuit['name']}|{controls[0]}|{controls[-1]}"
                content_hash = hashlib.sha256(hash_input.encode()).hexdigest()

                if self.db and not dry_run:
                    from src.models.contribution import Contribution, ControlFeature
                    existing = self.db.query(Contribution).filter(
                        Contribution.xml_hash == content_hash
                    ).first()
                    if existing:
                        if verbose:
                            print(f"  ~ DOUBLON : {circuit['name']}")
                        stats["skipped"] += 1
                        continue

                # Features terrain OSM
                try:
                    terrain_features = _compute_osm_terrain(controls)
                except Exception as e:
                    if verbose:
                        print(f"  ! OSM error pour {circuit['name']} : {e}")
                    terrain_features = [{} for _ in controls]

                # Features géométriques
                from src.services.learning.feature_extractor import ContributionFeatures, ControlFeatureVector, _haversine_m
                legs = [_haversine_m(controls[i], controls[i + 1]) for i in range(len(controls) - 1)]
                length_m = circuit["length_m"] or (sum(legs) if legs else None)
                td = _grade_td(legs)
                quality = _circuit_quality_score(controls)

                # Bearing changes
                from src.services.learning.gpx_feature_extractor import _bearing, _bearing_change
                bearings = [_bearing(controls[i], controls[i + 1]) for i in range(len(controls) - 1)]

                control_features = []
                for i, (lng, lat) in enumerate(controls):
                    leg_dist = legs[i] if i < len(legs) else 0.0
                    bearing_chg = 0.0
                    if i > 0 and i < len(bearings):
                        bearing_chg = _bearing_change(bearings[i - 1], bearings[i])
                    pos_ratio = i / max(len(controls) - 1, 1)
                    terrain = terrain_features[i] if i < len(terrain_features) else {}

                    control_features.append(ControlFeatureVector(
                        leg_distance_m=round(leg_dist, 1),
                        leg_bearing_change=round(bearing_chg, 1),
                        control_position_ratio=round(pos_ratio, 3),
                        td_grade=td,
                        pd_grade=None,
                        terrain_symbol_density=terrain.get("terrain_symbol_density"),
                        nearest_path_dist_m=terrain.get("nearest_path_dist_m"),
                        control_feature_type=terrain.get("control_feature_type"),
                        attractiveness_score=terrain.get("attractiveness_score"),
                        quality_score=round(quality, 3),
                    ))

                if verbose:
                    n = len(controls)
                    dist = f"{round(length_m)}m" if length_m else "?"
                    print(f"  ✓ {circuit['name']} — {n} postes, {dist}, TD{td}, qualité={quality:.2f}")

                if not dry_run and self.db:
                    from src.models.contribution import Contribution, ControlFeature
                    contrib = Contribution(
                        xml_hash=content_hash,
                        source_format="xml_osm",
                        circuit_type="sprint",
                        map_type="urban",
                        ffco_category=None,
                        td_grade=td,
                        pd_grade=None,
                        n_controls=len(controls),
                        length_m=round(length_m) if length_m else None,
                        climb_m=circuit.get("climb_m"),
                        consent_educational=True,  # données publiques Eventor
                    )
                    self.db.add(contrib)
                    self.db.flush()

                    for fv in control_features:
                        self.db.add(ControlFeature(
                            contribution_id=contrib.id,
                            leg_distance_m=fv.leg_distance_m,
                            leg_bearing_change=fv.leg_bearing_change,
                            control_position_ratio=fv.control_position_ratio,
                            td_grade=fv.td_grade,
                            pd_grade=fv.pd_grade,
                            terrain_symbol_density=fv.terrain_symbol_density,
                            nearest_path_dist_m=fv.nearest_path_dist_m,
                            control_feature_type=fv.control_feature_type,
                            attractiveness_score=fv.attractiveness_score,
                            quality_score=fv.quality_score,
                        ))

                    self.db.commit()
                    stats["stored"] += 1
                elif dry_run:
                    stats["stored"] += 1  # comptabilisé même en dry run

        return stats
