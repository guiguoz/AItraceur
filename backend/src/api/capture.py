"""Capture optionnelle des corps de requête de génération.

Si AITRACEUR_CAPTURE_DIR est défini, chaque appel à capture_request() écrit le corps
JSON sous <dir>/<kind>_<AAAAMMJJTHHMMSSZ>_<sha8>.json et renvoie le chemin.
Sinon, ne fait rien et renvoie None.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def capture_request(kind: str, body: dict) -> Path | None:
    """Écrit le corps de requête en JSON si AITRACEUR_CAPTURE_DIR est défini.

    Args:
        kind: "circuit" ou "sprint".
        body: corps de la requête FastAPI (dict).

    Returns:
        Chemin du fichier écrit, ou None si la capture est désactivée.
    """
    capture_dir = os.environ.get("AITRACEUR_CAPTURE_DIR")
    if not capture_dir:
        return None

    out_dir = Path(capture_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(body, ensure_ascii=False, sort_keys=True)
    sha8 = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{kind}_{ts}_{sha8}.json"
    path = out_dir / filename
    path.write_text(payload, encoding="utf-8")
    return path
