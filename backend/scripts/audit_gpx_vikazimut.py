"""
Audit d'exploitabilité des traces GPX Vikazimut pour les parcours foot-O.

Usage :
    python backend/scripts/audit_gpx_vikazimut.py [--n 50]

Vérifie pour chaque parcours foot-O :
  - les points GPX tombent-ils dans la bbox de la carte ?
  - les contrôles sont-ils visités (< 50m du tracé) ?

Sortie :
  Rapport console + résumé GO/NO-GO.
"""

import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# Résolution du chemin vers le package backend
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json


# ── Haversine ────────────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── GPX parser minimal ───────────────────────────────────────────────────────

@dataclass
class _Pt:
    lat: float
    lon: float


_GPX_NS = [
    "http://www.topografix.com/GPX/1/1",
    "http://www.topografix.com/GPX/1/0",
    "",
]


def _findall(elem, tag):
    for ns in _GPX_NS:
        found = elem.findall(f"{{{ns}}}{tag}" if ns else tag)
        if found:
            return found
    return []


def _parse_gpx(path: str) -> List[_Pt]:
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []
    root = tree.getroot()
    pts = []
    for trkpt in _findall(root, "trk") + _findall(root, "rte"):
        # descend dans trkseg/trkpt ou directement rtept
        for seg in _findall(trkpt, "trkseg") or [trkpt]:
            for pt in _findall(seg, "trkpt") or _findall(seg, "rtept"):
                try:
                    pts.append(_Pt(float(pt.attrib["lat"]), float(pt.attrib["lon"])))
                except (KeyError, ValueError):
                    pass
    # fallback : wpt
    if not pts:
        for wpt in _findall(root, "wpt"):
            try:
                pts.append(_Pt(float(wpt.attrib["lat"]), float(wpt.attrib["lon"])))
            except (KeyError, ValueError):
                pass
    return pts


# ── Audit d'un parcours ───────────────────────────────────────────────────────

def _audit_course(course: dict, snap_radius_m: float = 50.0) -> Optional[dict]:
    """
    Retourne un dict de métriques pour un parcours, ou None si les données manquent.
    """
    traces = course.get("traces", [])
    controls = course.get("controls", [])
    bounds = course.get("bounds", {})

    if not traces or len(controls) < 2 or not bounds:
        return None

    gpx_path = traces[0]
    if not os.path.exists(gpx_path):
        return None

    pts = _parse_gpx(gpx_path)
    if len(pts) < 10:
        return None

    # Bbox
    lat_min = bounds.get("south", 0)
    lat_max = bounds.get("north", 0)
    lng_min = bounds.get("west", 0)
    lng_max = bounds.get("east", 0)

    # % points dans bbox
    in_bbox = sum(
        1 for p in pts
        if lat_min <= p.lat <= lat_max and lng_min <= p.lon <= lng_max
    )
    ratio_bbox = in_bbox / len(pts) if pts else 0.0

    # % contrôles visités (point GPX le plus proche < snap_radius_m)
    visited = 0
    min_dists = []
    for ctrl in controls:
        ctrl_lat = ctrl.get("lat", 0)
        ctrl_lng = ctrl.get("lng", 0)
        best = min(
            _haversine_m(p.lat, p.lon, ctrl_lat, ctrl_lng) for p in pts
        )
        min_dists.append(best)
        if best <= snap_radius_m:
            visited += 1

    ratio_visited = visited / len(controls) if controls else 0.0
    exploitable = ratio_bbox >= 0.80 and ratio_visited >= 0.70

    return {
        "id": course.get("id"),
        "discipline": course.get("discipline"),
        "n_controls": len(controls),
        "n_traces": len(traces),
        "n_gpx_pts": len(pts),
        "ratio_bbox": ratio_bbox,
        "visited": visited,
        "total_controls": len(controls),
        "ratio_visited": ratio_visited,
        "min_dist_max_m": round(max(min_dists), 1) if min_dists else 0,
        "exploitable": exploitable,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Audit exploitabilité GPX Vikazimut")
    parser.add_argument("--n", type=int, default=50, help="Nombre de parcours à auditer")
    parser.add_argument(
        "--index",
        default=os.path.join(os.path.dirname(__file__), "../../vikazimut/index.json"),
        help="Chemin vers index.json",
    )
    args = parser.parse_args()

    index_path = os.path.normpath(args.index)
    if not os.path.exists(index_path):
        print(f"[ERREUR] index.json introuvable : {index_path}")
        sys.exit(1)

    with open(index_path, encoding="utf-8") as f:
        data = json.load(f)

    # Filtrer foot-O uniquement
    foot_o = [
        c for c in data
        if c.get("is_foot_o") and c.get("traces") and c.get("controls") and c.get("bounds")
    ]
    print(f"foot-O disponibles : {len(foot_o)} / {len(data)} totaux")

    sample = foot_o[: args.n]
    print(f"Audit sur {len(sample)} parcours...\n")

    results = []
    exploitable_count = 0
    total_gpx_ok = 0

    for i, course in enumerate(sample, 1):
        r = _audit_course(course)
        if r is None:
            print(f"[{i:02d}/{len(sample)}] #{course.get('id')} — données insuffisantes, ignoré")
            continue

        status = "OK EXPLOITABLE" if r["exploitable"] else "NON EXPLOITABLE"
        if r["exploitable"]:
            exploitable_count += 1
            total_gpx_ok += r["n_traces"]

        print(
            f"[{i:02d}/{len(sample)}] #{r['id']} ({r['discipline']}, "
            f"{r['n_controls']} ctrl, {r['n_traces']} gpx)\n"
            f"  bbox: {r['ratio_bbox']*100:.0f}% pts  "
            f"ctrl visites: {r['visited']}/{r['total_controls']} "
            f"(max dist: {r['min_dist_max_m']}m)\n"
            f"  -> {status}\n"
        )
        results.append(r)

    # Résumé
    audited = len(results)
    ratio_exploit = exploitable_count / audited if audited else 0
    print("=" * 60)
    print(f"RÉSUMÉ : {exploitable_count}/{audited} exploitables ({ratio_exploit*100:.0f}%)")
    print(f"GPX totaux dans les parcours exploitables : {total_gpx_ok}")

    if ratio_exploit >= 0.60:
        print("-> GO : lancer build_leg_diversity_db.py")
    elif ratio_exploit >= 0.30:
        print("-> PARTIEL : exploitable mais qualite variable")
    else:
        print("-> NO-GO : trop peu de donnees coherentes")


if __name__ == "__main__":
    main()
