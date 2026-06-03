"""MapProfile — ce que la carte permet de faire, en langage traceur CO."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class MapProfile:
    navigation_complexity: Optional[float]   # None si candidate_points ISOM absent
    route_choice_potential: float            # densité arêtes OSM [0-1]
    speed_potential: float                   # fraction terrain CNN > 0.6 [0-1]
    micro_relief_potential: float            # std altitudes locale (ElevationCache) [0-1]
    visibility_complexity: Optional[float]   # None si ocad_line_segments absent


def compute_map_profile(
    bbox: tuple,
    heatmap_cache=None,
    elevation_cache=None,
    route_analyzer=None,
    candidate_points: Optional[List] = None,
    ocad_line_segments: Optional[List] = None,
) -> MapProfile:
    """
    Calcule le profil de la carte — ce qu'elle permet de faire.

    bbox: (min_lng, min_lat, max_lng, max_lat)
    Toutes les autres données sont optionnelles (fallback 0.5 si absent).
    """
    min_lng, min_lat, max_lng, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2.0
    lng_scale = math.cos(math.radians(mid_lat)) * 111_320.0
    lat_scale = 111_320.0
    bbox_km2 = (max_lng - min_lng) * lng_scale * (max_lat - min_lat) * lat_scale / 1e6
    bbox_km2 = max(bbox_km2, 0.01)

    # ── navigation_complexity : densité ISOM (None si données absentes) ──────────
    if candidate_points:
        isom_count = sum(1 for cp in candidate_points if cp.get("isom"))
        nav_complexity: Optional[float] = min(1.0, isom_count / (bbox_km2 * 50.0))
    else:
        nav_complexity = None

    # ── route_choice_potential : densité arêtes OSM ───────────────────────────
    if route_analyzer is not None:
        try:
            edge_count = route_analyzer.graph.number_of_edges()
            # Seuil : 500 arêtes/km² = réseau très dense
            route_potential = min(1.0, edge_count / (bbox_km2 * 500.0))
        except Exception:
            route_potential = 0.5
    else:
        route_potential = 0.5

    # ── speed_potential : fraction CNN > 0.6 ──────────────────────────────────
    if heatmap_cache is not None:
        scores = heatmap_cache.scores.flatten().astype(float)
        speed_pot = float((scores > 0.60).sum() / max(1, len(scores)))
    else:
        speed_pot = 0.5

    # ── micro_relief_potential : std des altitudes ────────────────────────────
    if elevation_cache is not None:
        try:
            alts = elevation_cache.altitudes.flatten().astype(float)
            valid = alts[~np.isnan(alts)]
            if len(valid) > 0:
                # Seuil : 50m de std → terrain très vallonné
                relief_pot = min(1.0, float(valid.std()) / 50.0)
            else:
                relief_pot = 0.0
        except Exception:
            relief_pot = 0.0
    else:
        relief_pot = 0.0

    # ── visibility_complexity : densité courbes de niveau (None si données absentes) ──
    if ocad_line_segments:
        vis_complexity: Optional[float] = min(1.0, len(ocad_line_segments) / (bbox_km2 * 100.0))
    else:
        vis_complexity = None

    return MapProfile(
        navigation_complexity=round(nav_complexity, 3) if nav_complexity is not None else None,
        route_choice_potential=round(route_potential, 3),
        speed_potential=round(speed_pot, 3),
        micro_relief_potential=round(relief_pot, 3),
        visibility_complexity=round(vis_complexity, 3) if vis_complexity is not None else None,
    )
