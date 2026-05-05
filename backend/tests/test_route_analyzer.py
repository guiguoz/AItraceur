"""
Tests — RouteAnalyzer : count_decision_points, _is_significant_fork,
route_diversity_info, get_cache_stats.

Graphe synthétique T-junction :

    A ------- B ------- C
              |
              D

A = (0.000, 0.000)
B = (0.001, 0.000)   nœud de bifurcation (degree 3)
C = (0.002, 0.000)
D = (0.001,-0.001)

Way 1 : A → B → C  (axe est-ouest)
Way 2 : B → D       (branche sud)
"""
from __future__ import annotations

import math
import pytest

try:
    from src.services.optimization.route_analyzer import RouteAnalyzer
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="RouteAnalyzer non disponible")


# ---------------------------------------------------------------------------
# Fixture — graphe T-junction
# ---------------------------------------------------------------------------

A = (0.000, 0.000)
B = (0.001, 0.000)
C = (0.002, 0.000)
D = (0.001, -0.001)


@pytest.fixture
def t_junction() -> RouteAnalyzer:
    ways = [
        [A, B, C],  # chemin est-ouest
        [B, D],     # branche sud
    ]
    return RouteAnalyzer(ways)


# ---------------------------------------------------------------------------
# _is_significant_fork
# ---------------------------------------------------------------------------

class TestIsSignificantFork:
    def test_fork_at_B(self, t_junction):
        """B a 3 voisins avec angles > 30° → bifurcation significative."""
        assert t_junction._is_significant_fork(B) is True

    def test_no_fork_at_A(self, t_junction):
        """A n'a qu'un voisin (B) → degré 1, pas de fork."""
        assert t_junction._is_significant_fork(A) is False

    def test_no_fork_at_C(self, t_junction):
        """C n'a qu'un voisin (B) → pas de fork."""
        assert t_junction._is_significant_fork(C) is False

    def test_nearly_straight_junction_with_path_context(self):
        """Embranchement quasi-droit (<5°) exclu quand la direction chemin est connue."""
        M = (0.001, 0.000)
        L = (0.000, 0.000)
        R = (0.002, 0.000)
        S = (0.001 + 0.0001, 0.000 + 0.000001)  # branche quasi-parallèle à M→R
        analyzer = RouteAnalyzer([[L, M, R], [M, S]])
        # Avec contexte chemin L→M→R : S dévie de <5° de M→R → pas de fork
        assert analyzer._has_significant_alternative(M, L, R) is False


# ---------------------------------------------------------------------------
# count_decision_points
# ---------------------------------------------------------------------------

class TestCountDecisionPoints:
    def test_A_to_C_has_one_decision_point(self, t_junction):
        """Route A→C passe par B (fork), donc 1 point de décision."""
        n = t_junction.count_decision_points(A[0], A[1], C[0], C[1])
        assert n == 1

    def test_A_to_D_has_one_decision_point(self, t_junction):
        """Route A→D passe par B (fork), donc 1 point de décision."""
        n = t_junction.count_decision_points(A[0], A[1], D[0], D[1])
        assert n == 1

    def test_B_to_C_no_decision_point(self, t_junction):
        """Route B→C : B est le départ, pas un nœud intermédiaire → 0."""
        n = t_junction.count_decision_points(B[0], B[1], C[0], C[1])
        assert n == 0

    def test_same_start_end_returns_zero(self, t_junction):
        """Départ = arrivée → route None (n_start == n_end) → 0 points de décision."""
        n = t_junction.count_decision_points(B[0], B[1], B[0], B[1])
        assert n == 0


# ---------------------------------------------------------------------------
# route_diversity_info
# ---------------------------------------------------------------------------

class TestRouteDiversityInfo:
    def test_single_path_returns_zero_jaccard(self, t_junction):
        """A→B : une seule route possible → jaccard=0, credible_routes=1."""
        info = t_junction.route_diversity_info(A[0], A[1], B[0], B[1])
        assert info["jaccard"] == 0.0
        assert info["credible_routes"] == 1

    def test_returns_dict_keys(self, t_junction):
        info = t_junction.route_diversity_info(A[0], A[1], C[0], C[1])
        assert "jaccard" in info
        assert "credible_routes" in info

    def test_jaccard_range(self, t_junction):
        info = t_junction.route_diversity_info(A[0], A[1], C[0], C[1])
        assert 0.0 <= info["jaccard"] <= 1.0

    def test_credibility_filter_excludes_too_long(self):
        """Une route 50% plus longue que l'optimale doit être exclue."""
        # Graphe avec un détour massif : A→B direct + A→X→Y→B long
        A2 = (0.000, 0.000)
        B2 = (0.001, 0.000)
        X  = (0.000, 0.010)  # nœud très au nord
        Y  = (0.001, 0.010)
        ways = [[A2, B2], [A2, X], [X, Y], [Y, B2]]
        analyzer = RouteAnalyzer(ways)
        info = analyzer.route_diversity_info(A2[0], A2[1], B2[0], B2[1], k=2)
        # Le détour via X,Y est bien plus long que 1.30× → non crédible
        assert info["credible_routes"] == 1


# ---------------------------------------------------------------------------
# route_diversity_score (rétrocompatibilité)
# ---------------------------------------------------------------------------

class TestRouteDiversityScoreBackcompat:
    def test_returns_float(self, t_junction):
        score = t_junction.route_diversity_score(A[0], A[1], C[0], C[1])
        assert isinstance(score, float)

    def test_consistent_with_route_diversity_info(self, t_junction):
        score = t_junction.route_diversity_score(A[0], A[1], C[0], C[1])
        info = t_junction.route_diversity_info(A[0], A[1], C[0], C[1])
        assert abs(score - info["jaccard"]) < 1e-9


# ---------------------------------------------------------------------------
# Cache & get_cache_stats
# ---------------------------------------------------------------------------

class TestCacheStats:
    def test_initial_stats(self, t_junction):
        stats = t_junction.get_cache_stats()
        assert stats["hit_rate"] == 0.0
        assert stats["total_calls"] == 1  # dénominateur min=1

    def test_cache_hit_on_second_call(self, t_junction):
        t_junction.route_diversity_info(A[0], A[1], C[0], C[1], k=2)
        t_junction.route_diversity_info(A[0], A[1], C[0], C[1], k=2)
        stats = t_junction.get_cache_stats()
        assert stats["hit_rate"] > 0.0

    def test_cache_hit_rate_between_0_and_1(self, t_junction):
        for _ in range(3):
            t_junction.route_diversity_info(A[0], A[1], C[0], C[1])
        stats = t_junction.get_cache_stats()
        assert 0.0 <= stats["hit_rate"] <= 1.0
