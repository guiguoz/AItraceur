"""
Client API Eventor (orienteering).

Supports : Swedish (eventor.orientering.se), Norwegian (eventor.orientering.no),
           IOF (eventor.orienteering.org / eventor.orienteering.sport).

Authentication : header ApiKey (32 chars).
Rate limit     : 1 requête/seconde par sécurité (pas de limite documentée).
"""

import time
from typing import Optional

import requests

# URLs nationales connues
EVENTOR_URLS = {
    "SE": "https://eventor.orientering.se/api",
    "NO": "https://eventor.orientering.no/api",
    "IOF": "https://eventor.orienteering.sport/api",
    "DK": "https://eventor.o-l.dk/api",
    "FI": "https://eventor.suunnistusliitto.fi/api",
    "AU": "https://eventor.orienteering.asn.au/api",
    "GB": "https://eventor.britishorienteering.org.uk/api",
}


class EventorClient:
    """
    Client HTTP pour l'API Eventor.

    Usage:
        client = EventorClient(api_key="...", country="SE")
        events_xml = client.get_sprint_events("2025-01-01", "2025-12-31")
        course_xml  = client.get_course_data(event_id=12345)
    """

    def __init__(
        self,
        api_key: str,
        country: str = "SE",
        base_url: Optional[str] = None,
        rate_limit_s: float = 1.2,
    ):
        self.base_url = (base_url or EVENTOR_URLS.get(country.upper(), EVENTOR_URLS["SE"])).rstrip("/")
        self.session = requests.Session()
        self.session.headers["ApiKey"] = api_key
        self.session.headers["Accept"] = "application/xml"
        self.rate_limit_s = rate_limit_s
        self._last_call: float = 0.0

    def _get(self, path: str, **params) -> bytes:
        elapsed = time.time() - self._last_call
        if elapsed < self.rate_limit_s:
            time.sleep(self.rate_limit_s - elapsed)
        url = f"{self.base_url}/{path.lstrip('/')}"
        resp = self.session.get(url, params={k: v for k, v in params.items() if v is not None}, timeout=30)
        self._last_call = time.time()
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # Événements
    # ------------------------------------------------------------------

    def get_events(
        self,
        from_date: str,
        to_date: str,
        classifications: str = "1,2,3,4",
        organisations: Optional[str] = None,
    ) -> bytes:
        """
        Liste les événements dans une plage de dates.

        Args:
            from_date: "YYYY-MM-DD"
            to_date:   "YYYY-MM-DD"
            classifications: IDs séparés par virgule (1=championnats…4=local)
            organisations: IDs d'organisations séparés par virgule (optionnel)

        Returns: XML EventList
        """
        return self._get(
            "/events",
            fromDate=from_date,
            toDate=to_date,
            classificationIds=classifications,
            organisations=organisations,
        )

    def get_event(self, event_id: int) -> bytes:
        """Détails d'un événement (XML Event)."""
        return self._get(f"/event/{event_id}")

    # ------------------------------------------------------------------
    # Données de parcours
    # ------------------------------------------------------------------

    def get_course_data(self, event_id: int, event_race_id: Optional[int] = None) -> bytes:
        """
        Données de parcours IOF XML pour un événement.

        Tente plusieurs endpoints dans l'ordre :
        1. /courseData?eventId= (endpoint standard)
        2. /results/event/iofxml?eventId= (contient parfois les données cours)

        Returns: bytes XML (IOF XML 3.0 CourseData ou ResultList)
        Raises: requests.HTTPError si aucun endpoint ne répond
        """
        # Endpoint principal
        try:
            return self._get("/courseData", eventId=event_id, eventRaceId=event_race_id)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (403, 404):
                pass  # Essayer le fallback
            else:
                raise

        # Fallback : résultats (peut contenir des positions de contrôles)
        return self._get("/results/event/iofxml", eventId=event_id)

    def get_event_classes(self, event_id: int) -> bytes:
        """Classes (catégories) d'un événement."""
        return self._get("/eventclasses", eventId=event_id)
