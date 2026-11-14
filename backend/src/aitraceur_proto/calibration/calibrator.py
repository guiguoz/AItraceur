"""
Couche 7 — Calibration automatique des poids de scoring (optimisation L-BFGS-B).

Maximise la séparation score_WOC - alpha * score_generated avec :
  - régularisation L2 (évite la domination d'une seule métrique)
  - pénalité de variance inter-métriques (force l'équilibre)
  - initialisation bruitée (±5 % — évite les minima locaux triviaux)
  - early stopping (max_iter=100)

Exemple d'utilisation :
    engine = CalibrationEngine(ref_courses, gen_courses)
    weights = engine.calibrate()
    engine.save_weights("weights_woc.json")

    result = evaluate_calibration(ref_courses, gen_courses, weights)
    print(result["delta"])  # > 0.3 = bonne séparation WOC / IA
"""
from __future__ import annotations

import dataclasses
import json
import logging
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..model.course import Course
from ..profiles import CourseProfile, ScoringWeights
from ..scoring.scorer import score_course

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paramètres calibrables — noms + bornes (min, max)
# ---------------------------------------------------------------------------

_CALIB_PARAMS: list[tuple[str, float, float]] = [
    # Scoring local (par jambe)
    ("effort_weight",  0.0, 2.0),
    ("choice_weight",  0.0, 2.0),
    ("tech_weight",    0.0, 2.0),
    # Scoring global (séquentiel)
    ("w_legs",         0.0, 2.0),
    ("w_flow",         0.0, 2.0),
    ("w_variety",      0.0, 2.0),
    ("w_effort",       0.0, 2.0),
    ("target_effort",  1.0, 2.0),
    # Scoring anti-patterns
    ("w_alignment",    0.0, 2.0),
    ("w_clustering",   0.0, 2.0),
    ("w_diversity",    0.0, 2.0),
]

_PARAM_NAMES: list[str] = [p[0] for p in _CALIB_PARAMS]
_BOUNDS: list[tuple[float, float]] = [(p[1], p[2]) for p in _CALIB_PARAMS]
_N_PARAMS: int = len(_CALIB_PARAMS)
# Indice de target_effort dans le vecteur — exclu de la régularisation L2
_IDX_TARGET_EFFORT: int = _PARAM_NAMES.index("target_effort")
# Plancher de bruit : 10 % de l'amplitude de chaque paramètre (évite d'être
# coincé à 0 pour les w_* dont la valeur initiale est 0.0)
_NOISE_FLOOR: np.ndarray = np.array(
    [0.1 * (hi - lo) for _, lo, hi in _CALIB_PARAMS], dtype=np.float64
)

# Sous-scores utilisés pour la pénalité d'équilibre inter-métriques
_BALANCE_FIELDS: list[str] = [
    "flow_score",
    "variety_score",
    "global_effort_score",
    "alignment_score",
    "clustering_score",
    "diversity_score",
]

# Point de départ non-trivial : active toutes les composantes dès le début
# pour que la surface de loss soit non-plate dès la première évaluation.
_DEFAULT_INIT = ScoringWeights(
    effort_weight=0.4,
    choice_weight=0.4,
    tech_weight=0.2,
    w_legs=0.3,
    w_flow=0.2,
    w_variety=0.2,
    w_effort=0.3,
    target_effort=1.2,
    w_alignment=0.2,
    w_clustering=0.2,
    w_diversity=0.2,
)


# ---------------------------------------------------------------------------
# ReferenceStats — statistiques du corpus de référence
# ---------------------------------------------------------------------------

@dataclass
class ReferenceStats:
    """Statistiques agrégées d'un corpus de circuits de référence."""

    n_courses: int = 0

    # Distance
    mean_distance_m: float = 0.0
    std_distance_m: float = 0.0
    min_distance_m: float = 0.0
    max_distance_m: float = 0.0

    # Jambes
    mean_leg_m: float = 0.0
    std_leg_m: float = 0.0
    mean_min_leg_m: float = 0.0
    mean_max_leg_m: float = 0.0

    # Technique
    mean_td: float = 0.0
    std_td: float = 0.0

    # Variété / structure
    mean_type_diversity: float = 0.0
    mean_dog_legs_ratio: float = 0.0

    # Spatial
    mean_bearing_change_deg: float = 0.0
    std_bearing_change_deg: float = 0.0
    mean_coverage_ratio: float = 0.0


# ---------------------------------------------------------------------------
# CalibrationEngine — optimisation L-BFGS-B
# ---------------------------------------------------------------------------

class CalibrationEngine:
    """
    Moteur de calibration automatique des poids de scoring (WOC-grade).

    Optimise 11 paramètres de ScoringWeights par maximisation de la séparation
    score_WOC - alpha * score_generated, avec régularisation et équilibre forcé.

    Args:
        reference_courses:  Circuits de référence (WOC / traceurs experts).
        generated_courses:  Circuits IA ou aléatoires.
        alpha:              Poids du terme de pénalisation des générés (défaut 0.5).
        lambda_reg:         Force de régularisation L2 (défaut 0.1).
        beta:               Poids de la pénalité d'équilibre inter-métriques (défaut 0.2).
        seed:               Graine numpy — reproductibilité garantie (défaut 42).
    """

    def __init__(
        self,
        reference_courses: List[Course],
        generated_courses: List[Course],
        *,
        alpha: float = 0.5,
        lambda_reg: float = 0.1,
        beta: float = 0.2,
        seed: int = 42,
    ) -> None:
        self.reference_courses: list[Course] = list(reference_courses)
        self.generated_courses: list[Course] = list(generated_courses)
        self.alpha = alpha
        self.lambda_reg = lambda_reg
        self.beta = beta
        self._rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------
    # Conversion vecteur ↔ ScoringWeights
    # ------------------------------------------------------------------

    @staticmethod
    def _weights_to_vector(weights: ScoringWeights) -> np.ndarray:
        """Extrait les 11 paramètres calibrables dans un vecteur numpy."""
        return np.array(
            [getattr(weights, name) for name in _PARAM_NAMES],
            dtype=np.float64,
        )

    @staticmethod
    def _vector_to_weights(vector: np.ndarray) -> ScoringWeights:
        """
        Reconstruit un ScoringWeights depuis un vecteur de 11 paramètres.

        Les champs legacy (distance, climb, technical, etc.) conservent
        leurs valeurs par défaut de ScoringWeights.
        """
        overrides = {
            name: float(vector[i])
            for i, name in enumerate(_PARAM_NAMES)
        }
        return ScoringWeights(**overrides)

    # ------------------------------------------------------------------
    # Scoring utilitaire — passe unique (évite la double évaluation)
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_corpus(
        courses: List[Course], weights: ScoringWeights
    ) -> tuple[float, np.ndarray]:
        """
        Évalue le corpus en UN SEUL passage sur score_course.

        Retourne :
            (mean_global_score [0,1], mean_balance_vector [len=6])

        Valeurs neutres si corpus vide : (0.5, vecteur de 0.5).
        """
        if not courses:
            return 0.5, np.full(len(_BALANCE_FIELDS), 0.5)

        score_sum = 0.0
        balance_sum = np.zeros(len(_BALANCE_FIELDS))

        for c in courses:
            profile = getattr(c, "profile", None)
            bd = score_course(c, weights, profile=profile)
            score_sum += max(0.0, min(1.0, bd.global_score / 100.0))
            for j, fname in enumerate(_BALANCE_FIELDS):
                balance_sum[j] += max(0.0, min(1.0, float(getattr(bd, fname, 0.5))))

        n = len(courses)
        return score_sum / n, balance_sum / n

    @staticmethod
    def _mean_score(courses: List[Course], weights: ScoringWeights) -> float:
        """Score moyen [0,1] d'un corpus. Interface publique stable."""
        mean, _ = CalibrationEngine._evaluate_corpus(courses, weights)
        return mean

    # ------------------------------------------------------------------
    # Fonction objectif (à minimiser — scipy convention)
    # ------------------------------------------------------------------

    def objective_function(self, vector: np.ndarray) -> float:
        """
        Loss = -(score_ref - alpha * score_gen) + reg_L2 + balance_penalty.

        Trois composantes :
        1. Séparation     : max(score_WOC - alpha * score_gen)
        2. Régularisation : lambda_reg * ||w||²  (hors target_effort)
        3. Équilibre      : beta * Var(sous_scores) → empêche la domination

        Un seul passage sur score_course par corpus (pas de double évaluation).
        """
        # Sécurité : clipper dans les bornes avant évaluation
        clipped = np.clip(
            vector,
            [b[0] for b in _BOUNDS],
            [b[1] for b in _BOUNDS],
        )
        weights = self._vector_to_weights(clipped)

        # 1 + 3 — passe unique sur le corpus de référence
        score_ref, balance = self._evaluate_corpus(self.reference_courses, weights)
        # passe unique sur le corpus généré (score seulement, pas de balance)
        score_gen, _ = self._evaluate_corpus(self.generated_courses, weights)

        separation = score_ref - self.alpha * score_gen

        # 2 — Régularisation L2 (hors target_effort — paramètre de position,
        # pas de magnitude — pour éviter de le pousser vers sa borne inférieure)
        reg_vec = np.delete(clipped, _IDX_TARGET_EFFORT)
        reg = self.lambda_reg * float(np.sum(reg_vec ** 2))

        # 3 — Pénalité d'équilibre inter-métriques
        balance_penalty = self.beta * float(np.var(balance))

        return -separation + reg + balance_penalty

    # ------------------------------------------------------------------
    # Calibration principale
    # ------------------------------------------------------------------

    def calibrate(
        self,
        init_weights: Optional[ScoringWeights] = None,
        *,
        max_iter: int = 100,
        noise_std: float = 0.05,
    ) -> ScoringWeights:
        """
        Lance l'optimisation L-BFGS-B et retourne les poids calibrés.

        Args:
            init_weights: Point de départ (défaut : ScoringWeights()).
            max_iter:     Max d'itérations — early stopping (défaut 100).
            noise_std:    Amplitude du bruit d'init ±X% de chaque valeur
                          (défaut 0.05 = ±5 %, évite les minima triviaux).

        Returns:
            ScoringWeights optimisés, prêts à être injectés dans un profil.

        Raises:
            ImportError: si scipy n'est pas installé.
        """
        try:
            from scipy.optimize import minimize
        except ImportError as exc:
            raise ImportError(
                "scipy est requis pour CalibrationEngine.calibrate(). "
                "Installez-le avec : pip install scipy"
            ) from exc

        if not self.reference_courses:
            logger.warning(
                "CalibrationEngine.calibrate() : aucun circuit de référence "
                "→ poids par défaut retournés."
            )
            result_weights = init_weights or _DEFAULT_INIT
            self._last_weights: Optional[ScoringWeights] = result_weights
            return result_weights

        # Point de départ non-trivial : _DEFAULT_INIT garantit new_weight_sum > 0
        # (active la formule étendue dès la première évaluation du scorer)
        base = init_weights or _DEFAULT_INIT
        x0 = self._weights_to_vector(base)

        # Bruit proportionnel avec plancher = 10 % de l'amplitude de chaque param
        # → les w_* initialisés à 0.0 reçoivent un bruit d'au moins ±0.2 * noise_std
        noise = self._rng.normal(0.0, noise_std, size=_N_PARAMS)
        x0_noisy = np.clip(
            x0 + noise * np.maximum(np.abs(x0), _NOISE_FLOOR),
            [b[0] for b in _BOUNDS],
            [b[1] for b in _BOUNDS],
        )

        result = minimize(
            fun=self.objective_function,
            x0=x0_noisy,
            method="L-BFGS-B",
            bounds=_BOUNDS,
            options={"maxiter": max_iter, "ftol": 1e-9, "gtol": 1e-6},
        )

        if not result.success:
            logger.warning(
                "CalibrationEngine.calibrate() : non-convergence (%s). "
                "Meilleur résultat intermédiaire utilisé.",
                result.message,
            )

        optimized = np.clip(
            result.x,
            [b[0] for b in _BOUNDS],
            [b[1] for b in _BOUNDS],
        )
        result_weights = self._vector_to_weights(optimized)
        self._last_weights = result_weights  # cache → save_weights cohérent
        return result_weights

    # ------------------------------------------------------------------
    # Persistance JSON
    # ------------------------------------------------------------------

    def save_weights(
        self, path: str | Path, weights: Optional[ScoringWeights] = None
    ) -> None:
        """
        Sauvegarde des poids calibrés dans un fichier JSON.

        Args:
            path:    Chemin du fichier de sortie.
            weights: Poids à sauvegarder. Si None, utilise le cache
                     ``self._last_weights`` (résultat du dernier ``calibrate()``).
                     Si aucun cache disponible, lance une calibration.

        Format JSON :
            {
              "calibrated_weights": { ... },
              "n_reference_courses": N,
              "n_generated_courses": M,
              "hyperparams": { "alpha": …, "lambda_reg": …, "beta": … }
            }
        """
        if weights is None:
            weights = getattr(self, "_last_weights", None) or self.calibrate()
        data = {
            "calibrated_weights": asdict(weights),
            "n_reference_courses": len(self.reference_courses),
            "n_generated_courses": len(self.generated_courses),
            "hyperparams": {
                "alpha": self.alpha,
                "lambda_reg": self.lambda_reg,
                "beta": self.beta,
            },
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def load_weights(path: str | Path) -> ScoringWeights:
        """
        Charge des poids calibrés depuis un fichier JSON.

        Les champs manquants (anciens exports) sont complétés par les valeurs
        par défaut de ScoringWeights — rétrocompatibilité garantie.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        w_data = data.get("calibrated_weights", {})
        known = {f.name for f in dataclasses.fields(ScoringWeights)}
        w_data = {k: v for k, v in w_data.items() if k in known}
        return ScoringWeights(**w_data)

    # ------------------------------------------------------------------
    # Statistiques de référence (rétrocompatibilité)
    # ------------------------------------------------------------------

    def compute_reference_stats(self) -> ReferenceStats:
        """Calcule les statistiques agrégées du corpus de référence."""
        if not self.reference_courses:
            return ReferenceStats()

        dists, leg_means, leg_stds, leg_mins, leg_maxs = [], [], [], [], []
        tds, diversities, dog_leg_ratios, bearings, coverages = [], [], [], [], []

        for c in self.reference_courses:
            m = getattr(c, "metrics", None)
            if m is None and hasattr(c, "compute_metrics"):
                c = c.compute_metrics()
                m = getattr(c, "metrics", None)
            if m is None:
                continue
            dists.append(m.total_distance_m)
            leg_means.append(m.mean_leg_m)
            leg_stds.append(m.std_leg_m)
            leg_mins.append(m.min_leg_m)
            leg_maxs.append(m.max_leg_m)
            tds.append(m.mean_technical_level)
            diversities.append(m.type_diversity)
            n_legs = len(m.legs)
            dog_leg_ratios.append(m.dog_legs / max(1, n_legs))
            bearings.append(m.mean_bearing_change_deg)
            coverages.append(m.coverage_ratio)

        def _safe_std(vals: list[float]) -> float:
            return statistics.stdev(vals) if len(vals) > 1 else 0.0

        return ReferenceStats(
            n_courses=len(self.reference_courses),
            mean_distance_m=statistics.mean(dists) if dists else 0.0,
            std_distance_m=_safe_std(dists),
            min_distance_m=min(dists) if dists else 0.0,
            max_distance_m=max(dists) if dists else 0.0,
            mean_leg_m=statistics.mean(leg_means) if leg_means else 0.0,
            std_leg_m=statistics.mean(leg_stds) if leg_stds else 0.0,
            mean_min_leg_m=statistics.mean(leg_mins) if leg_mins else 0.0,
            mean_max_leg_m=statistics.mean(leg_maxs) if leg_maxs else 0.0,
            mean_td=statistics.mean(tds) if tds else 0.0,
            std_td=_safe_std(tds),
            mean_type_diversity=statistics.mean(diversities) if diversities else 0.0,
            mean_dog_legs_ratio=statistics.mean(dog_leg_ratios) if dog_leg_ratios else 0.0,
            mean_bearing_change_deg=statistics.mean(bearings) if bearings else 0.0,
            std_bearing_change_deg=_safe_std(bearings),
            mean_coverage_ratio=statistics.mean(coverages) if coverages else 0.0,
        )


# ---------------------------------------------------------------------------
# Évaluation standalone
# ---------------------------------------------------------------------------

def evaluate_calibration(
    reference_courses: List[Course],
    generated_courses: List[Course],
    weights: ScoringWeights,
) -> dict:
    """
    Évalue la qualité de séparation d'un jeu de poids sur deux corpus.

    Cible post-calibration :
        mean_ref_score  ≈ 0.9–1.0
        mean_gen_score  ≈ 0.3–0.6
        delta           > 0.3 (bonne séparation)

    Args:
        reference_courses: Circuits de référence (WOC / experts).
        generated_courses: Circuits IA ou aléatoires.
        weights:           ScoringWeights à évaluer.

    Returns:
        {
            "mean_ref_score": float [0,1],
            "mean_gen_score": float [0,1],
            "delta":          float — écart (ref - gen)
        }
    """
    mean_ref = CalibrationEngine._mean_score(reference_courses, weights)
    mean_gen = CalibrationEngine._mean_score(generated_courses, weights)
    return {
        "mean_ref_score": round(mean_ref, 4),
        "mean_gen_score": round(mean_gen, 4),
        "delta": round(mean_ref - mean_gen, 4),
    }


# ---------------------------------------------------------------------------
# Helper : reconstruction d'un Course depuis un dict sérialisé
# ---------------------------------------------------------------------------

def _course_from_dict(record: dict, profile: CourseProfile) -> Course:
    """Reconstruit un Course minimal depuis un dict JSON sérialisé."""
    from shapely.geometry import Point

    from ..controls.candidate import ControlCandidate, DetailType

    controls = []
    for idx, raw in enumerate(record.get("controls", [])):
        if "x" not in raw or "y" not in raw:
            raise ValueError(
                f"Contrôle #{idx} manque les champs 'x' et/ou 'y' : {raw!r}"
            )
        cand = ControlCandidate(
            id=str(raw.get("id", idx)),
            geom=Point(float(raw["x"]), float(raw["y"])),
            detail_type=DetailType(raw.get("detail_type", "unknown")),
            attractiveness_score=float(raw.get("attractiveness_score", 0.5)),
            readability_score=float(raw.get("readability_score", 0.5)),
            allowed_profiles=frozenset({profile.id}),
        )
        controls.append(cand)

    return Course(controls=controls, profile=profile)
