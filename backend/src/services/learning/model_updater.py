# =============================================
# Mise à jour automatique du modèle ML
# Vérifie Ionos au démarrage, télécharge si nouveau
# =============================================
#
# Flux :
#   1. GET https://[ionos]/model/latest.json
#   2. Compare version avec modèle local
#   3. Si plus récent → télécharge .pkl + vérifie sha256
#   4. Met à jour latest.json local
#   5. MLScorer recharge automatiquement au prochain appel
# =============================================

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import requests

# URL à mettre à jour une fois le domaine Ionos connu
MODEL_REGISTRY_URL = os.getenv(
    "MODEL_REGISTRY_URL",
    "https://aitraceur.vikazim.fr/model/latest.json"
)

MODELS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "models"
LOCAL_LATEST = MODELS_DIR / "latest.json"

TIMEOUT_S = 5  # Ne pas bloquer le démarrage


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _local_version() -> Optional[str]:
    """Retourne la version du modèle local, ou None si absent."""
    if not LOCAL_LATEST.exists():
        return None
    try:
        return json.loads(LOCAL_LATEST.read_text()).get("version")
    except Exception:
        return None


def check_and_download() -> None:
    """
    Vérifie si un modèle plus récent est disponible sur Ionos.
    Télécharge et installe silencieusement si c'est le cas.
    Appelé dans un thread daemon au démarrage — jamais bloquant.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(MODEL_REGISTRY_URL, timeout=TIMEOUT_S)
        resp.raise_for_status()
        remote = resp.json()
    except Exception as e:
        print(f"[ML] Vérification modèle : pas de connexion ou serveur absent ({e})")
        return

    remote_version = remote.get("version")
    local_version = _local_version()

    if not remote_version:
        print("[ML] latest.json distant invalide.")
        return

    if local_version == remote_version:
        print(f"[ML] Modèle à jour (v{local_version}).")
        return

    # Nouveau modèle disponible
    pkl_url = remote.get("url")
    expected_sha256 = remote.get("sha256")
    n_samples = remote.get("n_samples", "?")

    if not pkl_url:
        print("[ML] URL du modèle absent dans latest.json distant.")
        return

    print(f"[ML] Nouveau modèle disponible : v{remote_version} ({n_samples} circuits). Téléchargement...")

    try:
        pkl_resp = requests.get(pkl_url, timeout=60, stream=True)
        pkl_resp.raise_for_status()

        # Nom du fichier local
        filename = pkl_url.split("/")[-1]
        dest = MODELS_DIR / filename

        with open(dest, "wb") as f:
            for chunk in pkl_resp.iter_content(chunk_size=65536):
                f.write(chunk)

        # Vérification intégrité sha256
        if expected_sha256:
            actual = _sha256(dest)
            if actual != expected_sha256:
                dest.unlink(missing_ok=True)
                print(f"[ML] Erreur intégrité sha256 — modèle rejeté.")
                return

        # Mettre à jour le pointeur local
        LOCAL_LATEST.write_text(json.dumps({
            **remote,
            "path": str(dest),
        }))

        # Invalider le cache MLScorer pour forcer le rechargement
        try:
            from .ml_trainer import MLScorer
            MLScorer._model = None
            MLScorer._model_path = None
        except Exception:
            pass

        print(f"[ML] Modèle v{remote_version} installé ({n_samples} circuits, MAE={remote.get('mae', '?')}).")

    except Exception as e:
        print(f"[ML] Échec téléchargement modèle : {e}")
