"""
LRI (Latent Regime Index) -- retrieval layer over a stable geometric manifold.

Charge lri_baseline.json (produit par build_lri_model.py) et expose un singleton
LRIModel pour le retrieval de regime dans le GA.

Architecture :
- LRI est un systeme de retrieval, pas un optimiseur ni un classifieur.
- project() et assign_regime() operent dans l'espace PC1/PC2 uniquement.
- Les centroids 10D ne sont jamais exposes en runtime (regles one-space).
- pca_components est deja flippe dans le JSON (pc1_sign_flip applique une seule fois
  dans build_lri_model.py). Ne pas reflippler ici.
- Si lri_baseline.json absent, get_lri_model() retourne None -- GA standard.

Regimes (k=2) :
- "open"     : high PC1 — circuits azimutaux, peu de guidance lineaire, fort ATTACK_POINT.
- "handrail" : low PC1  — circuits le long des lignes terrain, fort HANDRAIL_FOLLOW.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

import numpy as np


LRI_FEATURE_COLS: tuple[str, ...] = (
    "parallel_affordance", "crossing_density", "exit_clarity",
    "contour_crossing_guidance",
    "HANDRAIL_FOLLOW", "LINE_CROSSING", "ATTACK_POINT",
    "DIRECT_RISK_RUN", "RELIEF_CROSSING_GUIDANCE", "SAFETY_RECOVERY",
)


@dataclass(frozen=True)
class LRIModel:
    pca_mean: np.ndarray              # (10,)
    pca_std: np.ndarray               # (10,)
    pca_components: np.ndarray        # (2, 10) -- Vt2 avec orientation canonique deja appliquee
    cluster_centroids_pc: np.ndarray  # (k, 2) -- espace PC runtime, tries par PC1 desc
    regime_names: dict[str, str]      # {"0": "open", "1": "handrail", ...}
    cluster_semantics_version: int = 1   # audit trail -- ne pas utiliser en runtime
    sklearn_version: str = "unknown"     # version sklearn du fit KMeans

    def project(self, features: np.ndarray) -> np.ndarray:
        """Projette un vecteur 10-dim dans l'espace PC1/PC2 (retrieval space)."""
        scaled = (features - self.pca_mean) / self.pca_std
        return scaled @ self.pca_components.T  # (2,)

    def assign_regime(self, pc_scores: np.ndarray) -> str:
        """Retrieval regime : nearest centroid dans l'espace PC1/PC2."""
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

        # Assertion 1 : feature_cols -- l'ordre des features EST le modele
        if data.get("feature_cols") != list(LRI_FEATURE_COLS):
            raise ValueError(
                f"feature_cols mismatch.\n"
                f"  JSON    : {data.get('feature_cols')}\n"
                f"  Module  : {list(LRI_FEATURE_COLS)}"
            )

        # Assertion 2 : semantic_anchor -- valide l'ordre ET le signe des regimes
        anchor = data.get("semantic_anchor", {})
        if anchor and "open_pc1_mean" in anchor and "handrail_pc1_mean" in anchor:
            o = float(anchor["open_pc1_mean"])
            h = float(anchor["handrail_pc1_mean"])
            if o <= h:
                raise ValueError(
                    f"semantic_anchor inversion detectee : open_pc1={o} <= handrail_pc1={h}. "
                    f"Relancer build_lri_model.py pour regenerer le JSON."
                )
            if o <= 0:
                raise ValueError(
                    f"open_pc1_mean={o} devrait etre > 0 (high PC1 = regime open/attack)."
                )
            if h >= 0:
                raise ValueError(
                    f"handrail_pc1_mean={h} devrait etre < 0 (low PC1 = regime handrail)."
                )

        return cls(
            pca_mean=np.array(data["pca_mean"], dtype=float),
            pca_std=np.array(data["pca_std"], dtype=float),
            pca_components=np.array(data["pca_components"], dtype=float),
            cluster_centroids_pc=np.array(data["cluster_centroids_pc"], dtype=float),
            regime_names=data["regime_names"],
            cluster_semantics_version=data.get("cluster_semantics_version", 0),
            sklearn_version=data.get("sklearn_version", "unknown"),
        )


_LRI_MODEL: LRIModel | None = None


def get_lri_model() -> LRIModel | None:
    """Lazy singleton -- charge une fois depuis lri_baseline.json."""
    global _LRI_MODEL
    if _LRI_MODEL is None:
        path = pathlib.Path(__file__).parent.parent.parent.parent / "data" / "lri_baseline.json"
        if path.exists():
            _LRI_MODEL = LRIModel.load(str(path))
            print(
                f"[LRI] loaded v={_LRI_MODEL.cluster_semantics_version} "
                f"regimes={_LRI_MODEL.available_regimes} "
                f"sklearn={_LRI_MODEL.sklearn_version}",
                flush=True,
            )
    return _LRI_MODEL
