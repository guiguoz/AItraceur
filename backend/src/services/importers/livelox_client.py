"""
Client API Livelox (api.livelox.com).

Livelox expose une API publique JSON + IOF XML pour les événements de CO.
Endpoints clés :
  GET /events                                     → liste événements
  GET /event/{id}                                 → détail événement
  GET /orienteering/courses/iofxml?eventId=...    → positions WGS84 des contrôles

Authentification :
  - Via clé API (header ApiKey) — demander à info@livelox.com
  - Via session web (login/password du compte livelox.com)

Rate limit : 1 requête/sec par sécurité.
"""

import time
from typing import Optional

import requests

API_BASE = "https://api.livelox.com"
WEB_BASE = "https://www.livelox.com"

DISCIPLINE_SPRINT = "sprint"


class LiveloxClient:
    """
    Client HTTP pour api.livelox.com.

    Usage avec clé API :
        client = LiveloxClient(api_key="your-key")

    Usage avec compte web (login/password) :
        client = LiveloxClient()
        client.login("username", "password")
    """

    def __init__(self, api_key: Optional[str] = None, rate_limit_s: float = 1.2):
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        if api_key:
            self.session.headers["ApiKey"] = api_key
        self.rate_limit_s = rate_limit_s
        self._last_call: float = 0.0

    def login(self, username: str, password: str) -> bool:
        """
        Authentification via compte livelox.com (session cookie).

        Le cookie HttpOnly est automatiquement stocké dans self.session
        et renvoyé pour tous les appels suivants (y compris api.livelox.com).

        Returns: True si login réussi, False sinon.
        """
        resp = self.session.post(
            f"{WEB_BASE}/Authentication/Login",
            json={"username": username, "password": password, "redirectUrl": None},
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[Livelox] Échec login : HTTP {resp.status_code} — {resp.text[:200]}")
            return False

        # Vérifier la réponse JSON (indépendamment de la copie des cookies)
        try:
            data = resp.json()
            if "redirectUrl" not in data:
                print(f"[Livelox] Réponse inattendue : {resp.text[:200]}")
                return False
        except Exception as e:
            print(f"[Livelox] Erreur parse JSON : {e} — {resp.text[:200]}")
            return False

        # Récupérer le token AVANT de copier (évite CookieConflictError)
        original_cookies = {c.name: c.value for c in self.session.cookies}
        ctx_token = original_cookies.get("userContextToken")

        # Copier les cookies pour tous les sous-domaines livelox.com
        for name, value in original_cookies.items():
            for domain in ("api.livelox.com", ".livelox.com"):
                self.session.cookies.set(name, value, domain=domain, path="/")

        # Essayer userContextToken comme header
        if ctx_token:
            self.session.headers["userContextToken"] = ctx_token
            self.session.headers["Authorization"] = f"Bearer {ctx_token}"

        print(f"[Livelox] Connecté — cookies : {list(original_cookies.keys())}")
        print(f"[Livelox] userContextToken : {ctx_token[:40] + '...' if ctx_token and len(ctx_token) > 40 else ctx_token}")
        return True

    def _get(self, path: str, accept: str = "application/json", **params) -> requests.Response:
        elapsed = time.time() - self._last_call
        if elapsed < self.rate_limit_s:
            time.sleep(self.rate_limit_s - elapsed)
        url = f"{API_BASE}/{path.lstrip('/')}"
        self.session.headers["Accept"] = accept
        self.session.headers["Origin"] = WEB_BASE
        self.session.headers["Referer"] = f"{WEB_BASE}/"
        resp = self.session.get(
            url,
            params={k: v for k, v in params.items() if v is not None},
            timeout=30,
        )
        self._last_call = time.time()
        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # Événements
    # ------------------------------------------------------------------

    def get_events(
        self,
        from_dt: Optional[str] = None,
        to_dt: Optional[str] = None,
        country_id: Optional[int] = None,
        south: Optional[float] = None,
        north: Optional[float] = None,
        west: Optional[float] = None,
        east: Optional[float] = None,
        only_valid: bool = True,
        include_classes: bool = True,
        sorting: str = "time:descending",
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """
        Liste les événements Livelox.

        Args:
            from_dt / to_dt : "YYYY-MM-DDThh:mm:ssZ" (UTC ISO8601)
            country_id      : ID numérique pays Livelox (ex: 752=Suède)
            south/north/west/east : bbox WGS84 pour filtrer géographiquement
            only_valid      : Seulement les événements avec carte+parcours valides
            sorting         : "time:descending" | "time:ascending"
            page / page_size: Pagination ("1:50" → page 1, 50 résultats)

        Returns: dict JSON Livelox
        """
        return self._get(
            "/events",
            **{
                "from": from_dt,
                "to": to_dt,
                "countryId": country_id,
                "south": south,
                "north": north,
                "west": west,
                "east": east,
                "onlyHavingValidMapAndCourses": str(only_valid).lower(),
                "includeClasses": str(include_classes).lower(),
                "sorting": sorting,
                "paging": f"{page}:{page_size}",
            },
        ).json()

    def get_event(self, event_id: int, include_classes: bool = True) -> dict:
        """Détails d'un événement Livelox."""
        return self._get(
            f"/event/{event_id}",
            includeClasses=str(include_classes).lower(),
        ).json()

    def get_countries(self, only_having_events: bool = True) -> dict:
        """Liste des pays avec événements Livelox."""
        return self._get(
            "/countries",
            onlyHavingEvents=str(only_having_events).lower(),
        ).json()

    # ------------------------------------------------------------------
    # Données de parcours
    # ------------------------------------------------------------------

    def get_course_iofxml(
        self,
        event_id: int,
        include_controls: bool = True,
        include_class_connections: bool = True,
        include_classes: bool = True,
    ) -> bytes:
        """
        Retourne les données de parcours en IOF XML 3.0.

        Inclut les positions WGS84 des contrôles si include_controls=True.

        Returns: bytes XML
        """
        return self._get(
            "/orienteering/courses/iofxml",
            accept="application/xml",
            eventId=event_id,
            includeControls=str(include_controls).lower(),
            includeClassConnections=str(include_class_connections).lower(),
            includeClasses=str(include_classes).lower(),
        ).content
