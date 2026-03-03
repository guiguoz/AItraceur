"""
Crée un KMZ multi-coureurs : carte Livelox géoréférencée + toutes les traces GPX.

Ouvrable dans Google Earth Pro ou importable dans Google Maps.

Usage :
    cd backend
    python tools/build_kmz.py carte.kmz dossier_gpx/
    python tools/build_kmz.py carte.kmz ../gpx/ --output puijo_woc.kmz

Options :
    --output FILE   Nom du KMZ de sortie (défaut : <dossier_gpx>_multi.kmz)

Formats de carte acceptés :
    .kmz  KMZ Livelox (contient map.png + LatLonBox avec rotation)  ← recommandé
    .jpg  .png  Image seule (bounds estimés depuis les traces GPS + marge 25%)
"""

import argparse
import glob
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

# Palette de 20 couleurs distinctes (format KML AABBGGRR)
_COLORS = [
    "ff0000ff", "ff00cc00", "ffff7700", "ff0055ff", "ffff00ff",
    "ff00ffff", "ff0088ff", "ff8800ff", "ff00dd88", "ffdd8800",
    "ff3333cc", "ff33cc33", "ffcc3333", "ff00aaff", "ffaa00ff",
    "ff88ff00", "ff0044bb", "ff44bb00", "ffbb4400", "ff888888",
]


def _parse_livelox_kmz(kmz_path: str):
    """
    Extrait la carte PNG et ses coordonnées depuis un KMZ Livelox.
    Retourne (png_bytes, img_name, lat_lon_box_dict) ou None si échec.
    """
    try:
        with zipfile.ZipFile(kmz_path, "r") as zf:
            kml_data = zf.read("doc.kml").decode("utf-8")
            root = ET.fromstring(kml_data)
            ns = {"kml": "http://www.opengis.net/kml/2.2"}

            # Chercher GroundOverlay (avec ou sans namespace)
            overlay = root.find(".//GroundOverlay") or root.find(
                f".//{{{ns['kml']}}}GroundOverlay"
            )
            if overlay is None:
                return None

            def _txt(elem, tag):
                node = elem.find(tag) or elem.find(f"{{{ns['kml']}}}{tag}")
                return node.text.strip() if node is not None and node.text else None

            box = overlay.find("LatLonBox") or overlay.find(f"{{{ns['kml']}}}LatLonBox")
            if box is None:
                return None

            llb = {
                "north": float(_txt(box, "north") or 0),
                "south": float(_txt(box, "south") or 0),
                "east": float(_txt(box, "east") or 0),
                "west": float(_txt(box, "west") or 0),
                "rotation": float(_txt(box, "rotation") or 0),
            }

            # Trouver le fichier image dans le KMZ
            icon = overlay.find(".//href") or overlay.find(f".//{{{ns['kml']}}}href")
            img_ref = icon.text.strip() if icon is not None and icon.text else "files/map.png"

            # Lire le PNG
            candidates = [img_ref, "files/map.png", "map.png"]
            png_bytes = None
            img_name = "map.png"
            for name in candidates:
                try:
                    png_bytes = zf.read(name)
                    img_name = os.path.basename(name)
                    break
                except KeyError:
                    continue

            if png_bytes is None:
                return None

            return png_bytes, img_name, llb

    except Exception as e:
        print(f"[WARN] Impossible de lire le KMZ Livelox : {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="KMZ multi-coureurs : carte Livelox + toutes les traces GPX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("map_file", help="KMZ Livelox (ou JPG/PNG) de la carte")
    parser.add_argument("gpx_dir", help="Dossier contenant les fichiers .gpx")
    parser.add_argument("--output", default=None, help="Fichier KMZ de sortie")
    args = parser.parse_args()

    map_path = os.path.abspath(args.map_file)
    gpx_dir = os.path.abspath(args.gpx_dir)

    if not os.path.isfile(map_path):
        print(f"[ERREUR] Carte introuvable : {map_path}")
        sys.exit(1)

    gpx_files = sorted(glob.glob(os.path.join(gpx_dir, "*.gpx")))
    if not gpx_files:
        print(f"[ERREUR] Aucun fichier .gpx dans '{gpx_dir}'")
        sys.exit(1)

    if args.output:
        out_kmz = os.path.abspath(args.output)
    else:
        base = os.path.splitext(os.path.basename(map_path))[0].replace(" ", "_")
        out_kmz = os.path.join(gpx_dir, f"{base}_multi.kmz")

    # ── Charger la carte ──────────────────────────────────────────────────────
    ext = os.path.splitext(map_path)[1].lower()
    livelox_data = None
    img_bytes = None
    img_name = os.path.basename(map_path)
    llb = None

    if ext == ".kmz":
        livelox_data = _parse_livelox_kmz(map_path)
        if livelox_data:
            img_bytes, img_name, llb = livelox_data
            print(f"[OK] KMZ Livelox chargé : {img_name} ({len(img_bytes)//1024} Ko)")
            print(f"     N={llb['north']:.5f} S={llb['south']:.5f} "
                  f"E={llb['east']:.5f} W={llb['west']:.5f} rot={llb['rotation']:.2f}°")
        else:
            print("[WARN] KMZ non reconnu comme format Livelox — bounds estimés depuis les GPX")
    else:
        with open(map_path, "rb") as f:
            img_bytes = f.read()
        print(f"[OK] Image chargée : {img_name} ({len(img_bytes)//1024} Ko)")

    # ── Parser les GPX ────────────────────────────────────────────────────────
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
                if "," in name:
                    name = name.split(",")[-1].strip()
                tracks.append({"name": name, "points": pts})
                print(f"  ✓ {name} — {len(pts)} pts")
        except Exception as e:
            print(f"  ✗ {os.path.basename(path)} — {e}")

    if not tracks:
        print("[ERREUR] Aucune trace valide parsée")
        sys.exit(1)

    # ── Bounds depuis GPX si pas de KMZ Livelox ──────────────────────────────
    if llb is None:
        all_lats = [pt.lat for t in tracks for pt in t["points"]]
        all_lons = [pt.lon for t in tracks for pt in t["points"]]
        mn_lat, mx_lat = min(all_lats), max(all_lats)
        mn_lon, mx_lon = min(all_lons), max(all_lons)
        m = 0.25  # marge 25%
        dlat = mx_lat - mn_lat
        dlon = mx_lon - mn_lon
        llb = {
            "north": mx_lat + dlat * m,
            "south": mn_lat - dlat * m,
            "east": mx_lon + dlon * m,
            "west": mn_lon - dlon * m,
            "rotation": 0.0,
        }
        print(f"[INFO] Bounds estimés depuis les GPX (marge 25%)")

    # ── Construire le KML ─────────────────────────────────────────────────────
    kml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        f"  <name>WOC 2025 Puijo — {len(tracks)} coureurs</name>",
        "  <GroundOverlay>",
        "    <name>Carte</name>",
        "    <drawOrder>75</drawOrder>",
        "    <Icon>",
        f"      <href>{img_name}</href>",
        "    </Icon>",
        "    <LatLonBox>",
        f"      <north>{llb['north']:.8f}</north>",
        f"      <south>{llb['south']:.8f}</south>",
        f"      <east>{llb['east']:.8f}</east>",
        f"      <west>{llb['west']:.8f}</west>",
        f"      <rotation>{llb['rotation']:.6f}</rotation>",
        "    </LatLonBox>",
        "  </GroundOverlay>",
        f"  <Folder><name>Traces ({len(tracks)} coureurs)</name>",
    ]

    for i, track in enumerate(tracks):
        color = _COLORS[i % len(_COLORS)]
        coords = " ".join(f"{pt.lon:.6f},{pt.lat:.6f},0" for pt in track["points"])
        kml += [
            "    <Placemark>",
            f"      <name>{_esc(track['name'])}</name>",
            "      <Style><LineStyle>",
            f"        <color>{color}</color><width>2</width>",
            "      </LineStyle></Style>",
            "      <LineString><tessellate>1</tessellate>",
            f"        <coordinates>{coords}</coordinates>",
            "      </LineString>",
            "    </Placemark>",
        ]

    kml += ["  </Folder>", "</Document>", "</kml>"]

    # ── Créer le KMZ ─────────────────────────────────────────────────────────
    with zipfile.ZipFile(out_kmz, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", "\n".join(kml).encode("utf-8"))
        if img_bytes:
            zf.writestr(img_name, img_bytes)

    size_kb = os.path.getsize(out_kmz) // 1024
    print(f"\n[OK] KMZ créé : {out_kmz} ({size_kb} Ko)")
    print(f"     {len(tracks)} traces • carte géoréférencée Livelox (rotation {llb['rotation']:.1f}°)")
    print()


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()
