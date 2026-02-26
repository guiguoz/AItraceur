"""
elevation_fetcher.py — Client OpenTopoData pour récupérer les altitudes SRTM.

Source: https://api.opentopodata.org/v1/srtm90m
- Gratuit, sans authentification
- Max 100 points par requête
- Rate limit: ~1 requête/seconde (compte public)
"""

import time
import requests
from typing import List, Tuple

OPENTOPODATA_URL = "https://api.opentopodata.org/v1/srtm90m"
BATCH_SIZE = 100
RATE_LIMIT_SLEEP = 1.1  # secondes entre les requêtes


def fetch_elevations(points: List[Tuple[float, float]]) -> List[float]:
    """
    Récupère les altitudes pour une liste de (lat, lon) via OpenTopoData SRTM 90m.

    Gère automatiquement :
    - Le batching (max 100 points/requête)
    - Le rate limiting (1 req/sec)
    - Les erreurs réseau (retourne 0.0 pour les points en échec)

    Args:
        points: Liste de tuples (latitude, longitude) en degrés décimaux WGS84

    Returns:
        Liste de floats (altitude en mètres), même ordre que l'entrée.
        0.0 pour les points dont l'altitude n'a pas pu être récupérée.
    """
    if not points:
        return []

    results = [0.0] * len(points)

    for batch_start in range(0, len(points), BATCH_SIZE):
        batch = points[batch_start : batch_start + BATCH_SIZE]
        locations = "|".join(f"{lat},{lon}" for lat, lon in batch)

        try:
            resp = requests.get(
                OPENTOPODATA_URL,
                params={"locations": locations},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for j, result in enumerate(data.get("results", [])):
                elevation = result.get("elevation")
                if elevation is not None:
                    results[batch_start + j] = float(elevation)

        except requests.exceptions.Timeout:
            print(f"[elevation_fetcher] Timeout sur batch {batch_start // BATCH_SIZE + 1}")
        except requests.exceptions.HTTPError as e:
            print(f"[elevation_fetcher] HTTP {e.response.status_code} sur batch {batch_start // BATCH_SIZE + 1}")
        except Exception as e:
            print(f"[elevation_fetcher] Erreur batch {batch_start // BATCH_SIZE + 1}: {e}")

        # Rate limiting — sauf après le dernier batch
        if batch_start + BATCH_SIZE < len(points):
            time.sleep(RATE_LIMIT_SLEEP)

    return results
