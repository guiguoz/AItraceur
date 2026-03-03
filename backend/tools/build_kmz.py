"""
Crée un fichier KMZ : carte JPG géoréférencée + traces GPX colorées.

Ouvrable dans Google Earth Pro ou Google Maps (import KMZ).

Usage :
    cd backend
    python tools/build_kmz.py carte.jpg dossier_gpx/
    python tools/build_kmz.py carte.jpg ../gpx/ --output puijo_woc.kmz --margin 0.3

Options :
    --output FILE   Nom du KMZ de sortie (défaut : <dossier_gpx>.kmz)
    --margin N      Marge autour des traces GPS pour caler le JPG (défaut : 0.25 = 25%)
    --no-map        Inclure seulement les traces (sans overlay carte)

Notes :
    La carte JPG est étirée sur la bounding box des traces + marge.
    Si la carte est inclinée, Google Earth permet d'ajuster manuellement.
"""

import argparse
import glob
import os
import sys
import zipfile

# Palette de 20 couleurs distinctes (format KML AABBGGRR)
_COLORS = [
    "ff0000ff",  # rouge
    "ff00ff00",  # vert
    "ffff0000",  # bleu
    "ff00ffff",  # jaune
    "ffff00ff",  # magenta
    "ffffff00",  # cyan
    "ff0080ff",  # orange
    "ff8000ff",  # violet
    "ff00ff80",  # vert clair
    "ffff8000",  # bleu clair
    "ff4040ff",  # rouge foncé
    "ff40ff40",  # vert moyen
    "ffff4040",  # bleu moyen
    "ff00c0ff",  # orange vif
    "ffc000ff",  # violet clair
    "ff80ff00",  # cyan clair
    "ff0040c0",  # rouge-marron
    "ff40c000",  # vert olive
    "ffc04000",  # bleu marine
    "ff808080",  # gris
]


def main():
    parser = argparse.ArgumentParser(
        description="Crée un KMZ : overlay carte JPG + traces GPX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("jpg", help="Chemin vers le fichier JPG de la carte")
    parser.add_argument("gpx_dir", help="Dossier contenant les fichiers .gpx")
    parser.add_argument("--output", default=None, help="Fichier KMZ de sortie")
    parser.add_argument("--margin", type=float, default=0.25,
                        help="Marge autour des traces pour caler le JPG (défaut: 0.25)")
    parser.add_argument("--no-map", action="store_true",
                        help="Inclure seulement les traces sans overlay carte")
    args = parser.parse_args()

    jpg_path = os.path.abspath(args.jpg)
    gpx_dir = os.path.abspath(args.gpx_dir)

    # Vérifications
    if not os.path.isfile(jpg_path):
        print(f"[ERREUR] Carte JPG introuvable : {jpg_path}")
        sys.exit(1)

    gpx_files = sorted(glob.glob(os.path.join(gpx_dir, "*.gpx")))
    if not gpx_files:
        print(f"[ERREUR] Aucun fichier .gpx dans '{gpx_dir}'")
        sys.exit(1)

    # Nom du KMZ de sortie
    if args.output:
        out_kmz = os.path.abspath(args.output)
    else:
        base = os.path.basename(gpx_dir).replace(" ", "_") or "export"
        out_kmz = os.path.join(gpx_dir, f"{base}.kmz")

    print(f"[OK] {len(gpx_files)} fichiers GPX trouvés")

    # Parser les GPX (stdlib uniquement)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.services.analysis.gpx_parser import parse_gpx

    tracks = []
    for path in gpx_files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            pts = parse_gpx(content)
            if pts:
                name = os.path.splitext(os.path.basename(path))[0]
                # Raccourcir le nom : garder la partie après la dernière virgule
                if "," in name:
                    name = name.split(",")[-1].strip()
                tracks.append({"name": name, "points": pts})
                print(f"  ✓ {name} — {len(pts)} pts")
        except Exception as e:
            print(f"  ✗ {os.path.basename(path)} — {e}")

    if not tracks:
        print("[ERREUR] Aucune trace valide parsée")
        sys.exit(1)

    # Bounding box de toutes les traces
    all_lats = [pt.lat for t in tracks for pt in t["points"]]
    all_lons = [pt.lon for t in tracks for pt in t["points"]]
    min_lat, max_lat = min(all_lats), max(all_lats)
    min_lon, max_lon = min(all_lons), max(all_lons)

    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon
    margin = args.margin

    # Bounds avec marge pour le GroundOverlay
    north = max_lat + lat_span * margin
    south = min_lat - lat_span * margin
    east = max_lon + lon_span * margin
    west = min_lon - lon_span * margin

    print(f"\n[OK] Bounding box GPS : N={north:.5f} S={south:.5f} E={east:.5f} W={west:.5f}")
    print(f"     (marge {int(margin*100)}% ajoutée pour caler la carte)")

    # Construire le KML
    kml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        f"  <name>{os.path.splitext(os.path.basename(out_kmz))[0]}</name>",
    ]

    # GroundOverlay (carte JPG)
    if not args.no_map:
        jpg_name = os.path.basename(jpg_path)
        kml_lines += [
            "  <GroundOverlay>",
            "    <name>Carte</name>",
            "    <drawOrder>0</drawOrder>",
            "    <Icon>",
            f"      <href>{jpg_name}</href>",
            "    </Icon>",
            "    <LatLonBox>",
            f"      <north>{north:.6f}</north>",
            f"      <south>{south:.6f}</south>",
            f"      <east>{east:.6f}</east>",
            f"      <west>{west:.6f}</west>",
            "      <rotation>0</rotation>",
            "    </LatLonBox>",
            "  </GroundOverlay>",
        ]

    # Dossier pour les traces
    kml_lines += [
        "  <Folder>",
        f"    <name>Traces ({len(tracks)} coureurs)</name>",
    ]

    for i, track in enumerate(tracks):
        color = _COLORS[i % len(_COLORS)]
        pts = track["points"]
        coords = " ".join(
            f"{pt.lon:.6f},{pt.lat:.6f},0" for pt in pts
        )
        kml_lines += [
            "    <Placemark>",
            f"      <name>{_escape_xml(track['name'])}</name>",
            "      <Style>",
            "        <LineStyle>",
            f"          <color>{color}</color>",
            "          <width>2</width>",
            "        </LineStyle>",
            "      </Style>",
            "      <LineString>",
            "        <tessellate>1</tessellate>",
            f"        <coordinates>{coords}</coordinates>",
            "      </LineString>",
            "    </Placemark>",
        ]

    kml_lines += [
        "  </Folder>",
        "</Document>",
        "</kml>",
    ]

    kml_content = "\n".join(kml_lines)

    # Créer le KMZ (ZIP)
    with zipfile.ZipFile(out_kmz, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_content.encode("utf-8"))
        if not args.no_map:
            zf.write(jpg_path, os.path.basename(jpg_path))

    size_kb = os.path.getsize(out_kmz) // 1024
    print(f"\n[OK] KMZ créé : {out_kmz} ({size_kb} Ko)")
    if not args.no_map:
        print("     → Ouvre dans Google Earth ou importe dans Google Maps")
        print("     → Si le JPG est mal calé, ajuste les coins dans Google Earth :")
        print("       Clic droit sur 'Carte' > Propriétés > Ajuster la position")
    print()


def _escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()
