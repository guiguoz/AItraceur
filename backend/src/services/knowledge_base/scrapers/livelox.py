# =============================================
# Scraper Livelox
# Sprint 6: Base de connaissances RAG
# =============================================

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# =============================================
# Types de données
# =============================================
@dataclass
class LiveloxEvent:
    """Un événement sur Livelox."""

    livelox_id: str
    name: str
    date: Optional[str] = None
    club: Optional[str] = None
    discipline: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    url: Optional[str] = None
    courses: List[Dict] = field(default_factory=list)


@dataclass
class LiveloxCourse:
    """Un circuit Livelox."""

    name: str
    length_m: Optional[float] = None
    climb_m: Optional[float] = None
    controls: int = 0
    winners: List[Dict] = field(default_factory=list)


@dataclass
class LiveloxResult:
    """Un résultat Livelox."""

    runner_name: str
    club: Optional[str] = None
    course: str = ""
    time: Optional[str] = None
    position: Optional[int] = None
    split_times: Dict[int, str] = field(default_factory=dict)  # control_num -> time


# =============================================
# Scraper Livelox
# =============================================
class LiveloxScraper:
    """
    Scraper pour Livelox (livelox.com).

    Livelox est un site de visualisation de traces GPS pour la course d'orientation.
    Il contient des événements, des circuits et des résultats.

    Note: L'API officielle n'est pas publique, on utilise le scraping.
    """

    BASE_URL = "https://livelox.com"
    API_URL = "https://livelox.com/api"

    def __init__(self):
        """Initialise le scraper."""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            }
        )

    def get_event(self, event_id: str) -> Optional[LiveloxEvent]:
        """
        Récupère un événement par son ID.

        Args:
            event_id: ID de l'événement sur Livelox

        Returns:
            LiveloxEvent ou None si non trouvé
        """
        # Essayer l'API
        try:
            response = self.session.get(f"{self.API_URL}/Event/{event_id}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return self._parse_event(data)
        except Exception as e:
            print(f"Erreur API Livelox: {e}")

        return None

    def search_events(
        self,
        query: str = None,
        country: str = None,
        year: int = None,
        limit: int = 20,
    ) -> List[LiveloxEvent]:
        """
        Recherche des événements.

        Args:
            query: Requête de recherche
            country: Code pays (ex: "FR")
            year: Année
            limit: Nombre max de résultats

        Returns:
            Liste d'événements
        """
        events = []

        # Note: L'API de recherche n'est pas publique
        # On retourne une liste vide - l'utilisateur peut ajouter manuellement des événements
        return events

    def get_event_results(self, event_id: str) -> List[LiveloxResult]:
        """
        Récupère les résultats d'un événement.

        Args:
            event_id: ID de l'événement

        Returns:
            Liste de résultats
        """
        try:
            response = self.session.get(
                f"{self.API_URL}/Event/{eventId}/Results", timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return self._parse_results(data)
        except Exception as e:
            print(f"Erreur récupération résultats: {e}")

        return []

    def get_course_controls(self, event_id: str, course_name: str) -> List[Dict]:
        """
        Récupère les postes d'un circuit.

        Args:
            event_id: ID de l'événement
            course_name: Nom du circuit

        Returns:
            Liste des postes {code, x, y, description}
        """
        try:
            # Essayer d'obtenir les données du circuit
            response = self.session.get(
                f"{self.API_URL}/Event/{eventId}/Course/{course_name}", timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("controls", [])
        except Exception as e:
            print(f"Erreur récupération postes: {e}")

        return []

    def _parse_event(self, data: Dict) -> LiveloxEvent:
        """Parse les données d'un événement."""
        return LiveloxEvent(
            livelox_id=str(data.get("id", "")),
            name=data.get("name", ""),
            date=data.get("date", ""),
            club=data.get("organiser", {}).get("name", ""),
            discipline=data.get("discipline", ""),
            country=data.get("country", ""),
            region=data.get("region", ""),
            url=f"{self.BASE_URL}/Event/{data.get('id')}",
            courses=[
                {
                    "name": c.get("name"),
                    "length": c.get("length"),
                    "climb": c.get("climb"),
                }
                for c in data.get("courses", [])
            ],
        )

    def _parse_results(self, data: Dict) -> List[LiveloxResult]:
        """Parse les résultats."""
        results = []

        for entry in data.get("results", []):
            result = LiveloxResult(
                runner_name=entry.get("name", ""),
                club=entry.get("club", ""),
                course=entry.get("course", ""),
                time=entry.get("time", ""),
                position=entry.get("position"),
            )

            # Split times
            for split in entry.get("splits", []):
                result.split_times[split.get("control")] = split.get("time", "")

            results.append(result)

        return results


# =============================================
# Fonctions utilitaires
# =============================================
def export_event_to_text(event: LiveloxEvent) -> str:
    """
    Exporte un événement en texte pour le RAG.

    Args:
        event: Événement à exporter

    Returns:
        Texte formaté
    """
    lines = [
        f"Événement: {event.name}",
        f"Date: {event.date or 'Inconnue'}",
        f"Club: {event.club or 'Inconnu'}",
        f"Pays: {event.country or 'Inconnu'}",
        f"Discipline: {event.discipline or 'Inconnue'}",
        "",
        "Circuits:",
    ]

    for course in event.courses:
        lines.append(f"  - {course.get('name', 'Inconnu')}")
        if course.get("length"):
            lines.append(f"    Longueur: {course['length']}m")
        if course.get("climb"):
            lines.append(f"    D+: {course['climb']}m")

    return "\n".join(lines)


def export_results_to_text(results: List[LiveloxResult]) -> str:
    """
    Exporte les résultats en texte pour le RAG.

    Args:
        results: Résultats à exporter

    Returns:
        Texte formaté
    """
    lines = [
        "Résultats de course d'orientation:",
        "",
    ]

    # Grouper par circuit
    by_course = {}
    for r in results:
        if r.course not in by_course:
            by_course[r.course] = []
        by_course[r.course].append(r)

    for course_name, course_results in by_course.items():
        lines.append(f"Circuit {course_name}:")
        for r in course_results[:10]:  # Top 10
            pos = f"#{r.position}" if r.position else ""
            time = f" - {r.time}" if r.time else ""
            lines.append(f"  {pos} {r.runner_name} ({r.club or 'Sans club'}){time}")

        lines.append("")

    return "\n".join(lines)
