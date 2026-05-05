"""
Tests — GeneticAlgorithm : _classify_leg_type(), compute_nav_context().
"""
from __future__ import annotations

import pytest

try:
    from src.services.generation.genetic_algo import GeneticAlgorithm, GenerationConfig
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="GeneticAlgorithm non disponible")


@pytest.fixture
def ga() -> GeneticAlgorithm:
    """Instance GA minimale — pas de carte OCAD, pas de RouteAnalyzer."""
    cfg = GenerationConfig(circuit_type="forest", technical_level=3)
    return GeneticAlgorithm(config=cfg)


# ---------------------------------------------------------------------------
# _classify_leg_type — SET non exclusif, seuils depuis placement_rules.json
# Défauts attendus : route_choice_jaccard=0.30, handrail_coverage=0.70, low_catch=0.30
# ---------------------------------------------------------------------------

class TestClassifyLegType:

    def test_all_none_returns_direct(self, ga):
        assert ga._classify_leg_type(None, None, None) == {"direct"}

    def test_all_below_thresholds_returns_direct(self, ga):
        # jaccard=0.10 < 0.30, handrail=0.50 < 0.70, catch=0.60 > 0.30
        assert ga._classify_leg_type(0.10, 0.50, 0.60) == {"direct"}

    def test_route_choice_exact_threshold(self, ga):
        tags = ga._classify_leg_type(0.30, None, None)
        assert "route_choice" in tags
        assert "direct" not in tags

    def test_route_choice_above_threshold(self, ga):
        tags = ga._classify_leg_type(0.45, None, None)
        assert "route_choice" in tags
        assert "direct" not in tags

    def test_route_choice_just_below_threshold(self, ga):
        tags = ga._classify_leg_type(0.29, None, None)
        assert "route_choice" not in tags
        assert "direct" in tags

    def test_handrail_exact_threshold(self, ga):
        tags = ga._classify_leg_type(None, 0.70, None)
        assert "handrail" in tags
        assert "direct" not in tags

    def test_handrail_above_threshold(self, ga):
        tags = ga._classify_leg_type(None, 0.85, None)
        assert "handrail" in tags

    def test_handrail_below_threshold_no_tag(self, ga):
        tags = ga._classify_leg_type(None, 0.65, None)
        assert "handrail" not in tags

    def test_technical_read_exact_threshold(self, ga):
        # catch ≤ 0.30 → technical_read
        tags = ga._classify_leg_type(None, None, 0.30)
        assert "technical_read" in tags
        assert "direct" not in tags

    def test_technical_read_below_threshold(self, ga):
        tags = ga._classify_leg_type(None, None, 0.15)
        assert "technical_read" in tags

    def test_catch_above_threshold_no_technical_read(self, ga):
        tags = ga._classify_leg_type(None, None, 0.50)
        assert "technical_read" not in tags

    def test_route_choice_and_handrail_combined(self, ga):
        # Les tags ne sont pas exclusifs
        tags = ga._classify_leg_type(0.40, 0.80, None)
        assert "route_choice" in tags
        assert "handrail" in tags
        assert "direct" not in tags

    def test_all_three_tags_combined(self, ga):
        # jaccard=0.40, handrail=0.80, catch=0.10 → les trois tags présents
        tags = ga._classify_leg_type(0.40, 0.80, 0.10)
        assert tags == {"route_choice", "handrail", "technical_read"}

    def test_result_is_set(self, ga):
        assert isinstance(ga._classify_leg_type(0.40, None, None), set)


# ---------------------------------------------------------------------------
# compute_nav_context — 6 clés, pas de crash sans RouteAnalyzer ni OCAD tree
# ---------------------------------------------------------------------------

class TestComputeNavContext:

    _EXPECTED_KEYS = {
        "attack_point", "catching_feature", "handrail_samples",
        "optimal_route", "decision_points", "credible_routes",
    }

    def test_returns_six_keys(self, ga):
        result = ga.compute_nav_context(2.0, 48.0, 2.01, 48.01)
        assert set(result.keys()) == self._EXPECTED_KEYS

    def test_no_route_analyzer_returns_empty_route_and_dps(self, ga):
        assert ga._route_analyzer is None
        result = ga.compute_nav_context(2.0, 48.0, 2.01, 48.01)
        assert result["optimal_route"] == []
        assert result["decision_points"] == []
        assert result["credible_routes"] is None

    def test_no_ocad_tree_attack_and_catch_are_none(self, ga):
        # Aucun candidate_point → _ocad_tree=None → attack/catch non calculables
        assert ga._ocad_tree is None
        result = ga.compute_nav_context(2.0, 48.0, 2.01, 48.01)
        assert result["attack_point"] is None
        assert result["catching_feature"] is None

    def test_handrail_samples_is_list(self, ga):
        result = ga.compute_nav_context(2.0, 48.0, 2.01, 48.01)
        assert isinstance(result["handrail_samples"], list)

    def test_different_coords_no_crash(self, ga):
        # Vérifie que la méthode ne plante pas sur des coords quelconques
        result = ga.compute_nav_context(0.0, 0.0, 1.0, 1.0)
        assert set(result.keys()) == self._EXPECTED_KEYS
