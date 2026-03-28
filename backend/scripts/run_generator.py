#!/usr/bin/env python3
"""
scripts/run_generator.py — Générateur de parcours CO par Simulated Annealing.

Pipeline :
  BLOC 1 : Chargement candidats + poids → CostMatrix (3D Tobler ou 2D euclidien)
  BLOC 2 : Génération initiale greedy nearest-neighbor
  BLOC 3 : Optimisation Simulated Annealing (swap / insert / delete)
  BLOC 4 : Export GeoJSON (Points + LineStrings avec métriques complètes)
  BLOC 5 : CLI argparse
  BLOC 6 : main + gestion des erreurs

Imports absolus conformes à l'architecture aitraceur :
  Les modules internes utilisent des imports relatifs ; les imports ci-dessous
  sont absolus au sens Python (aucun point « . » en préfixe). Les fallbacks
  silencieux gèrent les modules non encore publiés (AStarPathfinder,
  scoring.profiles) sans interrompre le pipeline.

Usage :
    python scripts/run_generator.py \\
        --candidates data/candidates.json \\
        --output     output/course.geojson \\
        [--map-dir   data/maps/terrain/] \\
        [--weights   data/weights.json] \\
        [--profile   FOREST_MD_ORANGE] \\
        [--iters     2000] \\
        [--max-no-improve 100]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import math
import random
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# PYTHONPATH — résolution automatique depuis scripts/ ou backend/
# ---------------------------------------------------------------------------
_HERE    = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_SRC     = _BACKEND / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ---------------------------------------------------------------------------
# Imports aitraceur — absolus, avec fallbacks pour modules absents
# ---------------------------------------------------------------------------

# --- Candidats & profils ---
from aitraceur.controls.candidate import ControlCandidate, DetailType

try:
    from aitraceur.profiles import (
        CourseProfile,
        ScoringWeights,
        get_profile,
        PROFILE_FOREST_MIDDLE_ORANGE,
        PROFILE_FOREST_LONG_GREEN,
        PROFILE_FOREST_MIDDLE_BLUE,
        PROFILE_SPRINT_URBAN,
    )
except ImportError as _exc:
    sys.exit(f"ERREUR : aitraceur.profiles non trouvé.\n  Détail : {_exc}")

# scoring/profiles.py — non publié ; fallback sur aitraceur.profiles
try:
    from aitraceur.scoring.profiles import ScoringWeights as _SW  # type: ignore[import]
    ScoringWeights = _SW
except ImportError:
    pass   # ScoringWeights déjà importé depuis aitraceur.profiles

# --- Matrix & cache ---
from aitraceur.matrix.cost_matrix import CostMatrix
from aitraceur.matrix.leg_cache import LegCache  # noqa: F401  (exporté pour cohérence)

# --- Modèle & jambe ---
from aitraceur.model.course import Course
from aitraceur.model.leg import Leg, compute_leg_features

# --- Scoring ---
from aitraceur.scoring.scorer import score_course
from aitraceur.scoring import CourseScoreBreakdown

# --- Navigation ---
from aitraceur.navigation.elevation import ElevationProvider

# navigation/terrain_3d.py → AStarPathfinder non publié ; fallback silencieux
try:
    from aitraceur.navigation.terrain_3d import AStarPathfinder  # type: ignore[import]
except ImportError:
    AStarPathfinder = None   # Pathfinding géré en interne par CostMatrix

# rasterio optionnel (mode 3D végétation)
try:
    import rasterio as _rasterio
    import numpy as _np
    _HAS_RASTERIO = True
except ImportError:
    _HAS_RASTERIO = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run_generator")

# ---------------------------------------------------------------------------
# Profils disponibles (clé = ID profil)
# ---------------------------------------------------------------------------
_PROFILES: dict[str, CourseProfile] = {
    "FOREST_MD_ORANGE": PROFILE_FOREST_MIDDLE_ORANGE,
    "FOREST_LD_GREEN":  PROFILE_FOREST_LONG_GREEN,
    "FOREST_MD_BLUE":   PROFILE_FOREST_MIDDLE_BLUE,
    "SPRINT_URBAN":     PROFILE_SPRINT_URBAN,
    # Aliases courts
    "forest_middle": PROFILE_FOREST_MIDDLE_ORANGE,
    "forest_long":   PROFILE_FOREST_LONG_GREEN,
    "forest_blue":   PROFILE_FOREST_MIDDLE_BLUE,
    "sprint":        PROFILE_SPRINT_URBAN,
}

# Noms de rasters acceptés (priorité décroissante)
_ELEV_NAMES = ("elevation.tif", "dtm.tif", "dem.tif", "mnt.tif", "mnt_lidar.tif")
_VEG_NAMES  = ("vegetation.tif", "veg.tif", "runnability.tif", "passability.tif")


# ===========================================================================
# BLOC 1 — Chargement & Setup
# ===========================================================================

def load_candidates(path: str, profile: CourseProfile) -> List[ControlCandidate]:
    """
    Charge les candidats depuis un fichier JSON.

    Format attendu :
        [{"id": 1, "x": 652100.0, "y": 6861200.0, "detail_type": "knoll", ...}, ...]

    Champs obligatoires : id, x, y.
    Champs optionnels : detail_type, attractiveness_score, readability_score,
                        isolation_score, technical_level, symbol_id.

    Raises:
        FileNotFoundError : fichier absent.
        ValueError        : JSON malformé ou < 3 candidats valides.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Fichier candidats introuvable : {path}")

    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"Le JSON doit être une liste, obtenu : {type(raw).__name__}"
        )

    candidates: List[ControlCandidate] = []
    for i, rec in enumerate(raw):
        if not isinstance(rec, dict) or "x" not in rec or "y" not in rec:
            log.warning("Candidat #%d ignoré (x/y manquants) : %r", i, rec)
            continue

        # Résolution du detail_type — essaie valeur puis nom enum
        raw_dt = str(rec.get("detail_type", "knoll"))
        try:
            detail_type = DetailType(raw_dt)          # lookup par valeur ("knoll")
        except ValueError:
            try:
                detail_type = DetailType[raw_dt.upper()]  # lookup par nom ("KNOLL")
            except KeyError:
                detail_type = DetailType.KNOLL

        try:
            candidates.append(ControlCandidate(
                id=str(rec.get("id", i)),
                geom=_make_point(float(rec["x"]), float(rec["y"])),
                detail_type=detail_type,
                attractiveness_score=float(rec.get("attractiveness_score", 0.5)),
                readability_score=float(rec.get("readability_score", 0.5)),
                technical_level=int(
                    rec.get("technical_level", profile.technical_level.value)
                ),
                allowed_profiles=frozenset({profile.id}),
                source_sym=rec.get("symbol_id"),
            ))
        except (TypeError, ValueError) as exc:
            log.warning("Candidat #%d ignoré (%s) : %r", i, exc, rec)

    if len(candidates) < 3:
        raise ValueError(
            f"Seulement {len(candidates)} candidats valides après filtrage "
            f"(minimum requis : 3)."
        )

    log.info("%d candidats chargés depuis %s", len(candidates), p.name)
    return candidates


def _make_point(x: float, y: float):  # type: ignore[return]
    """Crée un Point Shapely ; lève ImportError si shapely absent."""
    try:
        from shapely.geometry import Point
        return Point(x, y)
    except ImportError as exc:
        raise ImportError("shapely est requis : pip install shapely") from exc


def load_weights(path: Optional[str], profile: CourseProfile) -> ScoringWeights:
    """
    Charge les ScoringWeights depuis un fichier JSON.

    Supporte deux formats :
      - Clé racine directe   : {"w_legs": 0.3, "w_flow": 0.2, ...}
      - Clé "calibrated_weights" : {"calibrated_weights": {"w_legs": ...}}

    Retourne les poids du profil si path est None ou le fichier illisible.
    """
    if path is None:
        log.info("Poids : profil '%s' (par défaut).", profile.id)
        return profile.weights

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        w_data: dict = raw.get("calibrated_weights", raw)
        known = {f.name for f in dataclasses.fields(ScoringWeights)}
        filtered = {k: float(v) for k, v in w_data.items() if k in known}
        weights = ScoringWeights(**filtered)
        log.info("Poids chargés depuis %s (%d champs)", Path(path).name, len(filtered))
        return weights
    except FileNotFoundError:
        log.warning("Fichier de poids introuvable (%s) → poids du profil.", path)
    except Exception as exc:
        log.warning("Chargement des poids échoué (%s) → poids du profil.", exc)

    return profile.weights


def setup_cost_matrix(
    map_dir: Optional[str],
    candidates: List[ControlCandidate],
    n_workers: int = 4,
    k_neighbors: int = 20,
    max_distance_m: float = 2500.0,
    cell_size_m: float = 3.0,
) -> Tuple[CostMatrix, bool]:
    """
    Instancie et pré-calcule la CostMatrix.

    Mode 3D Tobler (AStarPathfinder via TerrainMovementCost) :
        Activé si map_dir contient un raster d'élévation ET un raster de
        végétation.  L'ElevationProvider et le veg_grid sont transmis à la
        CostMatrix ; le pathfinding A* interne utilise alors la loi de Tobler.

    Mode flat/2D (fallback) :
        Si map_dir est absent, vide ou sans rasters lisibles.
        Coût = distance euclidienne / vitesse constante (12 km/h). Climb = 0.
        Aucune exception levée — uniquement un WARNING.

    Returns:
        (CostMatrix pré-calculée, is_3d)

    Raises:
        RuntimeError : en cas d'erreur irrécupérable lors du build.
    """
    elevation_provider: Optional[ElevationProvider] = None
    veg_grid = None

    if map_dir:
        mdir = Path(map_dir)
        if not mdir.is_dir():
            log.warning("--map-dir '%s' invalide → mode flat/2D.", map_dir)
        else:
            # Raster d'élévation → ElevationProvider
            for name in _ELEV_NAMES:
                p = mdir / name
                if p.is_file():
                    try:
                        elevation_provider = ElevationProvider(str(p))
                        log.info("Élévation chargée : %s", name)
                    except Exception as exc:
                        log.warning("ElevationProvider inutilisable (%s) : %s", name, exc)
                        elevation_provider = None
                    break

            # Raster végétation → numpy array (nécessite rasterio)
            if elevation_provider is not None:
                if not _HAS_RASTERIO:
                    log.warning(
                        "rasterio absent → végétation ignorée "
                        "(pip install rasterio pour le mode 3D)."
                    )
                else:
                    for name in _VEG_NAMES:
                        p = mdir / name
                        if p.is_file():
                            try:
                                with _rasterio.open(str(p)) as src:
                                    veg_grid = src.read(1).astype(_np.float32)
                                log.info("Végétation chargée : %s", name)
                            except Exception as exc:
                                log.warning(
                                    "Raster végétation inutilisable (%s) : %s", name, exc
                                )
                                veg_grid = None
                            break

    is_3d = elevation_provider is not None and veg_grid is not None
    mode_label = "3D Tobler" if is_3d else "flat/2D"

    if not is_3d:
        if map_dir and elevation_provider is None:
            log.warning("Aucun MNT trouvé dans '%s' → mode %s.", map_dir, mode_label)
        elif map_dir and veg_grid is None:
            log.warning(
                "MNT présent mais végétation absente → mode %s "
                "(les deux rasters sont requis pour Tobler).",
                mode_label,
            )
        else:
            log.warning("--map-dir non spécifié → mode %s (euclidien, climb=0).", mode_label)
    else:
        log.info("Mode %s activé.", mode_label)

    t0 = time.perf_counter()
    try:
        cm = CostMatrix(
            elevation_provider=elevation_provider if is_3d else None,
            veg_grid=veg_grid      if is_3d else None,
            cell_size_m=cell_size_m,
        )
        log.info(
            "Pré-calcul CostMatrix : %d candidats, k=%d, dist_max=%.0f m, "
            "workers=%d …",
            len(candidates), k_neighbors, max_distance_m, n_workers,
        )
        cm.build_cost_matrix(
            candidates,
            n_workers=n_workers,
            k_neighbors=k_neighbors,
            max_distance_m=max_distance_m,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Erreur lors de la construction de la CostMatrix : {exc}"
        ) from exc

    elapsed = time.perf_counter() - t0
    log.info(
        "CostMatrix construite en %.2fs — mode %s — couverture %.1f%%",
        elapsed, mode_label, cm.coverage_ratio() * 100,
    )
    return cm, is_3d


# ===========================================================================
# BLOC 2 — Génération initiale (greedy nearest-neighbor)
# ===========================================================================

def generate_initial_course(
    candidates: List[ControlCandidate],
    profile: CourseProfile,
    cost_matrix: CostMatrix,
    n_controls: Optional[int] = None,
) -> Course:
    """
    Construit un parcours initial par heuristique greedy nearest-neighbor.

    Algorithme :
      1. Départ = candidat au plus haut composite_score.
      2. À chaque étape, enchaîner le voisin non sélectionné dont la distance
         directe est minimale (O(k) via cost_matrix.direct_distance).
      3. Répéter jusqu'à atteindre n_controls postes.

    Pas de doublons garantis par la liste ``remaining``.

    Args:
        candidates:  Pool complet de candidats.
        profile:     Profil (fournit controls_target si n_controls est None).
        cost_matrix: Matrice pré-calculée (direct_distance en O(1) via Shapely).
        n_controls:  Nombre de postes souhaité. Si None → profile.targets.controls_target.

    Returns:
        Course non optimisée (metrics=None).
    """
    target = int(n_controls or profile.targets.controls_target)
    target = max(5, min(target, len(candidates)))

    # Départ : candidat au meilleur score composite (qualité intrinsèque)
    sorted_cands = sorted(candidates, key=lambda c: c.composite_score, reverse=True)
    selected: List[ControlCandidate] = [sorted_cands[0]]
    remaining: List[ControlCandidate] = [c for c in candidates if c.id != sorted_cands[0].id]

    while len(selected) < target and remaining:
        last = selected[-1]
        nearest = min(remaining, key=lambda c: cost_matrix.direct_distance(last, c))
        selected.append(nearest)
        remaining.remove(nearest)

    dist_init = sum(
        cost_matrix.direct_distance(selected[i], selected[i + 1])
        for i in range(len(selected) - 1)
    )
    log.info(
        "Parcours initial : %d postes — distance directe cumulée : %.0f m",
        len(selected), dist_init,
    )
    return Course(controls=selected, profile=profile)


# ===========================================================================
# BLOC 3 — Optimisation (Simulated Annealing)
# ===========================================================================

def _neighbor(
    course: Course,
    all_candidates: List[ControlCandidate],
    rng: random.Random,
) -> Course:
    """
    Génère un voisin par l'un des trois opérateurs :

      swap   — échange deux postes intermédiaires (ordre inversé dans le parcours).
      insert — insère un candidat du pool (absent du parcours courant).
      delete — retire un poste intermédiaire (garde au minimum 5 postes en tout).

    Le départ (index 0) et l'arrivée (index −1) ne sont jamais modifiés.
    Le pool est recalculé à la volée (O(n), négligeable pour N ≤ 200).
    """
    n = len(course.controls)
    intermediates: List[int] = list(range(1, n - 1))
    in_course = {c.id for c in course.controls}
    pool: List[ControlCandidate] = [c for c in all_candidates if c.id not in in_course]

    ops: List[str] = []
    if len(intermediates) >= 2:
        ops.append("swap")
    if pool:
        ops.append("insert")
    if len(intermediates) > 3:          # minimum 5 postes total
        ops.append("delete")

    if not ops:
        return course                   # cas dégénéré — aucun mouvement possible

    op = rng.choice(ops)

    if op == "swap":
        i, j = rng.sample(intermediates, 2)
        return course.with_swap(i, j)

    if op == "insert":
        new_ctrl = rng.choice(pool)
        pos = rng.randint(1, n - 1)
        return course.with_insertion(pos, new_ctrl)

    # op == "delete"
    idx = rng.choice(intermediates)
    return course.with_removal(idx)


def optimize_course(
    initial: Course,
    all_candidates: List[ControlCandidate],
    cost_matrix: CostMatrix,
    weights: ScoringWeights,
    n_iters: int = 2000,
    max_no_improve: int = 100,
    T_init: float = 1.0,
    cooling_rate: float = 0.995,
    seed: int = 42,
    log_interval: int = 50,
) -> Course:
    """
    Optimise le parcours par recuit simulé (Simulated Annealing).

    Normalisation :
        score_norm = global_score / 100  ∈ [0, 1]
        Δ = score_norm_candidat − score_norm_courant

    Acceptation Metropolis :
        Δ > 0                    → acceptation certaine (amélioration)
        exp(Δ / T) > U[0, 1)    → acceptation probabiliste (régression)

    Refroidissement géométrique :
        T ← T × cooling_rate  (après chaque itération)

    Arrêt anticipé :
        Si aucune amélioration pendant ``max_no_improve`` itérations.

    Chaque évaluation score_course utilise le LegCache (O(1)) après
    build_cost_matrix. Aucun recalcul A* dans la boucle.

    Args:
        initial:         Parcours de départ (greedy NN).
        all_candidates:  Pool global pour les insertions.
        cost_matrix:     Matrice pré-calculée.
        weights:         Poids de scoring.
        n_iters:         Nombre max d'itérations.
        max_no_improve:  Seuil early stopping.
        T_init:          Température initiale (défaut : 1.0).
        cooling_rate:    Taux refroidissement géométrique (défaut : 0.995).
        seed:            Graine (reproductibilité).
        log_interval:    Fréquence des logs périodiques.

    Returns:
        Meilleur parcours trouvé.
    """
    rng = random.Random(seed)
    profile = initial.profile

    # Évaluation initiale
    current = initial.compute_metrics(cost_matrix)
    bd_init = score_course(current, weights, cost_matrix=cost_matrix, profile=profile)
    current_score: float = bd_init.global_score / 100.0

    best_course: Course = current
    best_score: float = current_score

    T: float = T_init
    no_improve: int = 0
    actual_iters: int = 0

    log.info(
        "SA — iters=%d  max_no_improve=%d  T₀=%.3f  cooling=%.4f  seed=%d",
        n_iters, max_no_improve, T_init, cooling_rate, seed,
    )
    log.info(
        "Score initial : %.3f/1.000  (%.2f/100 — Grade %s)  postes : %d",
        current_score, bd_init.global_score, bd_init.grade, initial.n_controls,
    )

    t_start = time.perf_counter()

    for it in range(1, n_iters + 1):
        actual_iters = it

        # Génération + évaluation du voisin
        cand = _neighbor(current, all_candidates, rng)
        cand = cand.compute_metrics(cost_matrix)
        bd_new = score_course(cand, weights, cost_matrix=cost_matrix, profile=profile)
        new_score: float = bd_new.global_score / 100.0

        # Critère d'acceptation Metropolis (sur score normalisé)
        delta: float = new_score - current_score
        accept: bool = delta > 0 or (
            T > 1e-12 and math.exp(delta / T) > rng.random()
        )

        if accept:
            current = cand
            current_score = new_score

            if new_score > best_score:
                best_score = new_score
                best_course = cand
                no_improve = 0
                log.info(
                    "Iter %5d/%d | Score: %.3f | Best: %.3f | T=%.4f  ★",
                    it, n_iters, current_score, best_score, T,
                )
            else:
                no_improve += 1
        else:
            no_improve += 1

        T *= cooling_rate

        if it % log_interval == 0:
            log.info(
                "Iter %5d/%d | Score: %.3f | Best: %.3f | T=%.4f",
                it, n_iters, current_score, best_score, T,
            )

        if no_improve >= max_no_improve:
            log.info(
                "Early stopping — %d iters sans amélioration (iter %d/%d).",
                max_no_improve, it, n_iters,
            )
            break

    elapsed = time.perf_counter() - t_start
    bd_best = score_course(
        best_course, weights, cost_matrix=cost_matrix, profile=profile
    )
    log.info(
        "SA terminé en %.2fs | %d/%d iters | Score=%.2f/100 | "
        "Grade=%s | postes=%d",
        elapsed, actual_iters, n_iters,
        bd_best.global_score, bd_best.grade, best_course.n_controls,
    )
    return best_course


# ===========================================================================
# BLOC 4 — Export GeoJSON
# ===========================================================================

def _build_leg_with_3d(
    start: ControlCandidate,
    end: ControlCandidate,
    cost_matrix: CostMatrix,
    prev_bearing: Optional[float],
    base_speed: float,
) -> Leg:
    """
    Construit un Leg en surchargeant climb_m / travel_time_seconds depuis le
    cache brut de la CostMatrix (tuple dist/time/climb stocké par build_cost_matrix).

    Pourquoi le surcharger ? compute_leg_features utilise cost_matrix.cost(a, b)
    qui retourne time_s (pas une distance) en mode scalable 3D — ce qui rend
    la formule route_choice_complexity dimensionnellement incohérente.  Les
    métriques 3D fiables (temps Tobler, dénivelé A*) sont dans le cache brut.
    """
    leg = compute_leg_features(
        start, end, cost_matrix,
        prev_bearing=prev_bearing,
        base_speed_m_per_min=base_speed,
    )

    # Surcharge 3D depuis le cache brut (tuple stocké par _process_batch)
    cached = cost_matrix._cache.get(start.id, end.id)
    if isinstance(cached, tuple) and len(cached) == 3:
        _dist_m, time_s, climb_m = cached
        if math.isfinite(time_s) and time_s > 0 and math.isfinite(climb_m):
            leg = Leg(
                start_id=leg.start_id,
                end_id=leg.end_id,
                distance=leg.distance,
                bearing_deg=leg.bearing_deg,
                bearing_change_deg=leg.bearing_change_deg,
                route_choice_complexity=leg.route_choice_complexity,
                runnability=leg.runnability,
                technical_difficulty=leg.technical_difficulty,
                risk_level=leg.risk_level,
                travel_time=leg.travel_time,
                cost=leg.cost,
                climb_m=float(climb_m),
                travel_time_seconds=float(time_s),
            )
    return leg


def export_geojson(
    course: Course,
    cost_matrix: CostMatrix,
    weights: ScoringWeights,
    output_path: str,
) -> None:
    """
    Exporte le parcours en GeoJSON (FeatureCollection).

    Structure :
      - ``properties`` de la collection : métriques globales + tous les sous-scores.
      - Features Point  : un par poste (order, role, detail_type, scores…).
      - Features LineString : une par jambe dans l'ordre du parcours
        (distance_2d, climb_m, km_effort, travel_time_seconds,
         route_choice_complexity, bearing, runnability, risk_level).

    Coordonnées : (x, y) dans le SCR du raster source.

    Args:
        course:      Parcours optimisé.
        cost_matrix: Matrice pré-calculée (cache brut utilisé pour métriques 3D).
        weights:     Poids de scoring (scoring final du GeoJSON).
        output_path: Chemin du fichier .geojson de sortie.
    """
    controls = course.controls
    profile  = course.profile
    bd: CourseScoreBreakdown = score_course(
        course, weights, cost_matrix=cost_matrix, profile=profile,
    )
    base_speed = profile.movement.base_speed_m_per_min
    features: List[dict] = []

    # ------------------------------------------------------------------
    # Features Point — postes (ordre respecté)
    # ------------------------------------------------------------------
    for i, ctrl in enumerate(controls):
        role = "start" if i == 0 else ("finish" if i == len(controls) - 1 else "control")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [ctrl.x, ctrl.y]},
            "properties": {
                "id":                   ctrl.id,
                "sequence":             i,
                "role":                 role,
                "detail_type":          (
                    ctrl.detail_type.value
                    if hasattr(ctrl.detail_type, "value")
                    else str(ctrl.detail_type)
                ),
                "symbol_id":            ctrl.source_sym,
                "attractiveness_score": round(ctrl.attractiveness_score, 4),
                "readability_score":    round(ctrl.readability_score, 4),
                "technical_level":      ctrl.technical_level,
            },
        })

    # ------------------------------------------------------------------
    # Features LineString — jambes
    # ------------------------------------------------------------------
    prev_bearing: Optional[float] = None
    for i in range(len(controls) - 1):
        start_ctrl = controls[i]
        end_ctrl   = controls[i + 1]

        leg = _build_leg_with_3d(
            start_ctrl, end_ctrl, cost_matrix, prev_bearing, base_speed
        )
        prev_bearing = leg.bearing_deg

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [start_ctrl.x, start_ctrl.y],
                    [end_ctrl.x,   end_ctrl.y],
                ],
            },
            "properties": {
                "leg_sequence":            i,
                "start_id":                leg.start_id,
                "end_id":                  leg.end_id,
                "distance_2d":             round(leg.distance_2d, 1),
                "climb_m":                 round(leg.climb_m, 2),
                "km_effort":               round(leg.km_effort, 4),
                "travel_time_seconds":     round(leg.travel_time_seconds, 2),
                "route_choice_complexity": round(leg.route_choice_complexity, 4),
                "bearing_deg":             round(leg.bearing_deg, 1),
                "bearing_change_deg":      round(leg.bearing_change_deg, 1),
                "runnability":             round(leg.runnability, 4),
                "technical_difficulty":    round(leg.technical_difficulty, 4),
                "risk_level":              round(leg.risk_level, 4),
            },
        })

    # ------------------------------------------------------------------
    # FeatureCollection avec métriques globales
    # ------------------------------------------------------------------
    geojson = {
        "type": "FeatureCollection",
        "properties": {
            "course": {
                "profile_id":                   profile.id,
                "profile_name":                 profile.name,
                "n_controls":                   len(controls),
                "global_score":                 round(bd.global_score, 2),
                "grade":                        bd.grade,
                "distance_m":                   round(bd.distance_m, 1),
                "target_dist_m":                round(bd.target_dist_m, 1),
                "total_climb_m":                round(bd.total_climb, 2),
                "mean_km_effort":               round(bd.mean_km_effort, 4),
                "mean_route_choice_complexity": round(bd.mean_route_choice_complexity, 4),
                "dog_legs":                     bd.dog_legs,
                "n_infeasible":                 bd.n_infeasible,
                # Sous-scores [0–1]
                "distance_score":   round(bd.distance_score, 3),
                "climb_score":      round(bd.climb_score, 3),
                "technical_score":  round(bd.technical_score, 3),
                "variety_score":    round(bd.variety_score, 3),
                "structure_score":  round(bd.structure_score, 3),
                "spatial_score":    round(bd.spatial_score, 3),
                "safety_score":     round(bd.safety_score, 3),
                "flow_score":       round(bd.flow_score, 3),
                "global_effort_score": round(bd.global_effort_score, 3),
                "alignment_score":  round(bd.alignment_score, 3),
                "clustering_score": round(bd.clustering_score, 3),
                "diversity_score":  round(bd.diversity_score, 3),
            },
        },
        "features": features,
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(geojson, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(
        "GeoJSON exporté → %s  (%d features : %d postes + %d jambes)",
        output_path, len(features), len(controls), len(controls) - 1,
    )


# ===========================================================================
# BLOC 5 — CLI (argparse)
# ===========================================================================

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_generator.py",
        description=(
            "Génère un parcours de CO optimisé (SA) et l'exporte en GeoJSON.\n"
            "Mode 3D Tobler activé si --map-dir contient MNT + végétation."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--map-dir", default=None, metavar="DIR",
        help=(
            "Dossier GeoTIFF (elevation.tif + vegetation.tif). "
            "Optionnel — mode flat/2D si absent."
        ),
    )
    p.add_argument(
        "--candidates", required=True, metavar="JSON",
        help="Fichier JSON : liste [{id, x, y, detail_type, …}].",
    )
    p.add_argument(
        "--weights", default=None, metavar="JSON",
        help="Fichier JSON ScoringWeights. Défaut : poids du profil.",
    )
    p.add_argument(
        "--output", required=True, metavar="GEOJSON",
        help="Fichier GeoJSON de sortie.",
    )
    p.add_argument(
        "--profile", default="FOREST_MD_ORANGE",
        choices=list(dict.fromkeys(_PROFILES.keys())),   # préserve l'ordre, déduplique
        help="ID du profil de course.",
    )
    p.add_argument(
        "--iters", type=int, default=2000, metavar="N",
        help="Nombre maximum d'itérations SA.",
    )
    p.add_argument(
        "--max-no-improve", type=int, default=100, metavar="N",
        help="Early stopping après N iters sans amélioration.",
    )
    p.add_argument(
        "--T-init", type=float, default=1.0, metavar="F",
        help="Température initiale SA.",
    )
    p.add_argument(
        "--cooling", type=float, default=0.995, metavar="F",
        help="Taux de refroidissement géométrique.",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="Graine aléatoire.",
    )
    p.add_argument(
        "--n-workers", type=int, default=4, metavar="N",
        help="Threads parallèles pour build_cost_matrix.",
    )
    p.add_argument(
        "--k-neighbors", type=int, default=20, metavar="K",
        help="Voisins k pour le filtre spatial KDTree.",
    )
    p.add_argument(
        "--max-dist-m", type=float, default=2500.0, metavar="M",
        help="Distance euclidienne maximale entre deux postes reliés (m).",
    )
    p.add_argument(
        "--n-controls", type=int, default=None, metavar="N",
        help="Nombre de postes cible (remplace la valeur du profil).",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de verbosité.",
    )
    return p


# ===========================================================================
# BLOC 6 — Point d'entrée + robustesse globale
# ===========================================================================

def main() -> None:
    args = _build_parser().parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    log.info("=" * 64)
    log.info("AItraceur — run_generator.py")
    log.info("Candidats  : %s", args.candidates)
    log.info("Sortie     : %s", args.output)
    log.info("Profil     : %s", args.profile)
    log.info("Mode 3D    : %s", "oui" if args.map_dir else "non (--map-dir absent)")
    log.info("=" * 64)

    # ------------------------------------------------------------------
    # Profil
    # ------------------------------------------------------------------
    try:
        profile = _PROFILES.get(args.profile) or get_profile(args.profile)
    except KeyError:
        log.error("Profil inconnu : '%s'. Valeurs : %s", args.profile,
                  ", ".join(dict.fromkeys(_PROFILES.keys())))
        sys.exit(1)
    log.info("Profil : %s", profile.name)

    # ------------------------------------------------------------------
    # BLOC 1 — Chargement
    # ------------------------------------------------------------------
    try:
        candidates = load_candidates(args.candidates, profile)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        log.error("Chargement candidats échoué : %s", exc)
        sys.exit(1)

    weights = load_weights(args.weights, profile)

    try:
        cost_matrix, _is_3d = setup_cost_matrix(
            args.map_dir,
            candidates,
            n_workers=args.n_workers,
            k_neighbors=args.k_neighbors,
            max_distance_m=args.max_dist_m,
        )
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    # ------------------------------------------------------------------
    # BLOC 2 — Génération initiale
    # ------------------------------------------------------------------
    initial = generate_initial_course(
        candidates, profile, cost_matrix, args.n_controls,
    )

    # ------------------------------------------------------------------
    # BLOC 3 — Optimisation SA
    # ------------------------------------------------------------------
    best = optimize_course(
        initial=initial,
        all_candidates=candidates,
        cost_matrix=cost_matrix,
        weights=weights,
        n_iters=args.iters,
        max_no_improve=args.max_no_improve,
        T_init=args.T_init,
        cooling_rate=args.cooling,
        seed=args.seed,
        log_interval=max(1, args.iters // 20),
    )

    # ------------------------------------------------------------------
    # BLOC 4 — Export GeoJSON
    # ------------------------------------------------------------------
    try:
        export_geojson(best, cost_matrix, weights, args.output)
    except Exception as exc:
        log.error("Export GeoJSON échoué : %s", exc, exc_info=True)
        sys.exit(1)

    log.info("=" * 64)
    log.info("Génération terminée avec succès.")
    log.info("=" * 64)


if __name__ == "__main__":
    main()
