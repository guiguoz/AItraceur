#!/usr/bin/env python3
"""
Upload batch de fichiers GPX/KMZ (sprint urbain) vers l'API ML.

Usage:
    python upload_gpx.py <dossier_ou_fichier> [ffco_category]

Exemples:
    python upload_gpx.py circuits_gpx/
    python upload_gpx.py circuits_gpx/ H21E
    python upload_gpx.py mon_circuit.gpx Open
    python upload_gpx.py mon_circuit.kmz H35

Options:
    ffco_category : catégorie FFCO (défaut: Open)
                    Exemples: H21E, D21, H35, D16, Open

L'endpoint déduit automatiquement : circuit_type=sprint, map_type=urban.
Les features terrain sont calculées depuis OSM (pas d'OCAD requis).
"""

import os
import sys
from pathlib import Path

import requests

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
ENDPOINT = f"{API_BASE}/api/v1/contribute/gpx"


def find_files(path: str) -> list:
    """Trouve tous les fichiers .gpx et .kmz dans un dossier ou fichier."""
    p = Path(path)
    if p.is_file():
        if p.suffix.lower() in (".gpx", ".kmz"):
            return [p]
        print(f"[ERREUR] {path} n'est pas un fichier .gpx ou .kmz")
        return []
    if p.is_dir():
        files = list(p.glob("**/*.gpx")) + list(p.glob("**/*.kmz"))
        files.sort()
        return files
    print(f"[ERREUR] Chemin introuvable : {path}")
    return []


def upload_file(filepath: Path, ffco_category: str) -> str:
    """Upload un fichier GPX ou KMZ. Retourne 'OK', 'DOUBLON', ou 'ECHEC'."""
    ext = filepath.suffix.lower()
    field = "gpx_file" if ext == ".gpx" else "kmz_file"

    with open(filepath, "rb") as f:
        content = f.read()

    try:
        resp = requests.post(
            ENDPOINT,
            files={field: (filepath.name, content)},
            data={
                "ffco_category": ffco_category,
                "consent_aitraceur": "true",
                "consent_educational": "true",
            },
            timeout=120,  # Overpass peut être lent
        )
    except requests.RequestException as e:
        print(f"  ✗ Erreur réseau : {e}")
        return "ECHEC"

    if resp.status_code == 200:
        data = resp.json()
        n = data.get("n_controls", "?")
        dist = data.get("length_m", "?")
        td = data.get("td_grade", "?")
        print(f"  ✓ OK — {n} postes, {dist}m, TD{td}")
        return "OK"
    elif resp.status_code == 409:
        print(f"  ~ DOUBLON (déjà contribué)")
        return "DOUBLON"
    else:
        try:
            detail = resp.json().get("detail", resp.text[:120])
        except Exception:
            detail = resp.text[:120] if resp.text else f"HTTP {resp.status_code}"
        print(f"  ✗ ECHEC {resp.status_code} : {detail}")
        return "ECHEC"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    ffco_category = sys.argv[2] if len(sys.argv) > 2 else "Open"

    files = find_files(path)
    if not files:
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Pipeline GPX+OSM — Sprint Urbain")
    print(f"Catégorie : {ffco_category}")
    print(f"Fichiers  : {len(files)}")
    print(f"Endpoint  : {ENDPOINT}")
    print(f"{'='*60}\n")

    ok = doublon = echec = 0
    for filepath in files:
        print(f"→ {filepath.name}")
        status = upload_file(filepath, ffco_category)
        if status == "OK":
            ok += 1
        elif status == "DOUBLON":
            doublon += 1
        else:
            echec += 1

    print(f"\n{'='*60}")
    print(f"Résultat : {ok} OK / {doublon} doublons / {echec} échecs / {len(files)} total")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
