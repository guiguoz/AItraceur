"""
TraceurCorrections — Mutations ciblées en réponse aux issues du contrôleur.

Pour chaque type d'issue détecté par ControleurSprint, applique une correction
géométrique sur la liste de postes et retourne la nouvelle liste corrigée.
"""

import math
import random
from typing import List, Dict, Optional

from .controleur import ControleurIssue, _haversine_m, _bearing_deg


# ── Utilitaires géométriques ──────────────────────────────────────────────────

def _move_point_perpendicular(
    lat: float, lng: float,
    lat1: float, lng1: float,
    lat2: float, lng2: float,
    distance_m: float = 50.0
) -> Dict:
    """
    Déplace un point perpendiculairement au segment (lat1,lng1)→(lat2,lng2).
    Utilisé pour corriger les dog-legs.
    """
    bearing_seg = _bearing_deg(lat1, lng1, lat2, lng2)
    # Perpendiculaire = bearing ± 90°, choisir aléatoirement
    perp_bearing = (bearing_seg + random.choice([90, -90])) % 360

    # Convertir distance en degrés approximatifs
    R = 6_371_000
    dlat = math.degrees(distance_m / R)
    dlng = math.degrees(distance_m / (R * math.cos(math.radians(lat))))

    new_lat = lat + dlat * math.cos(math.radians(perp_bearing))
    new_lng = lng + dlng * math.sin(math.radians(perp_bearing))
    return {"lat": new_lat, "lng": new_lng}


def _move_toward_candidate(
    ctrl: Dict,
    candidates: List[Dict],
    min_dist_m: float = 35.0,
    forbidden_positions: Optional[List[Dict]] = None,
    oob_polygons: Optional[List] = None
) -> Optional[Dict]:
    """
    Remplace un poste par le candidat OSM le plus proche respectant les contraintes.
    Retourne None si aucun candidat valide trouvé.
    """
    from .controleur import _point_in_polygon

    forbidden_positions = forbidden_positions or []

    # Trier les candidats par distance au poste actuel
    def dist_to_ctrl(c):
        return _haversine_m(ctrl["lat"], ctrl["lng"], c.get("y", c.get("lat", 0)), c.get("x", c.get("lng", 0)))

    sorted_cands = sorted(candidates, key=dist_to_ctrl)

    for cand in sorted_cands:
        clat = cand.get("y", cand.get("lat", 0))
        clng = cand.get("x", cand.get("lng", 0))

        # Vérifier distance minimale par rapport aux autres postes
        too_close = any(
            _haversine_m(clat, clng, p["lat"], p["lng"]) < min_dist_m
            for p in forbidden_positions
        )
        if too_close:
            continue

        # Vérifier zone interdite
        if oob_polygons:
            in_oob = any(_point_in_polygon(clat, clng, poly) for poly in oob_polygons)
            if in_oob:
                continue

        return {"lat": clat, "lng": clng, "feature_type": cand.get("type", "")}

    return None


# ── Correction principale ─────────────────────────────────────────────────────

def apply_corrections(
    controls: List[Dict],
    issues: List[ControleurIssue],
    candidates: List[Dict],
    oob_polygons: Optional[List] = None,
) -> tuple[List[Dict], List[str]]:
    """
    Applique des corrections ciblées par type d'issue.

    Args:
        controls: liste de postes [{lat, lng, type, order, ...}]
        issues: issues du ControleurSprint (triées ERROR en premier)
        candidates: candidats OSM [{x/lng, y/lat, type}, ...]
        oob_polygons: zones interdites [[lon, lat], ...]

    Returns:
        (new_controls, correction_messages) — la liste corrigée + log des actions
    """
    import copy
    new_controls = copy.deepcopy(controls)
    messages = []

    # Traiter les issues dans l'ordre (ERROR d'abord)
    sorted_issues = sorted(
        issues,
        key=lambda i: (0 if i.severity == "ERROR" else 1, i.control_index)
    )

    corrected_indices = set()

    for issue in sorted_issues:
        idx = issue.control_index
        if idx < 0 or idx >= len(new_controls):
            continue
        if idx in corrected_indices:
            continue  # Pas deux corrections sur le même poste en une passe

        ctrl = new_controls[idx]

        if issue.code == "C01":
            # Dog-leg : déplacer l'apex perpendiculairement à la jambe N→N+2
            i_from = issue.leg_from
            i_to = issue.leg_to
            if 0 <= i_from < len(new_controls) and 0 <= i_to < len(new_controls):
                prev, nxt = new_controls[i_from], new_controls[i_to]
                new_pos = _move_point_perpendicular(
                    ctrl["lat"], ctrl["lng"],
                    prev["lat"], prev["lng"],
                    nxt["lat"], nxt["lng"],
                    distance_m=45.0
                )
                new_controls[idx]["lat"] = new_pos["lat"]
                new_controls[idx]["lng"] = new_pos["lng"]
                corrected_indices.add(idx)
                messages.append(f"Correction C01 P{idx + 1} → déplacement perpendiculaire 45m")

        elif issue.code == "C02":
            # Trop proches : trouver un candidat OSM à bonne distance
            other_positions = [c for i, c in enumerate(new_controls) if i != idx]
            new_pos = _move_toward_candidate(
                ctrl, candidates,
                min_dist_m=35.0,
                forbidden_positions=other_positions,
                oob_polygons=oob_polygons
            )
            if new_pos:
                new_controls[idx]["lat"] = new_pos["lat"]
                new_controls[idx]["lng"] = new_pos["lng"]
                if new_pos.get("feature_type"):
                    new_controls[idx]["feature_type"] = new_pos["feature_type"]
                corrected_indices.add(idx)
                messages.append(f"Correction C02 P{idx + 1} → candidat OSM à distance suffisante")

        elif issue.code == "C08":
            # Zone interdite : remplacer par candidat OSM hors zone
            other_positions = [c for i, c in enumerate(new_controls) if i != idx]
            new_pos = _move_toward_candidate(
                ctrl, candidates,
                min_dist_m=20.0,
                forbidden_positions=other_positions,
                oob_polygons=oob_polygons
            )
            if new_pos:
                new_controls[idx]["lat"] = new_pos["lat"]
                new_controls[idx]["lng"] = new_pos["lng"]
                if new_pos.get("feature_type"):
                    new_controls[idx]["feature_type"] = new_pos["feature_type"]
                corrected_indices.add(idx)
                messages.append(f"Correction C08 P{idx + 1} → candidat OSM hors zone interdite")

        elif issue.code == "C10":
            # Feature type inacceptable : trouver candidat de meilleur type
            preferred_types = {"building_corner", "path_junction", "fence_corner",
                               "opening_in_fence", "statue", "pillar", "road_junction"}
            good_candidates = [c for c in candidates if c.get("type", "") in preferred_types]
            if not good_candidates:
                good_candidates = candidates
            other_positions = [c for i, c in enumerate(new_controls) if i != idx]
            new_pos = _move_toward_candidate(
                ctrl, good_candidates,
                min_dist_m=20.0,
                forbidden_positions=other_positions,
                oob_polygons=oob_polygons
            )
            if new_pos:
                new_controls[idx]["lat"] = new_pos["lat"]
                new_controls[idx]["lng"] = new_pos["lng"]
                if new_pos.get("feature_type"):
                    new_controls[idx]["feature_type"] = new_pos["feature_type"]
                corrected_indices.add(idx)
                messages.append(f"Correction C10 P{idx + 1} → feature type amélioré ({new_pos.get('feature_type', '?')})")

    return new_controls, messages
