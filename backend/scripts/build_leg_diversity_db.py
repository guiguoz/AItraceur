"""
Construit la base de données de diversité de jambes depuis les traces GPX Vikazimut.

Pour chaque parcours foot-O avec >= MIN_RUNNERS coureurs :
  - Parse les GPX depuis vikazimut/traces/
  - Appelle analyze_multi_gpx() pour obtenir difficulty_per_leg (CV vitesse)
  - Stocke chaque jambe avec sa géométrie (bbox + dist_m) et son CV

Output : backend/data/leg_diversity.json
  [
    {"lat_min": ..., "lng_min": ..., "lat_max": ..., "lng_max": ...,
     "dist_m": 450, "cv": 0.38, "n_runners": 12},
    ...
  ]

Usage :
    python backend/scripts/build_leg_diversity_db.py [--max 500] [--min-runners 3]
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.analysis.gpx_parser import parse_gpx
from src.services.analysis.multi_gpx_analyzer import analyze_multi_gpx


# ── Haversine ─────────────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build leg diversity DB from Vikazimut GPX")
    parser.add_argument("--max", type=int, default=0, help="Nb max de parcours (0=tous)")
    parser.add_argument("--min-runners", type=int, default=3, help="Runners minimum par parcours")
    parser.add_argument(
        "--index",
        default=os.path.join(os.path.dirname(__file__), "../../vikazimut/index.json"),
        help="Chemin vers index.json",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(__file__), "../data/leg_diversity.json"),
        help="Chemin output JSON",
    )
    args = parser.parse_args()

    index_path = os.path.normpath(args.index)
    output_path = os.path.normpath(args.output)

    with open(index_path, encoding="utf-8") as f:
        data = json.load(f)

    # Filtrer foot-O avec assez de traces et controles
    candidates = [
        c for c in data
        if c.get("is_foot_o")
        and len(c.get("traces", [])) >= args.min_runners
        and len(c.get("controls", [])) >= 3
        and c.get("bounds")
    ]

    if args.max:
        candidates = candidates[: args.max]

    print(f"foot-O exploitables : {len(candidates)} parcours (min {args.min_runners} runners)")

    leg_entries = []
    courses_ok = 0
    courses_skip = 0
    total_legs = 0

    for i, course in enumerate(candidates, 1):
        course_id = course["id"]
        traces = course["traces"]
        raw_controls = course["controls"]

        # Adapter controls au format {x: lng, y: lat, order: n}
        controls = [
            {"x": ctrl["lng"], "y": ctrl["lat"], "order": idx}
            for idx, ctrl in enumerate(raw_controls)
        ]

        # Charger les GPX
        gpx_tracks = []
        for gpx_path in traces:
            if not os.path.exists(gpx_path):
                continue
            try:
                with open(gpx_path, "rb") as f:
                    track = parse_gpx(f.read())
                if len(track) >= 10:
                    gpx_tracks.append(track)
            except Exception:
                pass

        if len(gpx_tracks) < args.min_runners:
            courses_skip += 1
            continue

        # Analyser
        try:
            result = analyze_multi_gpx(gpx_tracks, controls, snap_radius_m=60.0)
        except Exception as e:
            print(f"  [WARN] #{course_id} : erreur analyse — {e}")
            courses_skip += 1
            continue

        difficulty = result.get("difficulty_per_leg", {})
        speed = result.get("speed_per_leg", {})

        if not difficulty:
            courses_skip += 1
            continue

        # Construire les entrées de jambes
        n_legs_added = 0
        for leg_str, cv in difficulty.items():
            leg_idx = int(leg_str) - 1  # leg "1" = controls[0] -> controls[1]
            if leg_idx < 0 or leg_idx + 1 >= len(raw_controls):
                continue

            ctrl_a = raw_controls[leg_idx]
            ctrl_b = raw_controls[leg_idx + 1]
            lat_a, lng_a = ctrl_a["lat"], ctrl_a["lng"]
            lat_b, lng_b = ctrl_b["lat"], ctrl_b["lng"]

            dist_m = _haversine_m(lat_a, lng_a, lat_b, lng_b)
            if dist_m < 30:
                continue  # jambe trop courte, probablement bruit

            n_runners = speed.get(leg_str, {}).get("runners", len(gpx_tracks))

            leg_entries.append({
                "lat_min": min(lat_a, lat_b),
                "lng_min": min(lng_a, lng_b),
                "lat_max": max(lat_a, lat_b),
                "lng_max": max(lng_a, lng_b),
                "dist_m": round(dist_m, 1),
                "cv": round(cv, 4),
                "n_runners": n_runners,
            })
            n_legs_added += 1

        courses_ok += 1
        total_legs += n_legs_added

        if i % 50 == 0 or i == len(candidates):
            print(
                f"  [{i}/{len(candidates)}] OK={courses_ok} skip={courses_skip} "
                f"legs={total_legs}"
            )

    # Sauvegarder
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(leg_entries, f, separators=(",", ":"))

    print(f"\nTermine : {courses_ok} parcours, {total_legs} jambes -> {output_path}")
    print(f"Skips : {courses_skip}")

    # Stats CV
    if leg_entries:
        cvs = [e["cv"] for e in leg_entries]
        cvs.sort()
        n = len(cvs)
        p50 = cvs[n // 2]
        p90 = cvs[int(n * 0.9)]
        high_cv = sum(1 for c in cvs if c > 0.40)
        low_cv = sum(1 for c in cvs if c < 0.05)
        print(f"CV median={p50:.3f}  p90={p90:.3f}  high(>0.40)={high_cv}  trivial(<0.05)={low_cv}")


if __name__ == "__main__":
    main()
