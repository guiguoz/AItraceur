"""
spatial_filter — filtrage spatial des paires candidats via KDTree.

Remplace l'énumération O(n²) par une recherche K plus proches voisins.
Pour 500 candidats et k=20, on passe de 250 000 paires à ~10 000 paires
orientées (×2 pour la symétrie orientée), soit ≈ 96 % de paires évitées.

Les paires sont ORIENTÉES (A→B ≠ B→A) car la topographie est asymétrique
(montée vs descente).

Exemple :
    from src.aitraceur.matrix.spatial_filter import build_candidate_pairs

    pairs = build_candidate_pairs(candidates, k_neighbors=15, max_distance=1500.0)
    # pairs = [(c1, c2), (c2, c1), (c1, c3), ...]
"""
from __future__ import annotations

from typing import List, Tuple

try:
    import numpy as np
    from scipy.spatial import cKDTree
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False


def build_candidate_pairs(
    candidates: List[object],
    k_neighbors: int = 20,
    max_distance: float = 2500.0,
) -> List[Tuple[object, object]]:
    """
    Retourne les paires orientées (c1, c2) à calculer via A*.

    Pour chaque candidat, on interroge le KDTree pour ses K plus proches
    voisins dans un rayon `max_distance`. Chaque paire non ordonnée {i, j}
    génère exactement deux paires orientées : (i→j) et (j→i).

    Args:
        candidates:    Liste de ControlCandidate (attributs .x et .y requis).
        k_neighbors:   Nombre de voisins par candidat (hors soi-même).
        max_distance:  Rayon de coupure en mètres.

    Returns:
        Liste de (c1, c2) orientées, sans doublons.

    Raises:
        ImportError: si scipy ou numpy ne sont pas installés.
    """
    if not _SCIPY_OK:
        raise ImportError("scipy et numpy sont requis pour build_candidate_pairs.")

    if not candidates:
        return []

    n = len(candidates)

    # Extraction des coordonnées (x, y) projetées
    coords = np.array([(c.x, c.y) for c in candidates], dtype=np.float64)  # type: ignore[attr-defined]

    # Construction du KDTree — O(n log n)
    tree = cKDTree(coords)

    # k+1 car la requête inclut le point lui-même (distance = 0)
    k = min(k_neighbors + 1, n)
    distances, indices = tree.query(coords, k=k, workers=1)

    # Collecte des paires non ordonnées → deux paires orientées chacune
    unordered_seen: set[Tuple[int, int]] = set()
    pairs: List[Tuple[object, object]] = []

    for i in range(n):
        row_dists = distances[i] if n > 1 else [distances[i]]
        row_idxs  = indices[i]  if n > 1 else [indices[i]]

        for j, d in zip(row_idxs, row_dists):
            j = int(j)
            if j == i:
                continue
            if d > max_distance:
                # KDTree retourne les voisins par distance croissante ;
                # les suivants seront encore plus loin → on peut couper
                break

            # Clé non ordonnée pour dédupliquer les paires {i, j}
            key = (min(i, j), max(i, j))
            if key not in unordered_seen:
                unordered_seen.add(key)
                pairs.append((candidates[i], candidates[j]))   # i → j
                pairs.append((candidates[j], candidates[i]))   # j → i (asymétrie terrain)

    return pairs
