"""
Couche 3 — Matrice de coûts entre ControlCandidate.

Deux modes de construction :

  Mode legacy (rétrocompatible) :
      cm = CostMatrix(candidates=candidates, _data=np_array)
      cm.cost(ca, cb)          # O(1) via numpy
      cm.feasible_pairs(ca)    # triés par coût croissant

  Mode scalable 3D (KDTree + parallèle) :
      builder = CostMatrix(elevation_provider=ep, veg_grid=vg, cell_size_m=3.0)
      builder.build_cost_matrix(candidates, n_workers=4, k_neighbors=20)
      builder.cost(ca, cb)     # O(1) via numpy post-construction

  Dégradation silencieuse :
      Si elevation_provider / veg_grid sont absents, le coût est calculé
      comme distance euclidienne / vitesse_constante (modèle 2D).

Exemple :
    cm = build_cost_matrix(candidates, movement_model, profile)   # API legacy
    cost = cm.cost(cand_a, cand_b)
    pairs = cm.feasible_pairs(cand_a, max_leg_m=800)
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False

from ..controls.candidate import ControlCandidate
from ..navigation.movement import MovementModel
from ..profiles import CourseProfile
from .leg_cache import LegCache
from .spatial_filter import build_candidate_pairs

_log = logging.getLogger(__name__)

# Sentinelle pour "coût infini / impossible"
_INF = float("inf")

# Vitesse de repli si pas de modèle 3D (12 km/h en m/s)
_FALLBACK_SPEED_MPS = 12.0 / 3.6

# Taille des lots pour ThreadPoolExecutor
_CHUNK_SIZE = 64


# ---------------------------------------------------------------------------
# CostMatrix
# ---------------------------------------------------------------------------

class CostMatrix:
    """
    Matrice de coûts de déplacement entre tous les candidats.

    Constructeur legacy :
        CostMatrix(candidates=..., _data=np_array)

    Constructeur scalable 3D :
        CostMatrix(elevation_provider=..., veg_grid=..., cell_size_m=3.0)
        puis appel à build_cost_matrix(candidates, ...)

    Dans les deux cas, cost(a, b), feasible_pairs(a), coverage_ratio() etc.
    sont disponibles une fois la matrice construite.
    """

    def __init__(
        self,
        candidates: Optional[List[ControlCandidate]] = None,
        _data: Optional["np.ndarray"] = None,
        *,
        elevation_provider: Optional[object] = None,
        veg_grid: Optional["np.ndarray"] = None,
        cell_size_m: float = 3.0,
    ) -> None:
        # ------------------------------------------------------------------
        # Mode legacy : CostMatrix(candidates=..., _data=...)
        # ------------------------------------------------------------------
        if candidates is not None and _data is not None:
            self.candidates: List[ControlCandidate] = list(candidates)
            self._data: Optional["np.ndarray"] = _data
            self._index: dict[str, int] = {c.id: i for i, c in enumerate(self.candidates)}
            self._cache = LegCache()
            self._terrain_model = None
            self._elevation_provider = None
            self._fallback_speed_mps = _FALLBACK_SPEED_MPS
            return

        # ------------------------------------------------------------------
        # Mode scalable 3D : CostMatrix(elevation_provider=..., ...)
        # ------------------------------------------------------------------
        self.candidates = []
        self._data = None
        self._index = {}
        self._cache = LegCache()
        self._elevation_provider = elevation_provider
        self._fallback_speed_mps = _FALLBACK_SPEED_MPS

        # Instanciation du modèle 3D Tobler si données disponibles
        self._terrain_model = None
        if elevation_provider is not None and veg_grid is not None:
            try:
                from ..navigation.terrain_3d import TerrainMovementCost
                elev_grid = elevation_provider.get_elevation_grid()  # type: ignore[attr-defined]
                self._terrain_model = TerrainMovementCost(
                    elev_grid,
                    veg_grid,
                    cell_size=cell_size_m,
                )
                self._cell_size_m = cell_size_m
            except Exception as exc:
                _log.warning("Modèle 3D non disponible, repli sur 2D : %s", exc)

    # ------------------------------------------------------------------
    # Construction scalable (KDTree + parallèle)
    # ------------------------------------------------------------------

    def build_cost_matrix(
        self,
        candidates: List[ControlCandidate],
        n_workers: int = 4,
        k_neighbors: int = 20,
        max_distance_m: float = 2500.0,
    ) -> "CostMatrix":
        """
        Construit la matrice via KDTree + exécution parallèle par lots.

        Étapes :
          1. Filtrage spatial → paires orientées via build_candidate_pairs.
          2. Exclusion des paires déjà dans le cache (reprise possible).
          3. Découpage en lots (_CHUNK_SIZE) → ThreadPoolExecutor.
          4. Construction de la matrice numpy depuis le cache.

        Args:
            candidates:     Liste de ControlCandidate.
            n_workers:      Threads parallèles (défaut : 4).
            k_neighbors:    Voisins max par candidat (défaut : 20).
            max_distance_m: Rayon de coupure spatial (défaut : 2 500 m).

        Returns:
            self (pour chaînage fluent).
        """
        if not _NP_OK:
            raise ImportError("numpy est requis pour build_cost_matrix.")

        self.candidates = list(candidates)
        self._index = {c.id: i for i, c in enumerate(self.candidates)}

        # 1. Filtrage spatial → paires orientées
        all_pairs = build_candidate_pairs(
            candidates, k_neighbors=k_neighbors, max_distance=max_distance_m
        )
        _log.info(
            "build_cost_matrix : %d candidats → %d paires orientées (k=%d, r=%.0fm)",
            len(candidates), len(all_pairs), k_neighbors, max_distance_m,
        )

        # 2. Filtrer les paires déjà en cache (reprise)
        uncached = [
            (c1, c2) for c1, c2 in all_pairs
            if not self._cache.contains(c1.id, c2.id)
        ]
        _log.info("%d paires à calculer (%d déjà en cache)", len(uncached), len(all_pairs) - len(uncached))

        # 3. Découpage en lots + exécution parallèle
        chunks = [
            uncached[i: i + _CHUNK_SIZE]
            for i in range(0, len(uncached), _CHUNK_SIZE)
        ]

        if chunks:
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                futures = {pool.submit(self._process_batch, chunk): idx for idx, chunk in enumerate(chunks)}
                done = 0
                for future in as_completed(futures):
                    done += 1
                    try:
                        future.result()
                    except Exception as exc:
                        _log.error("Lot %d/%d échoué : %s", done, len(chunks), exc)

        # 4. Conversion cache → matrice numpy (pour rétrocompatibilité)
        self._data = self._build_numpy_matrix()
        _log.info(
            "build_cost_matrix terminé : couverture %.1f%%",
            self.coverage_ratio() * 100,
        )
        return self

    def _process_batch(self, batch: List[Tuple]) -> List[Tuple]:
        """
        Traite un lot de paires (c1, c2), stocke les résultats dans le cache.

        Thread-safe : le LegCache utilise un Lock interne.
        Les exceptions individuelles sont loguées sans interrompre le lot.

        Args:
            batch: Liste de (ControlCandidate, ControlCandidate).

        Returns:
            Liste vide (résultats stockés dans self._cache).
        """
        for c1, c2 in batch:
            try:
                c1_id, c2_id, dist, time_s, climb_m = self._compute_pair(c1, c2)
                self._cache.set(c1_id, c2_id, dist, time_s, climb_m)
            except Exception as exc:
                _log.warning("Paire %s→%s ignorée : %s", c1.id, c2.id, exc)  # type: ignore[attr-defined]
        return []

    def _compute_pair(
        self,
        c1: ControlCandidate,
        c2: ControlCandidate,
    ) -> Tuple[str, str, float, float, float]:
        """
        Calcule (dist_m, time_s, climb_m) pour une paire orientée.

        Mode 3D (elevation_provider + veg_grid) :
            Convertit (x, y) → (row, col) puis appelle shortest_path_with_climb.
            Repli 2D si aucun chemin trouvé (time=inf).

        Mode 2D (fallback) :
            dist = distance euclidienne, time = dist / vitesse_constante, climb = 0.

        Args:
            c1, c2: Candidats source et destination.

        Returns:
            (c1.id, c2.id, dist_m, time_s, climb_m)
        """
        dist = math.hypot(c2.x - c1.x, c2.y - c1.y)  # type: ignore[attr-defined]

        if self._terrain_model is not None and self._elevation_provider is not None:
            from ..navigation.terrain_3d import shortest_path_with_climb
            start_rc = self._coords_to_cell(c1.x, c1.y)  # type: ignore[attr-defined]
            end_rc   = self._coords_to_cell(c2.x, c2.y)  # type: ignore[attr-defined]
            time_s, climb_m = shortest_path_with_climb(start_rc, end_rc, self._terrain_model)

            if not math.isfinite(time_s):
                # Pas de chemin 3D → repli vitesse constante
                time_s = dist / self._fallback_speed_mps
                climb_m = 0.0
        else:
            time_s = dist / self._fallback_speed_mps
            climb_m = 0.0

        return (c1.id, c2.id, dist, time_s, climb_m)  # type: ignore[attr-defined]

    def _coords_to_cell(self, x: float, y: float) -> Tuple[int, int]:
        """Convertit des coordonnées monde en (row, col) pour la grille terrain."""
        row_f, col_f = self._elevation_provider._to_rowcol_float(x, y)  # type: ignore[attr-defined]
        h, w = self._terrain_model.shape                                  # type: ignore[attr-defined]
        return (max(0, min(int(row_f), h - 1)), max(0, min(int(col_f), w - 1)))

    def _build_numpy_matrix(self) -> "np.ndarray":
        """Construit la matrice numpy (N×N float32) depuis le LegCache."""
        n = len(self.candidates)
        data = np.full((n, n), _INF, dtype=np.float32)
        np.fill_diagonal(data, 0.0)

        for i, c1 in enumerate(self.candidates):
            for j, c2 in enumerate(self.candidates):
                if i == j:
                    continue
                cached = self._cache.get(c1.id, c2.id)
                if cached is not None and isinstance(cached, tuple):
                    _dist, time_s, _climb = cached
                    if math.isfinite(time_s):
                        data[i, j] = float(time_s)
        return data

    # ------------------------------------------------------------------
    # API publique — requêtes (rétrocompatibles)
    # ------------------------------------------------------------------

    def cost(
        self,
        a: ControlCandidate,
        b: ControlCandidate,
    ) -> Optional[float]:
        """Retourne le coût de la jambe a→b, ou None si impossible."""
        ia = self._index.get(a.id)
        ib = self._index.get(b.id)
        if ia is None or ib is None:
            return None
        if self._data is None:
            return None
        v = float(self._data[ia, ib])
        return None if v == _INF else v

    def cost_by_idx(self, i: int, j: int) -> Optional[float]:
        """Accès direct par indices (plus rapide)."""
        if self._data is None:
            return None
        n = len(self.candidates)
        if not (0 <= i < n and 0 <= j < n):
            return None
        v = float(self._data[i, j])
        return None if v == _INF else v

    def idx(self, candidate: ControlCandidate) -> Optional[int]:
        """Indice d'un candidat dans la matrice."""
        return self._index.get(candidate.id)

    def feasible_pairs(
        self,
        origin: ControlCandidate,
        *,
        max_cost: Optional[float] = None,
        max_dist_m: Optional[float] = None,
    ) -> list[tuple[ControlCandidate, float]]:
        """
        Retourne les candidats accessibles depuis `origin`, triés par coût.

        Args:
            origin:     Candidat de départ.
            max_cost:   Filtre sur le coût maximum.
            max_dist_m: Filtre sur la distance euclidienne max (pré-filtre rapide).

        Returns:
            Liste de (ControlCandidate, coût), triée par coût croissant.
        """
        ia = self._index.get(origin.id)
        if ia is None or self._data is None:
            return []

        result = []
        for ib, cand in enumerate(self.candidates):
            if ib == ia:
                continue
            if max_dist_m is not None:
                dist = origin.geom.distance(cand.geom)
                if dist > max_dist_m:
                    continue
            v = float(self._data[ia, ib])
            if v == _INF:
                continue
            if max_cost is not None and v > max_cost:
                continue
            result.append((cand, v))

        result.sort(key=lambda x: x[1])
        return result

    def direct_distance(self, a: ControlCandidate, b: ControlCandidate) -> float:
        """Distance euclidienne entre deux candidats (mètres)."""
        return a.geom.distance(b.geom)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def n(self) -> int:
        return len(self.candidates)

    def coverage_ratio(self) -> float:
        """Fraction de paires faisables (hors diagonale)."""
        if not _NP_OK or self._data is None or len(self.candidates) < 2:
            return 0.0
        n = len(self.candidates)
        finite = float(np.sum(self._data != _INF)) - n   # enlève diagonale
        total = n * (n - 1)
        return finite / total if total > 0 else 0.0

    def __repr__(self) -> str:
        return (
            f"CostMatrix(n={len(self.candidates)}, "
            f"coverage={self.coverage_ratio():.1%})"
        )


# ---------------------------------------------------------------------------
# Fonction de construction legacy (rétrocompatible)
# ---------------------------------------------------------------------------

def _compute_row(
    i: int,
    candidates: list,
    movement_model: object,
    max_leg: float,
) -> List[Tuple[int, int, float]]:
    """
    Calcule toutes les paires (i, j) avec j > i pour la ligne i.

    Thread-safe : aucun état partagé n'est modifié.
    """
    results: List[Tuple[int, int, float]] = []
    ca = candidates[i]
    for j in range(i + 1, len(candidates)):
        cb = candidates[j]
        direct = ca.geom.distance(cb.geom)
        if direct > max_leg:
            continue
        cost = movement_model.compute_cost(ca.geom, cb.geom)  # type: ignore[attr-defined]
        if cost is not None and math.isfinite(cost):
            results.append((i, j, float(cost)))
    return results


def build_cost_matrix(
    candidates: list[ControlCandidate],
    movement_model: MovementModel,
    profile: CourseProfile,
    *,
    max_leg_m: Optional[float] = None,
    progress_callback: Optional[Callable] = None,
    n_workers: int = 1,
) -> CostMatrix:
    """
    Construit la CostMatrix (mode legacy) pour un ensemble de candidats.

    Optimisations :
      - Pré-filtre euclidien : seules les paires ≤ max_leg_m sont calculées.
      - Parallélisation optionnelle par ligne via ThreadPoolExecutor.
      - La matrice est symétrique (cost[i,j] == cost[j,i]).

    Args:
        candidates:        Liste de ControlCandidate.
        movement_model:    MovementModel pour le calcul de coût 2D.
        profile:           Profil de course (fournit leg_m_max).
        max_leg_m:         Seuil euclidien (m). Défaut : 1.5 × leg_m_max.
        progress_callback: Appelé avec (done, total) après chaque ligne.
        n_workers:         Threads. 1 = séquentiel.

    Returns:
        CostMatrix construite (mode legacy, symétrique).
    """
    if not _NP_OK:
        raise ImportError("numpy est requis pour build_cost_matrix.")

    n = len(candidates)
    if n == 0:
        return CostMatrix(
            candidates=[],
            _data=np.zeros((0, 0), dtype=np.float32),
        )

    _max_leg = max_leg_m or profile.targets.leg_m_max * 1.5
    data = np.full((n, n), _INF, dtype=np.float32)
    np.fill_diagonal(data, 0.0)

    if n_workers <= 1:
        for i in range(n):
            row_results = _compute_row(i, candidates, movement_model, _max_leg)
            for ri, rj, rc in row_results:
                data[ri, rj] = data[rj, ri] = rc
            if progress_callback is not None:
                progress_callback(i + 1, n)
    else:
        done = 0
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_compute_row, i, candidates, movement_model, _max_leg): i
                for i in range(n)
            }
            for future in as_completed(futures):
                row_results = future.result()
                for ri, rj, rc in row_results:
                    data[ri, rj] = data[rj, ri] = rc
                done += 1
                if progress_callback is not None:
                    progress_callback(done, n)

    return CostMatrix(candidates=candidates, _data=data)
