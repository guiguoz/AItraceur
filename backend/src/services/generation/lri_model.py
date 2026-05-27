"""
LRI (Latent Regime Index) model -- Phase C.

Charge lri_baseline.json (produit par build_lri_model.py) et expose
un singleton LRIModel pour l'assignation de regime dans le GA.

Regles architecturales :
- project() et assign_regime() operent dans l'espace PC1/PC2 uniquement.
- Les centroids 10D ne sont jamais exposes en runtime.
- pca_components est deja flippe dans le JSON (pc1_sign_flip applique une seule fois
  dans build_lri_model.py). Ne pas reflippler ici.
- Si lri_baseline.json absent, get_lri_model() retourne None -- comportement GA standard.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LRIModel:
    pca_mean: np.ndarray           # (10,)
    pca_std: np.ndarray            # (10,)
    pca_components: np.ndarray     # (2, 10) -- Vt2 avec orientation canonique deja appliquee
    cluster_centroids_pc: np.ndarray  # (k, 2) -- espace PC runtime
    regime_names: dict[str, str]   # {"0": "regime_0", "1": "regime_1", ...}

    def project(self, features: np.ndarray) -> np.ndarray:
        """Projette un vecteur 10-dim dans l'espace PC1/PC2."""
        scaled = (features - self.pca_mean) / self.pca_std
        return scaled @ self.pca_components.T  # (2,)

    def assign_regime(self, pc_scores: np.ndarray) -> str:
        """Retourne le nom du regime le plus proche (nearest centroid PC)."""
        dists = np.linalg.norm(self.cluster_centroids_pc - pc_scores, axis=1)
        idx = int(np.argmin(dists))
        return self.regime_names.get(str(idx), f"regime_{idx}")

    @property
    def available_regimes(self) -> list[str]:
        return list(self.regime_names.values())

    @classmethod
    def load(cls, path: str) -> "LRIModel":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            pca_mean=np.array(data["pca_mean"], dtype=float),
            pca_std=np.array(data["pca_std"], dtype=float),
            pca_components=np.array(data["pca_components"], dtype=float),
            cluster_centroids_pc=np.array(data["cluster_centroids_pc"], dtype=float),
            regime_names=data["regime_names"],
        )


_LRI_MODEL: LRIModel | None = None


def get_lri_model() -> LRIModel | None:
    """Lazy singleton -- charge une fois depuis lri_baseline.json."""
    global _LRI_MODEL
    if _LRI_MODEL is None:
        path = pathlib.Path(__file__).parent.parent.parent.parent / "data" / "lri_baseline.json"
        if path.exists():
            _LRI_MODEL = LRIModel.load(str(path))
    return _LRI_MODEL
