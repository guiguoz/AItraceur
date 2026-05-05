"""
annotate_legs.py — CLI d'annotation manuelle des legs pour la calibration Phase 0.

Produit backend/data/benchmark_legs.json : vérité terrain pour calibrer les seuils
leg_type_thresholds (route_choice_jaccard, handrail_coverage, low_catch_score).

Usage :
    cd backend
    python scripts/annotate_legs.py
    python scripts/annotate_legs.py --index ../../vikazimut/index.json --n 25
    python scripts/annotate_legs.py --show-map   # ouvre un aperçu Leaflet par jambe

Format de sortie benchmark_legs.json :
    [{
      "circuit_id": "vikazimut_4231",
      "td_level": 3,
      "circuit_type": "sprint",
      "legs": [{
        "idx": 0,
        "dist_m": 185.3,
        "bearing_deg": 42,
        "labels": ["route_choice"],
        "decision_points_manual": 2,
        "decision_points_auto": 1,
        "difficulty": 7
      }]
    }]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


# ── Géo helpers ──────────────────────────────────────────────────────────────

def _haversine(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _bearing(lng1: float, lat1: float, lng2: float, lat2: float) -> int:
    dlng = math.radians(lng2 - lng1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlng) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlng)
    return int((math.degrees(math.atan2(x, y)) + 360) % 360)


# ── Aperçu carte (--show-map) ─────────────────────────────────────────────────

def _show_leg_map(lng1: float, lat1: float, lng2: float, lat2: float) -> None:
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Leg preview</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>body{{margin:0}}#map{{height:100vh}}</style>
</head>
<body>
<div id="map"></div>
<script>
  var map = L.map('map').setView([{(lat1+lat2)/2}, {(lng1+lng2)/2}], 15);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);
  L.polyline([[{lat1},{lng1}],[{lat2},{lng2}]], {{color:'red',weight:5}}).addTo(map);
  L.circleMarker([{lat1},{lng1}], {{radius:8,color:'green'}}).addTo(map).bindPopup('Départ').openPopup();
  L.circleMarker([{lat2},{lng2}], {{radius:8,color:'blue'}}).addTo(map).bindPopup('Arrivée');
</script>
</body>
</html>"""
    tmp = Path(os.environ.get("TEMP", "/tmp")) / "leg_preview.html"
    tmp.write_text(html, encoding="utf-8")
    webbrowser.open(tmp.as_uri())


# ── Chargement index Vikazimut ────────────────────────────────────────────────

def _load_courses(index_path: Path, n: int, circuit_type: Optional[str]) -> List[dict]:
    if not index_path.exists():
        print(f"[ERREUR] index.json introuvable : {index_path}")
        sys.exit(1)

    with open(index_path, encoding="utf-8") as f:
        all_courses = json.load(f)

    usable = [
        c for c in all_courses
        if c.get("is_foot_o")
        and c.get("controls")
        and c.get("bounds")
        and len([x for x in c.get("controls", []) if x.get("type") == "Control"]) >= 5
    ]

    if circuit_type == "sprint":
        usable = [c for c in usable if c.get("discipline") in ("urbano", "sprint")]
    elif circuit_type in ("forest", "md"):
        usable = [c for c in usable if c.get("discipline") not in ("urbano", "sprint")]

    return usable[:n]


# ── Auto decision_points (si RouteAnalyzer disponible) ──────────────────────

def _auto_dp(lng1, lat1, lng2, lat2) -> Optional[int]:
    """Tente de charger le RouteAnalyzer depuis OSM pour calculer DP auto."""
    try:
        import osmnx  # noqa: F401 — vérifie juste la dispo
    except ImportError:
        return None
    try:
        from src.services.optimization.route_analyzer import RouteAnalyzer
        # Bbox minimale autour du leg
        margin = 0.006
        ways_placeholder = []  # sans ways OSM, retourne None
        ra = RouteAnalyzer(ways_placeholder)
        return ra.count_decision_points(lng1, lat1, lng2, lat2)
    except Exception:
        return None


# ── Saisie utilisateur ────────────────────────────────────────────────────────

_LABEL_MAP = {
    "r": "route_choice",
    "h": "handrail",
    "t": "technical_read",
    "d": "direct",
}


def _prompt(msg: str, default: Optional[str] = None) -> str:
    if default is not None:
        msg = f"{msg} [{default}]"
    while True:
        try:
            val = input(msg + " : ").strip()
        except (EOFError, KeyboardInterrupt):
            raise
        if not val and default is not None:
            return default
        if val:
            return val


def _ask_labels() -> List[str]:
    while True:
        raw = _prompt("[R]oute_choice [H]andrail [T]ech_read [D]irect (ex: RH ou D)").lower()
        labels = [_LABEL_MAP[c] for c in raw if c in _LABEL_MAP]
        if labels:
            return labels
        if raw in ("s", "q"):
            raise ValueError(raw)
        print("  Codes valides : R H T D (minuscules acceptées)")


def _ask_int(msg: str, lo: int, hi: int, default: Optional[int] = None) -> int:
    default_str = str(default) if default is not None else None
    while True:
        raw = _prompt(msg, default=default_str)
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
            print(f"  Valeur entre {lo} et {hi}")
        except ValueError:
            print(f"  Entier attendu")


# ── Annotation principale ─────────────────────────────────────────────────────

def annotate(
    courses: List[dict],
    benchmark: List[dict],
    out_path: Path,
    td_level: int,
    circuit_type: str,
    show_map: bool,
) -> None:
    annotated_ids = {c["circuit_id"] for c in benchmark}

    for course in courses:
        cid = str(course.get("id", "?"))
        discipline = course.get("discipline", "?")
        controls_raw = [c for c in course.get("controls", []) if c.get("type") == "Control"]

        if cid in annotated_ids:
            print(f"⏭  Skip {cid} (déjà annoté)")
            continue

        n_legs = len(controls_raw) - 1
        if n_legs < 1:
            continue

        print(f"\n{'─'*60}")
        print(f"Circuit {cid} ({discipline}, TD{td_level}) — {n_legs} jambes")
        print(f"{'─'*60}")

        legs_data = []
        skip_circuit = False

        for i in range(n_legs):
            a = controls_raw[i]
            b = controls_raw[i + 1]
            lng1, lat1 = float(a["lng"]), float(a["lat"])
            lng2, lat2 = float(b["lng"]), float(b["lat"])
            dist_m = _haversine(lng1, lat1, lng2, lat2)
            bearing = _bearing(lng1, lat1, lng2, lat2)

            auto_dp = _auto_dp(lng1, lat1, lng2, lat2)

            print(f"\n  Jambe {i+1}/{n_legs} → {dist_m:.0f}m")
            print(f"    De  : {lat1:.5f}, {lng1:.5f}  (ctrl #{i})")
            print(f"    À   : {lat2:.5f}, {lng2:.5f}  (ctrl #{i+1})")
            print(f"    Google Maps (départ) : https://maps.google.com/?q={lat1},{lng1}")
            if auto_dp is not None:
                print(f"    Auto decision_points : {auto_dp}")
            else:
                print(f"    Auto decision_points : n/a (OSM non disponible)")

            if show_map:
                _show_leg_map(lng1, lat1, lng2, lat2)

            try:
                labels = _ask_labels()
            except ValueError as e:
                if str(e) == "s":
                    skip_circuit = True
                    break
                elif str(e) == "q":
                    _save(benchmark, out_path)
                    print(f"\nSauvegardé → {out_path}")
                    sys.exit(0)
                raise

            dp_manual = _ask_int(
                f"    Decision points manuels (0-5)",
                0, 5, default=auto_dp
            )
            difficulty = _ask_int("    Difficulté (1-10)", 1, 10)

            legs_data.append({
                "idx": i,
                "dist_m": round(dist_m, 1),
                "bearing_deg": bearing,
                "labels": labels,
                "decision_points_manual": dp_manual,
                "decision_points_auto": auto_dp,
                "difficulty": difficulty,
            })

        if skip_circuit:
            print(f"  ↩ Circuit {cid} ignoré")
            continue

        benchmark.append({
            "circuit_id": cid,
            "td_level": td_level,
            "circuit_type": circuit_type,
            "legs": legs_data,
        })
        annotated_ids.add(cid)
        _save(benchmark, out_path)
        print(f"\n  ✓ Circuit {cid} annoté ({len(legs_data)} jambes) — sauvegardé")

    print(f"\n{'='*60}")
    print(f"Annotation terminée — {len(benchmark)} circuits dans {out_path}")


def _save(benchmark: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(benchmark, f, ensure_ascii=False, indent=2)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLI d'annotation manuelle des legs CO pour calibration Phase 0"
    )
    parser.add_argument(
        "--index",
        default=str(BACKEND_DIR.parent / "vikazimut" / "index.json"),
        help="Chemin vers vikazimut/index.json",
    )
    parser.add_argument(
        "--out",
        default=str(BACKEND_DIR / "data" / "benchmark_legs.json"),
        help="Fichier de sortie (défaut: data/benchmark_legs.json)",
    )
    parser.add_argument("--n", type=int, default=25,
                        help="Nombre de circuits à annoter (défaut: 25)")
    parser.add_argument("--td", type=int, default=3, choices=[1, 2, 3, 4, 5],
                        help="Niveau TD à assigner (défaut: 3)")
    parser.add_argument("--circuit-type", default="sprint",
                        choices=["sprint", "forest", "md"],
                        help="Type de circuit (défaut: sprint)")
    parser.add_argument("--show-map", action="store_true",
                        help="Ouvrir un aperçu Leaflet HTML par jambe (nécessite un navigateur)")
    args = parser.parse_args()

    out_path = Path(args.out)

    # Charger annotation existante (resume-capable)
    benchmark: List[dict] = []
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            benchmark = json.load(f)
        print(f"Reprise : {len(benchmark)} circuits déjà annotés dans {out_path}")
    else:
        print(f"Nouveau fichier : {out_path}")

    courses = _load_courses(Path(args.index), args.n, args.circuit_type)
    if not courses:
        print("[ERREUR] Aucun circuit Vikazimut disponible.")
        sys.exit(1)

    print(f"\n{len(courses)} circuits chargés. Commandes : [s]=skip circuit  [q]=quitter & sauvegarder\n")

    try:
        annotate(
            courses=courses,
            benchmark=benchmark,
            out_path=out_path,
            td_level=args.td,
            circuit_type=args.circuit_type,
            show_map=args.show_map,
        )
    except KeyboardInterrupt:
        _save(benchmark, out_path)
        print(f"\nInterrompu — sauvegardé : {out_path}")


if __name__ == "__main__":
    main()
