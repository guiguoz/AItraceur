"""
Leg — liaison entre deux postes, qualifiée selon les critères métier du traceur.

Le Leg est l'objet central du scoring dynamique : c'est la "jambe" qui relie
deux postes consécutifs et qualifie le choix d'itinéraire, la difficulté de
navigation et le risque d'erreur associés.

Champs 3D (optionnels, calculés via TerrainMovementCost) :
  - climb_m             : dénivelé positif sur le chemin optimal (m)
  - travel_time_seconds : temps de parcours en secondes (terrain réel)
  - km_effort           : propriété dérivée (distance_km + climb/100)

Exemple :
    leg = compute_leg_features(start, end, cost_matrix)
    print(leg.route_choice_complexity)   # 0.30 = détour modéré
    print(leg.km_effort)                 # 0.82 = effort équivalent 820 m plat
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..navigation.terrain_3d import TerrainMovementCost
    from ..navigation.elevation import ElevationProvider


@dataclass(frozen=True)
class Leg:
    """
    Liaison entre deux postes, qualifiée selon les critères du traceur IOF/FFCO.

    Attributes:
        start_id:                ID du poste de départ.
        end_id:                  ID du poste d'arrivée.
        distance:                Distance à vol d'oiseau 2D (m).
        bearing_deg:             Azimut de la jambe (0–360°, Nord = 0).
        bearing_change_deg:      Changement de cap depuis la jambe précédente (0–180°).
                                 0 si première jambe.
        route_choice_complexity: Complexité du choix d'itinéraire [0–1].
        runnability:             Facilité de déplacement [0–1].
        technical_difficulty:    Difficulté de navigation [0–1].
        risk_level:              Probabilité d'erreur [0–1].
        travel_time:             Temps estimé (minutes) — calcul 2D basique.
        cost:                    Coût MovementModel brut (None = non calculé).
        climb_m:                 Dénivelé positif cumulé sur le chemin optimal (m).
                                 0.0 si le modèle 3D n'est pas disponible.
        travel_time_seconds:     Temps de parcours (secondes) via modèle 3D Tobler.
                                 0.0 si le modèle 3D n'est pas disponible.
    """
    start_id: str
    end_id: str
    distance: float
    bearing_deg: float
    bearing_change_deg: float
    route_choice_complexity: float
    runnability: float
    technical_difficulty: float
    risk_level: float
    travel_time: Optional[float] = None
    cost: Optional[float] = None
    # Champs 3D — optionnels, zéro par défaut (rétro-compatibles)
    climb_m: float = 0.0
    travel_time_seconds: float = 0.0

    # ------------------------------------------------------------------
    # Propriétés calculées
    # ------------------------------------------------------------------

    @property
    def distance_2d(self) -> float:
        """Alias de `distance` — distance à vol d'oiseau 2D (m)."""
        return self.distance

    @property
    def km_effort(self) -> float:
        """
        Distance-effort selon la règle IOF (km équivalent plat).

        km_effort = distance_2d / 1000  +  climb_m / 100

        Un mètre de dénivelé positif équivaut à 10 m plats (règle empirique CO).
        """
        return (self.distance / 1000.0) + (self.climb_m / 100.0)


# ---------------------------------------------------------------------------
# Fonction de calcul
# ---------------------------------------------------------------------------

def compute_leg_features(
    start: object,             # ControlCandidate
    end: object,               # ControlCandidate
    cost_matrix: Optional[object] = None,   # CostMatrix
    *,
    prev_bearing: Optional[float] = None,
    base_speed_m_per_min: float = 6.0,
    terrain_model: Optional["TerrainMovementCost"] = None,
    elevation_provider: Optional["ElevationProvider"] = None,
    cell_size_m: float = 5.0,
) -> Leg:
    """
    Calcule les propriétés métier d'une liaison entre deux postes.

    Lorsque cost_matrix est None, les propriétés basées sur le coût réel
    (route_choice_complexity, runnability) utilisent des valeurs neutres.

    Si terrain_model est fourni, le dénivelé et le temps en secondes sont
    calculés via A* Tobler (shortest_path_with_climb). Sinon, climb_m=0
    et travel_time_seconds=0.

    Args:
        start:               Poste de départ (ControlCandidate).
        end:                 Poste d'arrivée (ControlCandidate).
        cost_matrix:         Matrice de coûts 2D (optionnel).
        prev_bearing:        Azimut de la jambe précédente (degrés).
        base_speed_m_per_min: Vitesse de référence (m/min) pour travel_time.
        terrain_model:       TerrainMovementCost 3D (optionnel).
        elevation_provider:  ElevationProvider pour convertir coords → cellule.
        cell_size_m:         Résolution de la grille terrain (m).

    Returns:
        Leg avec toutes les propriétés métier renseignées.
    """
    dx = end.x - start.x      # type: ignore[attr-defined]
    dy = end.y - start.y      # type: ignore[attr-defined]
    distance = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dx, dy)) % 360.0

    # Changement de cap vs jambe précédente
    if prev_bearing is not None:
        delta = abs(bearing - prev_bearing) % 360.0
        bearing_change = min(delta, 360.0 - delta)
    else:
        bearing_change = 0.0

    # Coût depuis la matrice 2D (None si non calculé)
    cost: Optional[float] = None
    if cost_matrix is not None:
        cost = cost_matrix.cost(start, end)  # type: ignore[attr-defined]

    # Complexité du choix d'itinéraire : ratio détour / distance directe
    if cost is not None and distance > 1.0:
        detour_ratio = (cost - distance) / distance
        route_choice_complexity = min(1.0, max(0.0, detour_ratio * 2.0))
    else:
        route_choice_complexity = 0.0

    # Courabilité : fraction distance directe / coût réel
    if cost is not None and cost > 0.0:
        runnability = min(1.0, distance / cost)
    else:
        runnability = 0.8

    # Temps de parcours estimé (minutes, modèle 2D)
    effective_dist = cost if cost is not None else distance
    travel_time = effective_dist / max(0.1, base_speed_m_per_min)

    # Difficulté technique
    end_trap = getattr(end, "trap_potential", 0.0)
    end_vis = getattr(end, "visibility_radius", 30.0)
    nav_difficulty = 1.0 - min(1.0, end_vis / 30.0)
    technical_difficulty = min(1.0, end_trap * 0.55 + nav_difficulty * 0.45)

    # Risque d'erreur
    risk_level = min(1.0, technical_difficulty * 0.65 + end_trap * 0.35)

    # Calcul 3D : climb + temps réel via A* Tobler
    climb_m = 0.0
    travel_time_seconds = 0.0

    if terrain_model is not None and elevation_provider is not None:
        try:
            from ..navigation.terrain_3d import shortest_path_with_climb

            sx, sy = getattr(start, "x", 0.0), getattr(start, "y", 0.0)
            ex, ey = getattr(end,   "x", 0.0), getattr(end,   "y", 0.0)

            # Conversion coordonnées → indices raster
            start_rc = _coords_to_cell(sx, sy, elevation_provider, cell_size_m)
            end_rc   = _coords_to_cell(ex, ey, elevation_provider, cell_size_m)

            t_s, c_m = shortest_path_with_climb(start_rc, end_rc, terrain_model)
            if math.isfinite(t_s):
                travel_time_seconds = t_s
                climb_m = c_m
        except Exception:
            pass   # Dégradation silencieuse si modèle 3D indisponible

    return Leg(
        start_id=start.id,          # type: ignore[attr-defined]
        end_id=end.id,              # type: ignore[attr-defined]
        distance=distance,
        bearing_deg=bearing,
        bearing_change_deg=bearing_change,
        route_choice_complexity=route_choice_complexity,
        runnability=runnability,
        technical_difficulty=technical_difficulty,
        risk_level=risk_level,
        travel_time=travel_time,
        cost=cost,
        climb_m=climb_m,
        travel_time_seconds=travel_time_seconds,
    )


# ---------------------------------------------------------------------------
# Helper interne
# ---------------------------------------------------------------------------

def _coords_to_cell(
    x: float,
    y: float,
    elevation_provider: "ElevationProvider",
    cell_size_m: float,
) -> tuple[int, int]:
    """Convertit des coordonnées monde en (row, col) entiers pour la grille terrain."""
    row_f, col_f = elevation_provider._to_rowcol_float(x, y)   # type: ignore[attr-defined]
    h, w = elevation_provider.get_elevation_grid().shape
    row = max(0, min(int(row_f), h - 1))
    col = max(0, min(int(col_f), w - 1))
    return row, col
