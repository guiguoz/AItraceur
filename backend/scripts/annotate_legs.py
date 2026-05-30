#!/usr/bin/env python3
"""
annotate_legs.py — STEP B
Serveur HTTP stdlib pour l'annotation humaine des jambes LRI.

Usage :
  python backend/scripts/annotate_legs.py [--port 5500]
  → http://localhost:5500

Fichiers lus    : output/intent_legs_<map>.csv
Fichiers écrits : output/annotations_<map>.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.stdout.reconfigure(encoding="utf-8")

_SCRIPT = pathlib.Path(__file__).parent
_ROOT   = _SCRIPT.parent.parent
OUTPUT  = _ROOT / "output"
HTML    = _SCRIPT / "annotate_legs.html"

VALID_LABELS = {"suivi", "attaque", "uncertain"}

ANNOTATION_FIELDS = ["map", "circuit_id", "leg_index", "label", "timestamp"]


# ── Helpers CSV ───────────────────────────────────────────────────────────────

def _available_maps() -> list[str]:
    return sorted(
        p.stem.removeprefix("intent_legs_")
        for p in OUTPUT.glob("intent_legs_*.csv")
    )


def _load_legs(map_name: str) -> list[dict]:
    path = OUTPUT / f"intent_legs_{map_name}.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_annotations(map_name: str) -> list[dict]:
    path = OUTPUT / f"annotations_{map_name}.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_annotation(map_name: str, circuit_id: str, leg_index: int,
                     label: str) -> None:
    path = OUTPUT / f"annotations_{map_name}.csv"
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ANNOTATION_FIELDS)
        if f.tell() == 0:   # fichier vide → écrire le header (atomique, pas de TOCTOU)
            w.writeheader()
        w.writerow({
            "map":        map_name,
            "circuit_id": circuit_id,
            "leg_index":  leg_index,
            "label":      label,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        })


# ── Request handler ───────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[1]) == "200":
            return
        super().log_message(fmt, *args)

    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, msg: str, status: int = 400) -> None:
        self._send_json({"error": msg}, status)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path.rstrip("/")

        if path == "" or path == "/":
            self._serve_html()
        elif path == "/api/maps":
            self._send_json(_available_maps())
        elif path.startswith("/api/legs/"):
            map_name = path.removeprefix("/api/legs/")
            if not map_name or any(c in map_name for c in ('/', '\\', '..')):
                self._send_error_json("map_name invalide", 400)
                return
            legs = _load_legs(map_name)
            if not legs:
                self._send_error_json(f"Carte '{map_name}' introuvable ou vide", 404)
                return
            slim = [
                {
                    "circuit_id":        r["circuit_id"],
                    "condition":         r.get("condition", ""),
                    "leg_index":         int(r["leg_index"]),
                    "leg_m":             float(r["leg_m"]),
                    "start_lat":         float(r["start_lat"]),
                    "start_lon":         float(r["start_lon"]),
                    "end_lat":           float(r["end_lat"]),
                    "end_lon":           float(r["end_lon"]),
                    "pc1":               float(r["pc1"]),
                    "pc2":               float(r.get("pc2", 0)),
                    "decision_pressure": float(r.get("decision_pressure", 0)),
                    "HANDRAIL_FOLLOW":   float(r.get("HANDRAIL_FOLLOW", 0)),
                    "ATTACK_POINT":      float(r.get("ATTACK_POINT", 0)),
                    "SAFETY_RECOVERY":   float(r.get("SAFETY_RECOVERY", 0)),
                    "RELIEF_CROSSING_GUIDANCE": float(r.get("RELIEF_CROSSING_GUIDANCE", 0)),
                }
                for r in legs
            ]
            self._send_json(slim)
        elif path.startswith("/api/annotations/"):
            map_name = path.removeprefix("/api/annotations/")
            if not map_name or any(c in map_name for c in ('/', '\\', '..')):
                self._send_error_json("map_name invalide", 400)
                return
            self._send_json(_load_annotations(map_name))
        else:
            self._send_error_json("Not found", 404)

    def _serve_html(self) -> None:
        if not HTML.exists():
            self._send_error_json("annotate_legs.html introuvable", 500)
            return
        body = HTML.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path.rstrip("/")

        if path != "/api/annotate":
            self._send_error_json("Not found", 404)
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_error_json("JSON invalide")
            return

        map_name   = str(data.get("map", "")).strip()
        circuit_id = str(data.get("circuit_id", "")).strip()
        leg_index  = data.get("leg_index")
        label      = str(data.get("label", "")).strip()

        if not map_name or not circuit_id:
            self._send_error_json("map et circuit_id requis")
            return
        if leg_index is None:
            self._send_error_json("leg_index requis")
            return
        if label not in VALID_LABELS:
            self._send_error_json(
                f"label invalide : {label!r}  (valides: {sorted(VALID_LABELS)})"
            )
            return

        try:
            leg_index = int(leg_index)
        except (TypeError, ValueError):
            self._send_error_json("leg_index doit être un entier")
            return

        _save_annotation(map_name, circuit_id, leg_index, label)
        self._send_json({"ok": True, "map": map_name, "leg_index": leg_index, "label": label})


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5500)
    args = parser.parse_args()

    maps = _available_maps()
    if maps:
        print(f"[annotate] Cartes disponibles : {maps}")
    else:
        print("[annotate] Aucune carte — lancer d'abord generate_intent_legs.py")
    print(f"[annotate] Démarrage sur http://localhost:{args.port}")

    server = HTTPServer(("localhost", args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[annotate] Arrêt.")


if __name__ == "__main__":
    main()
