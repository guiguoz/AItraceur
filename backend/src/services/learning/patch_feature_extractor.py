"""
patch_feature_extractor.py — Extraction des 17 features visuelles ISOM pour patches de carte CO.

Module partagé entre :
  - backend/scripts/train_control_scorer.py  (entraînement XGBoost)
  - backend/src/services/learning/ocad_patch_scorer.py  (inférence)

Règle d'or ML : ce code est la source unique de vérité pour l'extraction des features.
Ne jamais modifier ici sans mettre à jour les deux consommateurs.

Feature space (17 dimensions) :
  [0:7]   ISOM couleur global  — full patch 256×256
  [7:14]  ISOM couleur centre  — crop central 64×64 (là où est le poste)
  [14]    edge_density         — fraction pixels Sobel > seuil 20
  [15]    corner_density       — fraction pixels réponse Harris > 1% max
  [16]    entropy              — entropie Shannon normalisée [0,1]

Métriques modèle patch_scorer_v2.pkl (XGBoost, 12 368 patches, multi-clubs UK) :
  AUC-ROC = 0.835  |  F1 = 0.678  |  Recall = 0.746
  Top features : ctr_white > ctr_yellow > ctr_green_dense > ctr_brown > corner_density
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Palette ISOM — (R,G,B) centre + tolérance L∞
# Ordre fixé : identique à l'entraînement — NE PAS CHANGER
# ---------------------------------------------------------------------------
ISOM_PALETTE: dict[str, tuple[tuple[int, int, int], int]] = {
    "brown_relief": ((180, 120, 60), 30),    # courbes de niveau, micro-relief
    "green_dense":  ((80, 140, 80), 35),     # végétation infranchissable
    "green_light":  ((160, 210, 160), 35),   # végétation lente
    "yellow_open":  ((255, 240, 130), 40),   # terrain ouvert
    "blue_water":   ((80, 150, 220), 40),    # eau
    "black_detail": ((50, 50, 50), 40),      # chemins, falaises, blocs
    "white_forest": ((240, 240, 240), 20),   # forêt courante
}

# 17 features : 7 ISOM global + 7 ISOM centre + 3 géométriques
FEATURE_NAMES: list[str] = [
    # Global ISOM (7) — full 256×256 patch
    "brown_relief", "green_dense", "green_light", "yellow_open",
    "blue_water", "black_detail", "white_forest",
    # Center ISOM (7) — crop central 64×64
    "ctr_brown", "ctr_green_dense", "ctr_green_light", "ctr_yellow",
    "ctr_water", "ctr_black", "ctr_white",
    # Géométrie locale (3)
    "edge_density",    # densité contours Sobel (complexité géométrique)
    "corner_density",  # densité coins Harris (intersections, angles)
    "entropy",         # entropie Shannon normalisée (richesse visuelle)
]


def _isom_fracs(pixels: np.ndarray, n: int) -> np.ndarray:
    """
    Matching L∞ vectorisé : assigne chaque pixel à une classe ISOM.

    Args:
        pixels: tableau (N, 3) int16 RGB
        n: nombre total de pixels (= len(pixels))

    Returns:
        (7,) float32 — fraction de pixels dans chaque classe ISOM_PALETTE
    """
    counts = np.zeros(len(ISOM_PALETTE), dtype=np.int32)
    assigned = np.zeros(n, dtype=bool)
    for idx, (_name, (c, tol)) in enumerate(ISOM_PALETTE.items()):
        center = np.array(c, dtype=np.int16)
        dist = np.max(np.abs(pixels - center), axis=1)
        mask = (~assigned) & (dist < tol)
        counts[idx] = mask.sum()
        assigned |= mask
    return (counts / n).astype(np.float32)


def extract_features(img: Image.Image) -> np.ndarray:
    """
    Extraire le vecteur 17-dim depuis un patch PIL Image.

    Temps typique : ~8ms pour un patch 256×256.

    Args:
        img: Image PIL (RGB ou autre mode, converti automatiquement)

    Returns:
        np.ndarray float32 de forme (17,)
          [0:7]   ISOM couleur global
          [7:14]  ISOM couleur centre 64×64
          [14]    edge_density
          [15]    corner_density
          [16]    entropy
    """
    from scipy.ndimage import uniform_filter

    arr = np.array(img.convert("RGB"), dtype=np.int16)   # H×W×3
    h, w, _ = arr.shape

    # 1. ISOM global (7) — full patch
    pixels_full = arr.reshape(-1, 3)
    global_feats = _isom_fracs(pixels_full, h * w)

    # 2. ISOM centre 64×64 (7) — crop central (là où est le poste)
    cy, cx = h // 2, w // 2
    r = 32
    center = arr[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
    nc = center.shape[0] * center.shape[1]
    if nc > 0:
        center_feats = _isom_fracs(center.reshape(-1, 3), nc)
    else:
        center_feats = np.zeros(7, dtype=np.float32)

    # 3. Grayscale pour les features géométriques
    gray = np.mean(arr.astype(np.float32), axis=2)   # H×W float32

    # 4. Edge density — gradient Sobel numpy, seuil 20
    gx = np.gradient(gray, axis=1)
    gy = np.gradient(gray, axis=0)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    edge_density = float((mag > 20.0).mean())

    # 5. Corner density — réponse Harris (structure tensor via uniform_filter)
    Ixx = uniform_filter(gx * gx, size=5)
    Iyy = uniform_filter(gy * gy, size=5)
    Ixy = uniform_filter(gx * gy, size=5)
    det = Ixx * Iyy - Ixy * Ixy
    trace = Ixx + Iyy
    R = det - 0.05 * trace ** 2
    r_max = R.max()
    corner_density = float((R > r_max * 0.01).mean()) if r_max > 0 else 0.0

    # 6. Entropie Shannon normalisée [0,1]
    gray_u8 = gray.clip(0, 255).astype(np.uint8).flatten()
    counts_hist = np.bincount(gray_u8, minlength=256).astype(np.float64)
    p = counts_hist / counts_hist.sum()
    p_nz = p[p > 0]
    entropy = float(-np.sum(p_nz * np.log(p_nz)) / np.log(256))

    return np.concatenate([
        global_feats,
        center_feats,
        [edge_density, corner_density, entropy],
    ]).astype(np.float32)
