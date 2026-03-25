"""
Pont OCAD → HeatmapCache pour l'inférence du modèle IA.

Séparation nette :
  - train_control_scorer.py  : entraînement sur MapAnt/RG2 (pur, inchangé)
  - ocad_pipeline.py         : adapte les cartes OCAD pour l'inférence
                               (normalisation couleurs → distribution MapAnt)

Usage dans _sprint_impl() :
    from src.services.learning.ocad_pipeline import fetch_ocad_image, fetch_ocad_forbidden_zones
    img = fetch_ocad_image(map_id)          # PIL.Image normalisée
    zones = fetch_ocad_forbidden_zones(map_id)  # [[lng, lat], ...]
"""
import io
import logging

import requests
from PIL import Image

from .style_normalizer import normalize_ocad_to_mapant

log = logging.getLogger(__name__)

TILE_SERVICE_URL = "http://localhost:8089"


def fetch_ocad_image(map_id: str, timeout: int = 10) -> Image.Image:
    """
    Récupère le PNG pleine-carte depuis le tile service et normalise
    les couleurs vers la distribution MapAnt (pour patch_scorer_v2).

    Lève requests.HTTPError si le PNG n'est pas disponible.
    """
    url = f"{TILE_SERVICE_URL}/renders/{map_id}.png"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    img_raw = Image.open(io.BytesIO(resp.content)).convert("RGB")
    return normalize_ocad_to_mapant(img_raw)


def fetch_ocad_forbidden_zones(map_id: str, timeout: int = 10) -> list:
    """
    Récupère les zones interdites (sym 709/527) depuis le tile service.
    Retourne une liste de polygones [[lng, lat], ...].
    Retourne [] si indisponible (pas de zone OOB dans la carte, ou erreur).
    """
    url = f"{TILE_SERVICE_URL}/map/{map_id}/forbidden-zones"
    try:
        resp = requests.get(url, timeout=timeout)
        if not resp.ok:
            log.warning("OCAD forbidden-zones %s → HTTP %s", map_id, resp.status_code)
            return []
        polygons = []
        for feat in resp.json().get("features", []):
            geom = feat.get("geometry") or {}
            gtype = geom.get("type", "")
            coords = geom.get("coordinates", [])
            if gtype == "Polygon":
                for ring in coords:
                    polygons.append([[p[0], p[1]] for p in ring])
            elif gtype == "MultiPolygon":
                for poly in coords:
                    for ring in poly:
                        polygons.append([[p[0], p[1]] for p in ring])
        return polygons
    except Exception as exc:
        log.warning("OCAD forbidden-zones fetch failed: %s", exc)
        return []
