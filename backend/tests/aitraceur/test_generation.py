"""
Tests — Couche 6 : génération de parcours.

Couvre :
  - generate_initial_course : parcours plausible
  - improve_course_local : score amélioré (en moyenne)
  - CostMatrix : symétrie, build_cost_matrix
"""
from __future__ import annotations

import random
import pytest

from src.aitraceur.matrix.cost_matrix import CostMatrix, build_cost_matrix
from src.aitraceur.model.course import Course
from src.aitraceur.navigation.movement import MovementModel
from src.aitraceur.generation.constructive import generate_initial_course
from src.aitraceur.generation.local_opt import improve_course_local
from src.aitraceur.scoring.scorer import score_course


# ---------------------------------------------------------------------------
# Fixtures : CostMatrix synthétique (sans MovementModel réel)
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_cost_matrix(ten_candidates, forest_profile):
    """CostMatrix où le coût = distance euclidienne (approximation simple)."""
    import numpy as np
    n = len(ten_candidates)
    data = np.zeros((n, n), dtype=np.float32)
    for i, ca in enumerate(ten_candidates):
        for j, cb in enumerate(ten_candidates):
            if i != j:
                data[i, j] = ca.geom.distance(cb.geom)
    return CostMatrix(candidates=ten_candidates, _data=data)


# ---------------------------------------------------------------------------
# Tests CostMatrix
# ---------------------------------------------------------------------------

class TestCostMatrix:
    def test_diagonal_is_zero(self, synthetic_cost_matrix):
        cm = synthetic_cost_matrix
        for c in cm.candidates:
            cost = cm.cost(c, c)
            assert cost == 0.0

    def test_symmetry(self, synthetic_cost_matrix):
        cm = synthetic_cost_matrix
        n = len(cm.candidates)
        for i in range(n):
            for j in range(i + 1, n):
                ca, cb = cm.candidates[i], cm.candidates[j]
                assert cm.cost(ca, cb) == cm.cost(cb, ca)

    def test_unknown_candidate_returns_none(self, synthetic_cost_matrix, ten_candidates):
        from src.aitraceur.controls.candidate import ControlCandidate, DetailType
        from shapely.geometry import Point
        ghost = ControlCandidate(
            id="ghost_999",
            geom=Point(9999, 9999),
            detail_type=DetailType.UNKNOWN,
            attractiveness_score=0,
            readability_score=0,
        )
        cost = synthetic_cost_matrix.cost(ten_candidates[0], ghost)
        assert cost is None

    def test_coverage_ratio(self, synthetic_cost_matrix):
        cr = synthetic_cost_matrix.coverage_ratio()
        assert 0.0 <= cr <= 1.0

    def test_feasible_pairs_sorted(self, synthetic_cost_matrix, ten_candidates):
        pairs = synthetic_cost_matrix.feasible_pairs(ten_candidates[0])
        costs = [c for _, c in pairs]
        assert costs == sorted(costs)

    def test_feasible_pairs_max_dist(self, synthetic_cost_matrix, ten_candidates):
        """max_dist_m filtre correctement."""
        max_d = 300.0
        pairs = synthetic_cost_matrix.feasible_pairs(
            ten_candidates[0], max_dist_m=max_d
        )
        for cand, cost in pairs:
            d = ten_candidates[0].geom.distance(cand.geom)
            assert d <= max_d


# ---------------------------------------------------------------------------
# Tests génération constructive
# ---------------------------------------------------------------------------

class TestGenerateInitialCourse:
    def test_returns_course(self, ten_candidates, synthetic_cost_matrix, forest_profile):
        course = generate_initial_course(
            ten_candidates, synthetic_cost_matrix, forest_profile,
            rng=random.Random(42),
        )
        assert isinstance(course, Course)

    def test_min_controls(self, ten_candidates, synthetic_cost_matrix, forest_profile):
        course = generate_initial_course(
            ten_candidates, synthetic_cost_matrix, forest_profile,
            rng=random.Random(42),
        )
        assert course.n_controls >= 2

    def test_all_controls_unique(self, ten_candidates, synthetic_cost_matrix, forest_profile):
        course = generate_initial_course(
            ten_candidates, synthetic_cost_matrix, forest_profile,
            rng=random.Random(42),
        )
        # Seul le départ peut être identique à l'arrivée (IOF standard)
        # → tous les intermédiaires doivent être uniques
        intermediate_ids = [c.id for c in course.controls[1:-1]]
        assert len(intermediate_ids) == len(set(intermediate_ids)), (
            "Des postes intermédiaires sont dupliqués"
        )

    def test_profile_set(self, ten_candidates, synthetic_cost_matrix, forest_profile):
        course = generate_initial_course(
            ten_candidates, synthetic_cost_matrix, forest_profile,
            rng=random.Random(42),
        )
        assert course.profile.id == forest_profile.id

    def test_reproducible_with_seed(self, ten_candidates, synthetic_cost_matrix, forest_profile):
        c1 = generate_initial_course(
            ten_candidates, synthetic_cost_matrix, forest_profile,
            rng=random.Random(99),
        )
        c2 = generate_initial_course(
            ten_candidates, synthetic_cost_matrix, forest_profile,
            rng=random.Random(99),
        )
        assert [c.id for c in c1.controls] == [c.id for c in c2.controls]


# ---------------------------------------------------------------------------
# Tests optimisation locale
# ---------------------------------------------------------------------------

class TestImproveCoursLocal:
    def test_score_does_not_decrease(
        self, ten_candidates, synthetic_cost_matrix, forest_profile
    ):
        """Le score du best doit être ≥ au score initial en moyenne."""
        scores_initial = []
        scores_improved = []

        for seed in range(5):
            rng = random.Random(seed)
            course = generate_initial_course(
                ten_candidates, synthetic_cost_matrix, forest_profile, rng=rng
            )
            course = course.compute_metrics(synthetic_cost_matrix)
            bd_init = score_course(course, synthetic_cost_matrix, forest_profile)

            improved = improve_course_local(
                course, ten_candidates, synthetic_cost_matrix, forest_profile,
                n_iter=50, rng=random.Random(seed + 100),
            )
            bd_improved = score_course(improved, synthetic_cost_matrix, forest_profile)

            scores_initial.append(bd_init.global_score)
            scores_improved.append(bd_improved.global_score)

        mean_init = sum(scores_initial) / len(scores_initial)
        mean_impr = sum(scores_improved) / len(scores_improved)
        assert mean_impr >= mean_init, (
            f"Optimisation locale dégrade le score : {mean_init:.2f} → {mean_impr:.2f}"
        )

    def test_improved_course_valid(
        self, ten_candidates, synthetic_cost_matrix, forest_profile
    ):
        course = generate_initial_course(
            ten_candidates, synthetic_cost_matrix, forest_profile,
            rng=random.Random(7),
        )
        improved = improve_course_local(
            course, ten_candidates, synthetic_cost_matrix, forest_profile,
            n_iter=30, rng=random.Random(77),
        )
        assert isinstance(improved, Course)
        assert improved.n_controls >= 2
        # Seul départ = arrivée est acceptable (IOF standard)
        intermediate_ids = [c.id for c in improved.controls[1:-1]]
        assert len(intermediate_ids) == len(set(intermediate_ids)), (
            "Doublons parmi les postes intermédiaires après optimisation"
        )

    def test_sa_does_not_crash(
        self, ten_candidates, synthetic_cost_matrix, forest_profile
    ):
        course = generate_initial_course(
            ten_candidates, synthetic_cost_matrix, forest_profile,
            rng=random.Random(1),
        )
        improved = improve_course_local(
            course, ten_candidates, synthetic_cost_matrix, forest_profile,
            n_iter=20, use_sa=True, rng=random.Random(2),
        )
        assert isinstance(improved, Course)
