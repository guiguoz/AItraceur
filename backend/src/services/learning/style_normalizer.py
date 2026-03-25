"""
Normalise les couleurs d'une image OCAD (tile service) vers la distribution
MapAnt (sur laquelle patch_scorer_v2 a été entraîné).

Technique : match_histograms (skimage) sur les 3 canaux RGB.
Image de référence : premier PNG trouvé dans data/mapant_cache/ (ou patch neutre).

IMPORTANT : Ce module est utilisé UNIQUEMENT à l'inférence (sprint → HeatmapCache).
            L'entraînement du modèle reste pur MapAnt/RG2 (train_control_scorer.py).
"""
from pathlib import Path
import numpy as np
from PIL import Image

_REF_IMG: "np.ndarray | None" = None  # lazy load


def _load_ref() -> "np.ndarray":
    global _REF_IMG
    if _REF_IMG is None:
        cache_dir = Path(__file__).parent.parent.parent.parent / "data" / "mapant_cache"
        pngs = sorted(cache_dir.glob("**/*.png"))
        if pngs:
            _REF_IMG = np.array(Image.open(pngs[0]).convert("RGB"))
        else:
            # Patch neutre : blanc cassé = couleur MapAnt forêt rapide (fond dominant)
            _REF_IMG = np.full((64, 64, 3), [242, 242, 232], dtype=np.uint8)
    return _REF_IMG


def normalize_ocad_to_mapant(ocad_img: Image.Image) -> Image.Image:
    """
    Aligne l'histogramme RGB de l'image OCAD sur celui d'un patch MapAnt de référence.
    Retourne l'image normalisée (même dimensions que l'entrée).
    Fallback sans modification si skimage est absent.
    """
    try:
        from skimage.exposure import match_histograms  # type: ignore
        src = np.array(ocad_img.convert("RGB"))
        ref = _load_ref()
        matched = match_histograms(src, ref, channel_axis=-1)
        return Image.fromarray(matched.astype(np.uint8))
    except ImportError:
        return ocad_img
