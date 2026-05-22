# =============================================
# geojson_extractor.py
# Extrait le GeoJSON terrain depuis un fichier OCAD (.ocd)
# via ocad2geojson (Node.js subprocess)
# =============================================
#
# Anonymisation :
#   - Les coordonnées sont recentrées sur (0,0) par le script JS
#   - Seul le code ISOM (sym) est conservé dans les propriétés
#   - Le fichier OCD temporaire est supprimé immédiatement après
# =============================================

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional

# Chemin vers le script Node.js (relatif à ce fichier)
_EXTRACT_JS = Path(__file__).parent.parent.parent.parent / "tile-service" / "extract_geojson.js"


def extract_geojson_from_ocd(ocd_bytes: bytes) -> Optional[List[Dict]]:
    """
    Extrait les features GeoJSON terrain depuis des bytes OCD.

    Args:
        ocd_bytes: Contenu binaire du fichier .ocd

    Returns:
        Liste de features GeoJSON (propriétés : {sym}), coordonnées recentrées sur (0,0)
        None si l'extraction échoue (Node.js absent, fichier invalide, etc.)
    """
    if not _EXTRACT_JS.exists():
        print(f"[OCAD] Script extract_geojson.js introuvable : {_EXTRACT_JS}")
        return None

    # Écrire le fichier OCD dans un temp file
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ocd", delete=False) as f:
            f.write(ocd_bytes)
            tmp = f.name

        result = subprocess.run(
            ["node", str(_EXTRACT_JS), tmp],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            print(f"[OCAD] Erreur extract_geojson.js : {result.stderr.strip()}")
            return None

        geojson = json.loads(result.stdout)
        features = geojson.get("features", [])
        print(f"[OCAD] Extraction OK : {len(features)} features terrain")
        return features

    except subprocess.TimeoutExpired:
        print("[OCAD] Timeout — fichier OCD trop lourd ?")
        return None
    except json.JSONDecodeError as e:
        print(f"[OCAD] JSON invalide depuis Node.js : {e}")
        return None
    except FileNotFoundError:
        print("[OCAD] Node.js introuvable — installer Node.js ou ajouter au PATH")
        return None
    except Exception as e:
        print(f"[OCAD] Erreur inattendue : {e}")
        return None
    finally:
        # Supprimer le temp file dans tous les cas
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass


# Codes ISOM à extraire pour les segments de navigation (termes N, O, P)
_LINE_SEG_CODES = {101, 102, 103, 201, 215, 305, 306, 501, 502, 503, 504, 505, 506, 507, 508, 516}


def extract_line_segments(features: List[Dict], codes: Optional[set] = None) -> List[Dict]:
    """
    Extrait les segments de LineString OCAD pertinents pour l'analyse des jambes.

    Args:
        features: Liste de features GeoJSON (depuis extract_geojson_from_ocd)
        codes: Set de codes ISOM à retenir (défaut : _LINE_SEG_CODES)

    Returns:
        Liste de segments [{p0: [lng, lat], p1: [lng, lat], isom_code: int}]
    """
    if codes is None:
        codes = _LINE_SEG_CODES

    segments: List[Dict] = []
    for feat in features or []:
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            continue
        props = feat.get("properties", {})
        sym = props.get("sym", 0)
        try:
            code = int(sym) // 1000 if int(sym) > 10000 else int(sym)
        except (TypeError, ValueError):
            continue
        if code not in codes:
            continue
        coords = geom.get("coordinates", [])
        for i in range(len(coords) - 1):
            p0, p1 = coords[i], coords[i + 1]
            if len(p0) >= 2 and len(p1) >= 2:
                segments.append({"p0": [p0[0], p0[1]], "p1": [p1[0], p1[1]], "isom_code": code})
    return segments
