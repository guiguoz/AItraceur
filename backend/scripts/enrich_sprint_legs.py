#!/usr/bin/env python3
"""
enrich_sprint_legs.py — Enrichit les jambes sprint avec des features de réseau OSM.

Ajoute 4 colonnes à output/intent_legs_{map}.csv :
  route_diversity   — Jaccard de diversité entre k meilleurs chemins [0,1]
  path_length_ratio — similarité de longueur min/max parmi les routes crédibles [0,1]
  decision_points   — nb de bifurcations significatives sur le meilleur chemin (A*)
  valid_graph_ratio — fraction de jambes avec chemin trouvé (même valeur pour toutes les lignes)

Note : mesure "OSM + heuristiques RouteAnalyzer" (simplification réseau, angle 30°,
snapping). Voir plan pour détail hypothèses H1/H2/H3.

Usage :
  python backend/scripts/enrich_sprint_legs.py caen
  python backend/scripts/enrich_sprint_legs.py caen bayeux langrune
"""

from __future__ import annotations

import csv
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import requests

_SCRIPT = pathlib.Path(__file__).parent
_ROOT   = _SCRIPT.parent.parent

_RA_DIR = _ROOT / "backend" / "src" / "services" / "optimization"
sys.path.insert(0, str(_RA_DIR))
from route_analyzer import RouteAnalyzer  # noqa: E402

OUTPUT = _ROOT / "output"

_WALK_TAGS = (
    "residential|service|unclassified|tertiary|secondary|primary"
    "|pedestrian|path|footway|steps|living_street|alley"
)
_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]
_NEW_COLS = ("route_diversity", "path_length_ratio", "decision_points", "valid_graph_ratio")


def _fetch_highway_ways(bbox: dict) -> list[list[tuple[float, float]]]:
    b = f"{bbox['min_y']},{bbox['min_x']},{bbox['max_y']},{bbox['max_x']}"
    query = (
        f"[out:json][timeout:60];\n"
        f"(way[\"highway\"~\"^({_WALK_TAGS})$\"]({b}););\n"
        f"out body geom;"
    )
    _HEADERS = {"User-Agent": "AItraceur-research/1.0 (orienteering course analysis)"}
    last_exc: Exception | None = None
    for mirror in _OVERPASS_MIRRORS:
        try:
            resp = requests.post(mirror, data={"data": query}, headers=_HEADERS, timeout=35)
            resp.raise_for_status()
            data = resp.json()
            ways = []
            for elem in data.get("elements", []):
                if "highway" not in elem.get("tags", {}):
                    continue
                geom = elem.get("geometry", [])
                coords = [(g["lon"], g["lat"]) for g in geom if "lon" in g and "lat" in g]
                if len(coords) >= 2:
                    ways.append(coords)
            return ways
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"Overpass inaccessible (tous miroirs) : {last_exc}")


def enrich_map(map_name: str) -> None:
    legs_path = OUTPUT / f"intent_legs_{map_name}.csv"
    if not legs_path.exists():
        print(f"  [ERREUR] {legs_path} introuvable")
        return

    rows = list(csv.DictReader(legs_path.open(encoding="utf-8")))
    if not rows:
        print(f"  [WARN] {map_name} : CSV vide")
        return

    print(f"\n{'═'*62}")
    print(f"  {map_name} — {len(rows)} jambes")
    print(f"{'═'*62}")

    lats = [float(r["start_lat"]) for r in rows] + [float(r["end_lat"]) for r in rows]
    lons = [float(r["start_lon"]) for r in rows] + [float(r["end_lon"]) for r in rows]
    margin = 0.003  # ~300m
    bbox = {
        "min_y": min(lats) - margin, "max_y": max(lats) + margin,
        "min_x": min(lons) - margin, "max_x": max(lons) + margin,
    }
    print(f"  Bbox : lat=[{bbox['min_y']:.4f},{bbox['max_y']:.4f}]  "
          f"lon=[{bbox['min_x']:.4f},{bbox['max_x']:.4f}]")

    print("  Fetch Overpass OSM...", flush=True)
    t0 = time.time()
    try:
        highway_ways = _fetch_highway_ways(bbox)
    except RuntimeError as exc:
        print(f"  [ERREUR] {exc}")
        return
    print(f"  {len(highway_ways)} voies OSM en {time.time()-t0:.1f}s")

    if not highway_ways:
        print("  [ERREUR] Aucune voie OSM — enrichissement impossible")
        return

    analyzer = RouteAnalyzer(highway_ways)
    print(f"  Graphe : {analyzer.node_count} noeuds, {analyzer.edge_count} arêtes")
    print("  Calcul features par jambe...", flush=True)

    n_found = 0
    for i, row in enumerate(rows):
        slng = float(row["start_lon"])
        slat = float(row["start_lat"])
        elng = float(row["end_lon"])
        elat = float(row["end_lat"])

        info = analyzer.route_diversity_info(slng, slat, elng, elat, k=3)

        if info["credible_routes"] > 0:
            n_found += 1
            row["route_diversity"]   = round(info["jaccard"], 4)
            row["path_length_ratio"] = round(info["similarity_ratio"], 4)
            row["decision_points"]   = analyzer.count_decision_points(slng, slat, elng, elat)
        else:
            row["route_diversity"]   = ""
            row["path_length_ratio"] = ""
            row["decision_points"]   = ""

        if (i + 1) % 20 == 0:
            print(f"    {i+1}/{len(rows)}...", flush=True)

    valid_ratio = round(n_found / max(len(rows), 1), 3)
    for row in rows:
        row["valid_graph_ratio"] = valid_ratio

    print(f"\n  valid_graph_ratio = {valid_ratio:.3f}  ({n_found}/{len(rows)} chemins trouvés)")
    if valid_ratio < 0.7:
        print("  ⚠ valid_graph_ratio < 0.7 — graphe OSM fragmenté, biais potentiel sur route_diversity")

    # Conserver les fieldnames originaux + nouvelles colonnes (sans doublon)
    original_fields = list(rows[0].keys())
    existing = set(original_fields)
    fieldnames = original_fields + [c for c in _NEW_COLS if c not in existing]

    with legs_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Écrit : {legs_path}")


def main() -> None:
    maps = sys.argv[1:]
    if not maps:
        print("Usage: python enrich_sprint_legs.py <map1> [map2 ...]")
        print("Ex:    python enrich_sprint_legs.py caen")
        sys.exit(1)
    for m in maps:
        enrich_map(m)
    print()


if __name__ == "__main__":
    main()
