"""
index_vikazimut.py — Indexe et filtre les parcours Vikazimut téléchargés.

Entrées :
  vikazimut/parcours/*.xml  (+ *.kml côte à côte)
  vikazimut/traces/N-*.gpx
  vikazimut/maps/N.jpg

Sorties :
  vikazimut/index.json   — tous les parcours avec métadonnées + flag is_foot_o
  vikazimut/stats.json   — résumé chiffré

Usage :
  python scripts/index_vikazimut.py
  python scripts/index_vikazimut.py --check-speed
  python scripts/index_vikazimut.py --vikazimut-dir /autre/chemin
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


# ─── Helpers ────────────────────────────────────────────────────────────────

IOF_NS = "http://www.orienteering.org/datastandard/3.0"
KML_NS = "http://www.opengis.net/kml/2.2"

VTT_DISCIPLINES = {"vtt", "bike", "mtbo", "vtt-o"}
VTT_COURSE_TYPES = {"bike", "mtb", "vtt"}
MAX_FOOT_O_KM = 20.0
SPEED_THRESHOLD_KMH = 14.0


def _tag(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── XML parser ─────────────────────────────────────────────────────────────

def parse_xml(xml_path: Path) -> dict:
    """Parse un fichier XML IOF 3.0 Vikazimut."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        return {"error": str(exc)}

    root = tree.getroot()
    ns = IOF_NS if root.tag.startswith(f"{{{IOF_NS}}}") else ""

    def find(node, *path):
        for p in path:
            tag = _tag(ns, p) if ns else p
            node = node.find(tag)
            if node is None:
                return None
        return node

    def findall(node, *path):
        parent = find(node, *path[:-1]) if len(path) > 1 else node
        if parent is None:
            return []
        tag = _tag(ns, path[-1]) if ns else path[-1]
        return parent.findall(tag)

    def text(node, *path):
        n = find(node, *path)
        return n.text.strip() if n is not None and n.text else ""

    rcd = find(root, "RaceCourseData")
    if rcd is None:
        return {"error": "no RaceCourseData"}

    map_node = find(rcd, "Map")
    ext = find(map_node, "Extensions") if map_node is not None else None

    discipline = ""
    course_type = ""
    scale = 0
    if ext is not None:
        discipline = text(ext, "Discipline").lower()
        course_type = text(ext, "CourseType").lower()
    if map_node is not None:
        try:
            scale = int(text(map_node, "Scale"))
        except ValueError:
            scale = 0

    # Contrôles (Start + Control + Finish)
    controls = []
    for ctrl in rcd.iter(_tag(ns, "Control") if ns else "Control"):
        ctrl_type = ctrl.get("type", "Control")
        pos = ctrl.find(_tag(ns, "Position") if ns else "Position")
        if pos is None:
            continue
        try:
            lat = float(pos.get("lat", ""))
            lng = float(pos.get("lng", ""))
        except (ValueError, TypeError):
            continue
        controls.append({"lat": lat, "lng": lng, "type": ctrl_type})

    # Distance totale (Haversine entre postes consécutifs)
    total_m = sum(
        haversine_m(controls[i]["lat"], controls[i]["lng"],
                    controls[i + 1]["lat"], controls[i + 1]["lng"])
        for i in range(len(controls) - 1)
    )

    return {
        "discipline": discipline,
        "course_type": course_type,
        "scale": scale,
        "n_controls": max(0, len(controls) - 2),  # hors départ/arrivée
        "total_dist_km": round(total_m / 1000, 2),
        "controls": controls,
    }


# ─── KML parser ─────────────────────────────────────────────────────────────

def parse_kml(kml_path: Path) -> dict | None:
    """Extrait la LatLonBox du KML Vikazimut."""
    try:
        tree = ET.parse(kml_path)
    except ET.ParseError:
        return None

    root = tree.getroot()
    ns = KML_NS if root.tag.startswith(f"{{{KML_NS}}}") else ""

    def find_all(node, local):
        tag = _tag(ns, local) if ns else local
        return list(node.iter(tag))

    boxes = find_all(root, "LatLonBox")
    if not boxes:
        return None

    box = boxes[0]

    def ftext(local):
        n = box.find(_tag(ns, local) if ns else local)
        try:
            return float(n.text.strip()) if n is not None and n.text else None
        except ValueError:
            return None

    north, south, east, west = ftext("north"), ftext("south"), ftext("east"), ftext("west")
    rotation = ftext("rotation") or 0.0

    if any(v is None for v in (north, south, east, west)):
        return None

    return {"north": north, "south": south, "east": east, "west": west, "rotation": rotation}


# ─── GPX speed check ────────────────────────────────────────────────────────

def gpx_avg_speed_kmh(gpx_path: Path) -> float | None:
    """Calcule la vitesse moyenne en km/h depuis un GPX (timestamps relatifs epoch)."""
    try:
        tree = ET.parse(gpx_path)
    except ET.ParseError:
        return None

    root = tree.getroot()
    # Namespace GPX 1.1
    gpx_ns = "http://www.topografix.com/GPX/1/1"
    ns = gpx_ns if root.tag.startswith(f"{{{gpx_ns}}}") else ""

    trkpt_tag = _tag(ns, "trkpt") if ns else "trkpt"
    time_tag = _tag(ns, "time") if ns else "time"

    points = []
    for pt in root.iter(trkpt_tag):
        try:
            lat = float(pt.get("lat", ""))
            lng = float(pt.get("lon", ""))
        except ValueError:
            continue
        t_node = pt.find(time_tag)
        t_sec = None
        if t_node is not None and t_node.text:
            # Format : 1970-01-01T00:00:01.964Z → secondes depuis epoch
            raw = t_node.text.strip().replace("Z", "").replace("T", " ")
            try:
                from datetime import datetime
                dt = datetime.strptime(raw[:23], "%Y-%m-%d %H:%M:%S.%f")
                t_sec = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
            except ValueError:
                pass
        points.append((lat, lng, t_sec))

    if len(points) < 2:
        return None

    total_dist = sum(
        haversine_m(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
        for i in range(len(points) - 1)
    )
    times = [p[2] for p in points if p[2] is not None]
    if len(times) < 2:
        return None

    elapsed = max(times) - min(times)
    if elapsed <= 0:
        return None

    return round((total_dist / elapsed) * 3.6, 2)


# ─── Filtre VTT-O ───────────────────────────────────────────────────────────

def classify(entry: dict) -> tuple[bool, str | None]:
    """Retourne (is_foot_o, filter_reason)."""
    disc = entry.get("discipline", "")
    ctype = entry.get("course_type", "")
    dist = entry.get("total_dist_km", 0)

    if any(kw in disc for kw in VTT_DISCIPLINES):
        return False, "vtt_discipline"
    if any(kw in ctype for kw in VTT_COURSE_TYPES):
        return False, "vtt_course_type"
    if dist > MAX_FOOT_O_KM:
        return False, "distance_too_long"
    return True, None


# ─── Main ────────────────────────────────────────────────────────────────────

def build_gpx_index(traces_dir: Path) -> dict[int, list[str]]:
    """Construit un dict {parcours_id: [gpx_path, ...]} depuis le dossier traces."""
    index: dict[int, list[str]] = defaultdict(list)
    for gpx in sorted(traces_dir.glob("*.gpx")):
        # Format : N-M.gpx
        parts = gpx.stem.split("-")
        if len(parts) >= 2:
            try:
                pid = int(parts[0])
                index[pid].append(str(gpx))
            except ValueError:
                pass
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexe les parcours Vikazimut")
    parser.add_argument(
        "--vikazimut-dir",
        default=str(Path(__file__).parent.parent.parent / "vikazimut"),
        help="Chemin vers le dossier vikazimut/ (défaut: ../vikazimut depuis backend/)",
    )
    parser.add_argument(
        "--check-speed",
        action="store_true",
        help="Calcule la vitesse GPX pour détecter les traces VTT suspectes (~5-10 min)",
    )
    args = parser.parse_args()

    vika_dir = Path(args.vikazimut_dir)
    parcours_dir = vika_dir / "parcours"
    traces_dir = vika_dir / "traces"
    maps_dir = vika_dir / "maps"

    if not parcours_dir.exists():
        print(f"[ERREUR] Dossier introuvable : {parcours_dir}", file=sys.stderr)
        sys.exit(1)

    xml_files = sorted(parcours_dir.glob("*.xml"))
    total = len(xml_files)
    print(f"Indexation de {total} parcours XML…")

    gpx_index = build_gpx_index(traces_dir) if traces_dir.exists() else {}

    results = []
    stats: dict = {
        "total": total,
        "foot_o": 0,
        "excluded_vtt_discipline": 0,
        "excluded_vtt_course_type": 0,
        "excluded_distance_too_long": 0,
        "parse_errors": 0,
        "no_map": 0,
        "no_traces": 0,
        "disciplines": defaultdict(int),
    }

    for i, xml_path in enumerate(xml_files, 1):
        if i % 500 == 0 or i == total:
            print(f"  {i}/{total}…", flush=True)

        pid_str = xml_path.stem
        try:
            pid = int(pid_str)
        except ValueError:
            continue

        entry = parse_xml(xml_path)
        if "error" in entry:
            stats["parse_errors"] += 1
            continue

        kml_path = parcours_dir / f"{pid_str}.kml"
        bounds = parse_kml(kml_path) if kml_path.exists() else None

        map_jpg = maps_dir / f"{pid_str}.jpg"
        map_png = maps_dir / f"{pid_str}.png"
        map_file = (
            str(map_jpg) if map_jpg.exists()
            else str(map_png) if map_png.exists()
            else None
        )
        if map_file is None:
            stats["no_map"] += 1

        traces = gpx_index.get(pid, [])
        if not traces:
            stats["no_traces"] += 1

        is_foot_o, filter_reason = classify(entry)

        speed_suspicious = False
        if args.check_speed and is_foot_o and traces:
            for gpx_file in traces[:3]:  # limite à 3 traces par parcours
                spd = gpx_avg_speed_kmh(Path(gpx_file))
                if spd is not None and spd > SPEED_THRESHOLD_KMH:
                    speed_suspicious = True
                    break

        disc = entry["discipline"] or "unknown"
        stats["disciplines"][disc] += 1

        if is_foot_o:
            stats["foot_o"] += 1
        elif filter_reason:
            key = f"excluded_{filter_reason}"
            stats[key] = stats.get(key, 0) + 1

        record: dict = {
            "id": pid,
            "discipline": entry["discipline"],
            "course_type": entry["course_type"],
            "scale": entry["scale"],
            "n_controls": entry["n_controls"],
            "total_dist_km": entry["total_dist_km"],
            "bounds": bounds,
            "controls": entry["controls"],
            "map_jpg": map_file,
            "traces": traces,
            "is_foot_o": is_foot_o,
            "filter_reason": filter_reason,
        }
        if args.check_speed:
            record["speed_suspicious"] = speed_suspicious

        results.append(record)

    # Écrire index.json
    index_path = vika_dir / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nindex.json écrit : {index_path}  ({len(results)} entrées)")

    # Écrire stats.json
    stats["disciplines"] = dict(stats["disciplines"])
    stats_path = vika_dir / "stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # Affichage résumé (ASCII uniquement pour compatibilité Windows cp1252)
    print("\n-- Résumé ------------------------------------------")
    print(f"  Total parcours   : {stats['total']}")
    print(f"  Foot-O conservés : {stats['foot_o']}")
    for k, v in stats.items():
        if k.startswith("excluded_") and v:
            print(f"  {k:<30}: {v}")
    print(f"  Erreurs parse    : {stats['parse_errors']}")
    print(f"  Sans carte JPG   : {stats['no_map']}")
    print(f"  Sans traces GPX  : {stats['no_traces']}")
    disciplines_sorted = dict(sorted(stats["disciplines"].items(), key=lambda x: -x[1]))
    print(f"\n  Disciplines : {disciplines_sorted}")
    print(f"\nstats.json écrit : {stats_path}")


if __name__ == "__main__":
    main()
