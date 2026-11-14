"""
LegCache — cache thread-safe pour les legs pré-calculés.

Deux usages coexistent dans le même dictionnaire :
  - Legs (objets Leg) : mis en cache via put()/get_or_compute() — usage SA/GA.
  - Métriques brutes (dist, time, climb) : mis en cache via set() — usage CostMatrix.

Le Lock garantit la sécurité dans un contexte ThreadPoolExecutor.

Exemple :
    cache = LegCache()
    cache.put(leg)
    leg2 = cache.get("c1", "c2")          # O(1) — retourne Leg ou None

    # Usage CostMatrix (métriques brutes) :
    cache.set("c1", "c2", 312.4, 48.2, 5.0)
    dist, time, climb = cache.get("c1", "c2")
"""
from __future__ import annotations

import threading
from typing import Any, Optional, Tuple, Union

from ..model.leg import Leg, compute_leg_features


class LegCache:
    """
    Cache orienté (A→B ≠ B→A), 100 % thread-safe via threading.Lock.

    La clé est un tuple (start_id, end_id) ; les valeurs peuvent être :
      - un objet Leg (API classique put/get_or_compute)
      - un tuple (dist, time, climb) de float (API CostMatrix set/get/contains)

    Attributes:
        _cache: dictionnaire interne.
        _lock:  verrou exclusif pour toutes les opérations de lecture/écriture.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[Any, Any], Any] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # API CostMatrix — métriques brutes (dist, time, climb)
    # ------------------------------------------------------------------

    def get(self, start_id: Any, end_id: Any) -> Optional[Any]:
        """
        Retourne la valeur mémorisée pour (start_id → end_id), ou None.

        La valeur peut être un Leg ou un tuple (dist, time, climb) selon
        la méthode d'insertion utilisée.
        """
        with self._lock:
            return self._cache.get((start_id, end_id))

    def set(
        self,
        start_id: Any,
        end_id: Any,
        dist: float,
        time: float,
        climb: float,
    ) -> None:
        """Stocke une métrique brute (dist m, time s, climb m) pour (start_id → end_id)."""
        with self._lock:
            self._cache[(start_id, end_id)] = (dist, time, climb)

    def contains(self, start_id: Any, end_id: Any) -> bool:
        """True si la paire (start_id → end_id) est présente dans le cache."""
        with self._lock:
            return (start_id, end_id) in self._cache

    # ------------------------------------------------------------------
    # API classique — objets Leg
    # ------------------------------------------------------------------

    def get_or_compute(
        self,
        start: object,
        end: object,
        cost_matrix: Optional[object] = None,
        *,
        prev_bearing: Optional[float] = None,
        base_speed_m_per_min: float = 6.0,
    ) -> Leg:
        """Retourne le Leg depuis le cache, ou le calcule et le mémorise."""
        key = (start.id, end.id)  # type: ignore[attr-defined]
        with self._lock:
            cached = self._cache.get(key)
        # Doit être un Leg (pas un tuple de métriques brutes)
        if isinstance(cached, Leg):
            return cached
        leg = compute_leg_features(
            start,
            end,
            cost_matrix,
            prev_bearing=prev_bearing,
            base_speed_m_per_min=base_speed_m_per_min,
        )
        with self._lock:
            self._cache[key] = leg
        return leg

    def put(self, leg: Leg) -> None:
        """Insère (ou remplace) un Leg dans le cache."""
        with self._lock:
            self._cache[(leg.start_id, leg.end_id)] = leg

    def invalidate(self, control_id: str) -> int:
        """
        Supprime toutes les entrées impliquant control_id.

        Retourne le nombre d'entrées supprimées.
        """
        with self._lock:
            to_remove = [
                k for k in self._cache
                if k[0] == control_id or k[1] == control_id
            ]
            for k in to_remove:
                del self._cache[k]
            return len(to_remove)

    def clear(self) -> None:
        """Vide entièrement le cache."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __repr__(self) -> str:
        with self._lock:
            n = len(self._cache)
        return f"LegCache(entries={n})"
