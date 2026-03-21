"""
Pipeline Livelox → ML features (sprint urbain).

Flux :
  1. GET /events (filtres : date, pays, bbox) → liste événements sprint
  2. Pour chaque événement : GET /orienteering/courses/iofxml?includeControls=true
  3. Parser IOF XML → positions WGS84 des contrôles (réutilise eventor_importer)
  4. Calculer features terrain OSM (réutilise gpx_feature_extractor)
  5. Stocker en DB (source_format="livelox_osm")

Filtrage sprint :
  - Classe contient "sprint" dans son nom
  - OU longueur du circuit ≤ 4000m (heuristique sprint)
  - OU l'événement est tagué sprint dans Livelox

Déduplication : hash SHA256(eventId|courseName|firstControl|lastControl)
"""

import hashlib
from typing import Any, Dict, List, Optional

from .eventor_importer import parse_iof_course_data, _is_sprint_event
from .livelox_client import LiveloxClient

# Longueur max présumée pour un sprint (mètres)
_MAX_SPRINT_LENGTH_M = 5000

# Mots-clés sprint dans le nom du circuit/classe
_SPRINT_KEYWORDS = {"sprint", "sp", "city", "urban", "natt", "night"}


def _is_sprint_circuit(circuit: Dict[str, Any]) -> bool:
    """Heuristique : ce circuit est-il un sprint ?"""
    name_lower = circuit.get("name", "").lower()
    if any(kw in name_lower for kw in _SPRINT_KEYWORDS):
        return True
    length = circuit.get("length_m")
    if length and length <= _MAX_SPRINT_LENGTH_M:
        return True
    return False


class LiveloxImporter:
    """
    Orchestre le pipeline Livelox → features ML.

    Usage:
        client   = LiveloxClient(api_key="...")  # ou sans clé pour données publiques
        importer = LiveloxImporter(client, db)
        stats    = importer.ingest(from_dt="2025-01-01T00:00:00Z",
                                   to_dt="2025-12-31T23:59:59Z")
    """

    def __init__(self, client: LiveloxClient, db=None):
        self.client = client
        self.db = db

    def ingest_event(
        self,
        event_id: int,
        sprint_only: bool = True,
        dry_run: bool = False,
        verbose: bool = True,
    ) -> Dict[str, int]:
        """
        Ingère un événement Livelox spécifique par son ID.

        Returns: {"stored": n, "skipped": n, "errors": n}
        """
        stats = {"stored": 0, "skipped": 0, "errors": 0}

        if verbose:
            print(f"[Livelox] Fetching event {event_id} ...")

        try:
            course_xml = self.client.get_course_iofxml(event_id)
        except Exception as e:
            if verbose:
                print(f"  ✗ Erreur fetch courseData : {e}")
            stats["errors"] += 1
            return stats

        try:
            circuits = parse_iof_course_data(course_xml)
        except Exception as e:
            if verbose:
                print(f"  ✗ Erreur parse IOF XML : {e}")
            stats["errors"] += 1
            return stats

        if not circuits:
            if verbose:
                print(f"  ~ Aucun circuit avec positions WGS84")
            stats["skipped"] += 1
            return stats

        if sprint_only:
            circuits = [c for c in circuits if _is_sprint_circuit(c)]
            if not circuits:
                if verbose:
                    print(f"  ~ Aucun circuit sprint détecté")
                stats["skipped"] += 1
                return stats

        return self._store_circuits(circuits, event_id, dry_run, verbose, stats)

    def ingest(
        self,
        from_dt: str,
        to_dt: str,
        country_id: Optional[int] = None,
        south: Optional[float] = None,
        north: Optional[float] = None,
        west: Optional[float] = None,
        east: Optional[float] = None,
        sprint_only: bool = True,
        dry_run: bool = False,
        verbose: bool = True,
        max_events: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Ingère tous les événements Livelox dans la plage de dates.

        Args:
            from_dt / to_dt : "YYYY-MM-DDThh:mm:ssZ"
            country_id      : Filtre par pays (ex: 752=SE, 578=NO, 250=FR, 276=DE)
            south/north/west/east : Bbox géographique (optionnel)
            sprint_only     : Ignorer les non-sprints
            dry_run         : Parser sans stocker
            max_events      : Limite (utile pour test)

        Returns:
            {"fetched": n, "sprint": n, "stored": n, "skipped": n, "errors": n}
        """
        stats = {"fetched": 0, "sprint": 0, "stored": 0, "skipped": 0, "errors": 0}

        if verbose:
            print(f"[Livelox] Fetching events {from_dt} → {to_dt} ...")

        # Paginer si nécessaire
        page = 1
        page_size = 50
        all_events = []

        while True:
            try:
                data = self.client.get_events(
                    from_dt=from_dt,
                    to_dt=to_dt,
                    country_id=country_id,
                    south=south,
                    north=north,
                    west=west,
                    east=east,
                    only_valid=True,
                    include_classes=True,
                    page=page,
                    page_size=page_size,
                )
            except Exception as e:
                print(f"[Livelox] Erreur fetch events page {page} : {e}")
                break

            events_page = data if isinstance(data, list) else data.get("events", data.get("data", []))
            if not events_page:
                break

            all_events.extend(events_page)
            if len(events_page) < page_size:
                break  # Dernière page
            page += 1

        stats["fetched"] = len(all_events)
        if verbose:
            print(f"[Livelox] {len(all_events)} événements trouvés")

        # Filtrage sprint par nom d'événement
        if sprint_only:
            all_events = [
                e for e in all_events
                if _is_sprint_event(e.get("name", "") or e.get("Name", ""))
                or "sprint" in str(e.get("classes", e.get("Classes", ""))).lower()
            ]
            if verbose:
                print(f"[Livelox] {len(all_events)} événements sprint retenus")
        stats["sprint"] = len(all_events)

        if max_events:
            all_events = all_events[:max_events]

        for event in all_events:
            event_id = event.get("id") or event.get("ID") or event.get("eventId")
            event_name = event.get("name") or event.get("Name", "?")
            event_date = event.get("date") or event.get("Date") or event.get("startTime", "")[:10]

            if not event_id:
                stats["errors"] += 1
                continue

            if verbose:
                print(f"\n→ [{event_id}] {event_name} ({event_date})")

            sub = self.ingest_event(int(event_id), sprint_only=sprint_only, dry_run=dry_run, verbose=verbose)
            stats["stored"] += sub["stored"]
            stats["skipped"] += sub["skipped"]
            stats["errors"] += sub["errors"]

        if verbose:
            print(f"\n{'='*60}")
            print(f"Résultat : {stats['stored']} stockés / {stats['skipped']} ignorés / {stats['errors']} erreurs")
            print(f"{'='*60}")

        return stats

    def _store_circuits(
        self,
        circuits: List[Dict[str, Any]],
        event_id: int,
        dry_run: bool,
        verbose: bool,
        stats: Dict[str, int],
    ) -> Dict[str, int]:
        from ..learning.gpx_feature_extractor import (
            _compute_osm_terrain,
            _circuit_quality_score,
            _grade_td,
            _bearing,
            _bearing_change,
        )
        from ..learning.feature_extractor import ControlFeatureVector, _haversine_m

        for circuit in circuits:
            controls = circuit["controls"]  # [(lng, lat), ...]
            if len(controls) < 3:
                continue

            # Déduplication
            hash_input = f"livelox|{event_id}|{circuit['name']}|{controls[0]}|{controls[-1]}"
            content_hash = hashlib.sha256(hash_input.encode()).hexdigest()

            if self.db and not dry_run:
                from src.models.contribution import Contribution
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
                    print(f"  ! OSM error : {e}")
                terrain_features = [{} for _ in controls]

            # Features géométriques
            legs = [_haversine_m(controls[i], controls[i + 1]) for i in range(len(controls) - 1)]
            length_m = circuit.get("length_m") or (sum(legs) if legs else None)
            td = _grade_td(legs)
            quality = _circuit_quality_score(controls)
            bearings = [_bearing(controls[i], controls[i + 1]) for i in range(len(controls) - 1)]

            control_features = []
            for i in range(len(controls)):
                leg_dist = legs[i] if i < len(legs) else 0.0
                bearing_chg = 0.0
                if i > 0 and i < len(bearings):
                    bearing_chg = _bearing_change(bearings[i - 1], bearings[i])
                terrain = terrain_features[i] if i < len(terrain_features) else {}
                control_features.append(ControlFeatureVector(
                    leg_distance_m=round(leg_dist, 1),
                    leg_bearing_change=round(bearing_chg, 1),
                    control_position_ratio=round(i / max(len(controls) - 1, 1), 3),
                    td_grade=td,
                    pd_grade=None,
                    terrain_symbol_density=terrain.get("terrain_symbol_density"),
                    nearest_path_dist_m=terrain.get("nearest_path_dist_m"),
                    control_feature_type=terrain.get("control_feature_type"),
                    attractiveness_score=terrain.get("attractiveness_score"),
                    quality_score=round(quality, 3),
                ))

            if verbose:
                dist_str = f"{round(length_m)}m" if length_m else "?"
                print(f"  ✓ {circuit['name']} — {len(controls)} postes, {dist_str}, TD{td}, q={quality:.2f}")

            if not dry_run and self.db:
                from src.models.contribution import Contribution, ControlFeature
                contrib = Contribution(
                    xml_hash=content_hash,
                    source_format="livelox_osm",
                    circuit_type="sprint",
                    map_type="urban",
                    ffco_category=None,
                    td_grade=td,
                    pd_grade=None,
                    n_controls=len(controls),
                    length_m=round(length_m) if length_m else None,
                    climb_m=circuit.get("climb_m"),
                    consent_educational=True,
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

        return stats
