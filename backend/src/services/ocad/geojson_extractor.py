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
