# =============================================
# Scraper RouteGadget
# Sprint 6: Base de connaissances RAG
# =============================================

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup


# =============================================
# Types de données
# =============================================
@dataclass
class RouteGadgetEvent:
    """Un événement RouteGadget."""

    event_id: str
    name: str
    date: Optional[str] = None
    club: Optional[str] = None
    organizer: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    courses: List[str] = field(default_factory=list)


@dataclass
class RouteGadgetCourse:
    """Un circuit RouteGadget."""

    name: str
    course_id: str
    length_m: Optional[float] = None
    climb_m: Optional[float] = None
    controls: int = 0


@dataclass
class RouteGadgetTrack:
    """Une trace GPS RouteGadget."""

    runner_name: str
    club: Optional[str] = None
    course: str = ""
    time: Optional[str] = None
    splits: Dict[int, str] = field(default_factory=dict)  # control -> time
    route: List[Dict] = field(default_factory=list)  # [(lat, lon, time), ...]
    start_time: Optional[str] = None
    finish_time: Optional[str] = None


# =============================================
# Scraper RouteGadget
# =============================================
class RouteGadgetScraper:
    """
    Scraper pour RouteGadget (routegadget.net).

    RouteGadget est un outil de visualisation de traces GPS pour la CO.
    Il permet de voir les itinéraires des concurrents.
    """

    # Différentes instances RouteGadget
    INSTANCES = [
        "https://www.routegadget.net",
        "https://2d.routegadget.net",
    ]

    def __init__(self, base_url: str = "https://www.routegadget.net"):
        """
        Initialise le scraper.

        Args:
            base_url: URL de l'instance RouteGadget
        """
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/html",
            }
        )

    def get_event(self, event_id: str) -> Optional[RouteGadgetEvent]:
        """
        Récupère un événement par son ID.

        Args:
            event_id: ID de l'événement

        Returns:
            RouteGadgetEvent ou None
        """
        url = f"{self.base_url}/arkisto/{event_id}"

        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return self._parse_event(response.text, event_id, url)
        except Exception as e:
            print(f"Erreur récupération événement: {e}")

        return None

    def get_events_list(self, limit: int = 20) -> List[RouteGadgetEvent]:
        """
        Récupère la liste des événements.

        Args:
            limit: Nombre maximum d'événements

        Returns:
            Liste d'événements
        """
        # L'archive RouteGadget n'a pas de liste publique simple
        # On retourne des événements populaires
        events = []

        # Exemple d'événements FIN5 ( Finland )
        fin5_events = [
            {"id": "fin5-2022", "name": "FIN5 2022"},
            {"id": "fin5-2023", "name": "FIN5 2023"},
        ]

        for e in fin5_events[:limit]:
            event = self.get_event(e["id"])
            if event:
                events.append(event)

        return events

    def get_course(
        self, event_id: str, course_name: str
    ) -> Optional[RouteGadgetCourse]:
        """
        Récupère un circuit.

        Args:
            event_id: ID de l'événement
            course_name: Nom du circuit

        Returns:
            RouteGadgetCourse ou None
        """
        url = f"{self.base_url}/arkisto/{event_id}/{course_name}"

        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return self._parse_course(response.text, course_name)
        except Exception as e:
            print(f"Erreur récupération circuit: {e}")

        return None

    def get_tracks(
        self,
        event_id: str,
        course_name: str = None,
    ) -> List[RouteGadgetTrack]:
        """
        Récupère les traces d'un événement/circuit.

        Args:
            event_id: ID de l'événement
            course_name: Nom du circuit (optionnel)

        Returns:
            Liste de traces
        """
        tracks = []

        # Essayer l'API JSON
        try:
            # URL pour récupérer les résultats en JSON
            json_url = f"{self.base_url}/arkisto/{event_id}/getcourses"

            response = self.session.get(json_url, timeout=10)
            if response.status_code == 200:
                data = response.json()

                # Parser chaque circuit
                courses = data.get("courses", [])
                for course in courses:
                    course_name = course.get("name", "")
                    course_id = course.get("id", "")

                    # Récupérer les résultats pour ce circuit
                    results_url = (
                        f"{self.base_url}/arkisto/{event_id}/getresults/{course_id}"
                    )
                    results_response = self.session.get(results_url, timeout=10)

                    if results_response.status_code == 200:
                        results_data = results_response.json()
                        course_tracks = self._parse_tracks(results_data, course_name)
                        tracks.extend(course_tracks)

        except Exception as e:
            print(f"Erreur récupération traces: {e}")

        return tracks

    def get_competitor_route(
        self,
        event_id: str,
        course_id: str,
        competitor_id: str,
    ) -> Optional[RouteGadgetTrack]:
        """
        Récupère la route complète d'un concurrent.

        Args:
            event_id: ID de l'événement
            course_id: ID du circuit
            competitor_id: ID du concurrent

        Returns:
            RouteGadgetTrack avec la route complète
        """
        try:
            url = f"{self.base_url}/arkisto/{event_id}/getroute/{course_id}/{competitor_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                return self._parse_route(data)

        except Exception as e:
            print(f"Erreur récupération route: {e}")

        return None

    def get_all_routes(
        self,
        event_id: str,
        course_name: str,
    ) -> List[RouteGadgetTrack]:
        """
        Récupère toutes les routes d'un circuit.

        Args:
            event_id: ID de l'événement
            course_name: Nom du circuit

        Returns:
            Liste de toutes les traces
        """
        tracks = []

        try:
            # D'abord récupérer les résultats
            courses_url = f"{self.base_url}/arkisto/{event_id}/getcourses"
            response = self.session.get(courses_url, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # Trouver le circuit
                course_id = None
                for course in data.get("courses", []):
                    if course.get("name") == course_name:
                        course_id = course.get("id")
                        break

                if course_id:
                    # Récupérer les résultats
                    results_url = (
                        f"{self.base_url}/arkisto/{event_id}/getresults/{course_id}"
                    )
                    results_response = self.session.get(results_url, timeout=10)

                    if results_response.status_code == 200:
                        results_data = results_response.json()

                        # Pour chaque concurrent, récupérer sa route
                        for result in results_data.get("results", []):
                            competitor_id = (
                                result.get("id", "").split("/")[-1]
                                if result.get("id")
                                else ""
                            )

                            if competitor_id:
                                route = self.get_competitor_route(
                                    event_id, course_id, competitor_id
                                )
                                if route:
                                    route.runner_name = result.get("name", "Unknown")
                                    route.course = course_name
                                    route.time = result.get("time", "")
                                    tracks.append(route)

        except Exception as e:
            print(f"Erreur récupération routes: {e}")

        return tracks

    def _parse_event(self, html: str, event_id: str, url: str) -> RouteGadgetEvent:
        """Parse une page d'événement."""
        soup = BeautifulSoup(html, "html.parser")

        # Titre
        title = ""
        title_elem = soup.select_one("h1, h2, .event-title, .title")
        if title_elem:
            title = title_elem.get_text(strip=True)

        # Date
        date = None
        date_elem = soup.select_one("time, .date")
        if date_elem:
            date = date_elem.get("datetime") or date_elem.get_text(strip=True)

        # Circuits
        courses = []
        course_links = soup.select("a[href*='course'], .course a")
        for link in course_links:
            course_name = link.get_text(strip=True)
            if course_name and course_name not in courses:
                courses.append(course_name)

        return RouteGadgetEvent(
            event_id=event_id,
            name=title or f"Event {event_id}",
            url=url,
            date=date,
            courses=courses,
        )

    def _parse_course(self, html: str, course_name: str) -> RouteGadgetCourse:
        """Parse une page de circuit."""
        soup = BeautifulSoup(html, "html.parser")

        # Extraire les infos du circuit
        length = None
        climb = None
        controls = 0

        # Chercher dans le texte
        text = soup.get_text()

        length_match = re.search(r"(\d+)\s*m", text)
        if length_match:
            length = float(length_match.group(1))

        climb_match = re.search(r"(\d+)\s*m\s*D\+", text)
        if climb_match:
            climb = float(climb_match.group(1))

        control_match = re.search(r"(\d+)\s*postes?", text)
        if control_match:
            controls = int(control_match.group(1))

        return RouteGadgetCourse(
            name=course_name,
            course_id=course_name.lower().replace(" ", "-"),
            length_m=length,
            climb_m=climb,
            controls=controls,
        )

    def _parse_tracks(self, data: Dict, course_name: str) -> List[RouteGadgetTrack]:
        """Parse les résultats pour extraire les traces."""
        tracks = []

        for result in data.get("results", []):
            track = RouteGadgetTrack(
                runner_name=result.get("name", "Unknown"),
                club=result.get("club", ""),
                course=course_name,
                time=result.get("time", ""),
            )

            # Splits
            splits_data = result.get("splits", {})
            for split in splits_data:
                if isinstance(split, dict):
                    control = split.get("control", 0)
                    time = split.get("time", "")
                    track.splits[control] = time

            tracks.append(track)

        return tracks

    def _parse_route(self, data: Dict) -> Optional[RouteGadgetTrack]:
        """Parse une route complète."""
        if not data:
            return None

        track = RouteGadgetTrack(
            runner_name=data.get("name", "Unknown"),
            club=data.get("club", ""),
        )

        # Parser la route (format: [lat, lon, time], ...)
        route_data = data.get("route", [])

        for point in route_data:
            if len(point) >= 2:
                lat = point[0]
                lon = point[1]
                time = point[2] if len(point) > 2 else None

                track.route.append(
                    {
                        "lat": lat,
                        "lon": lon,
                        "time": time,
                    }
                )

        return track


# =============================================
# Analyse des traces
# =============================================
class RouteAnalyzer:
    """
    Analyse les traces pour en extraire des informations utiles.
    """

    def __init__(self):
        """Initialise l'analyseur."""
        self.scraper = RouteGadgetScraper()

    def analyze_popular_routes(
        self,
        event_id: str,
        course_name: str,
    ) -> Dict:
        """
        Analyse les routes populaires d'un circuit.

        Returns:
            Analyse des choix d'itinéraires
        """
        tracks = self.scraper.get_all_routes(event_id, course_name)

        if not tracks:
            return {"error": "Aucune trace trouvée"}

        # Analyser les points de passage
        waypoints = self._analyze_waypoints(tracks)

        # Analyser les temps
        time_stats = self._analyze_times(tracks)

        # Trouver la route "optimale" (meilleur temps)
        best_route = min(tracks, key=lambda t: t.time or "") if tracks else None

        return {
            "course_name": course_name,
            "total_tracks": len(tracks),
            "waypoints": waypoints,
            "time_stats": time_stats,
            "best_time": best_route.time if best_route else None,
            "best_runner": best_route.runner_name if best_route else None,
        }

    def _analyze_waypoints(self, tracks: List[RouteGadgetTrack]) -> List[Dict]:
        """Analyse les points de passage communs."""
        # Compter les passages dans chaque zone
        from collections import defaultdict

        grid = defaultdict(int)

        for track in tracks:
            for point in track.route:
                # Discrétiser en grille de 50m
                lat_rounded = round(point["lat"] * 20) / 20
                lon_rounded = round(point["lon"] * 20) / 20
                grid[(lat_rounded, lon_rounded)] += 1

        # Trier par fréquence
        sorted_waypoints = sorted(
            grid.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:10]

        return [
            {
                "lat": wp[0][0],
                "lon": wp[0][1],
                "count": wp[1],
                "percentage": wp[1] / len(tracks) * 100,
            }
            for wp in sorted_waypoints
        ]

    def _analyze_times(self, tracks: List[RouteGadgetTrack]) -> Dict:
        """Analyse les temps."""
        valid_times = []

        for track in tracks:
            if track.time:
                # Parser le temps (format: HH:MM:SS)
                try:
                    parts = track.time.split(":")
                    if len(parts) == 3:
                        minutes = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 2:
                        minutes = int(parts[0])
                    else:
                        continue
                    valid_times.append(minutes)
                except:
                    continue

        if not valid_times:
            return {}

        return {
            "min_time": min(valid_times),
            "max_time": max(valid_times),
            "avg_time": sum(valid_times) / len(valid_times),
            "count": len(valid_times),
        }


# =============================================
# Fonctions utilitaires
# =============================================
def export_track_to_text(track: RouteGadgetTrack) -> str:
    """
    Exporte une trace en texte pour le RAG.

    Args:
        track: Trace à exporter

    Returns:
        Texte formaté
    """
    lines = [
        f"Coureur: {track.runner_name}",
        f"Club: {track.club or 'Inconnu'}",
        f"Circuit: {track.course}",
        f"Temps: {track.time or 'Inconnu'}",
        "",
    ]

    if track.splits:
        lines.append("Splits:")
        for control, split_time in track.splits.items():
            lines.append(f"  Poste {control}: {split_time}")
        lines.append("")

    if track.route:
        lines.append(f"Route: {len(track.route)} points GPS")

    return "\n".join(lines)


def export_analysis_to_text(analysis: Dict) -> str:
    """
    Exporte une analyse en texte pour le RAG.

    Args:
        analysis: Analyse à exporter

    Returns:
        Texte formaté
    """
    lines = [
        f"Analyse du circuit: {analysis.get('course_name', 'Inconnu')}",
        f"Nombre de traces: {analysis.get('total_tracks', 0)}",
        "",
    ]

    time_stats = analysis.get("time_stats", {})
    if time_stats:
        lines.append("Statistiques de temps:")
        lines.append(f"  Meilleur temps: {time_stats.get('min_time', 'N/A')} min")
        lines.append(f"  Temps moyen: {time_stats.get('avg_time', 'N/A'):.1f} min")
        lines.append("")

    waypoints = analysis.get("waypoints", [])
    if waypoints:
        lines.append("Points de passage populaires:")
        for wp in waypoints[:5]:
            lines.append(
                f"  ({wp['lat']:.4f}, {wp['lon']:.4f}) - {wp['percentage']:.1f}% des courirurs"
            )
        lines.append("")

    return "\n".join(lines)
