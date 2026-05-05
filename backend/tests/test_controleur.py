"""
Tests — ControleurSprint : C18 (route choice minimum TD3+),
C19 (handrail excess TD4/TD5), C20 (route choice excess TD3).

Les checks C18/C19/C20 opèrent uniquement sur nav_scores (list de dicts)
et td_key (str). La liste controls n'est pas utilisée par ces méthodes.
"""
from __future__ import annotations

import pytest

try:
    from src.services.controleur.controleur import ControleurSprint
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="ControleurSprint non disponible")


@pytest.fixture
def ctrl() -> ControleurSprint:
    return ControleurSprint()


# ---------------------------------------------------------------------------
# Helpers — construction de nav_scores synthétiques
# ---------------------------------------------------------------------------

def _ns_rc(jaccard: float) -> dict:
    """Nav score dominé par route_choice (handrail neutre, catch neutre)."""
    return {
        "route_diversity": {"jaccard": jaccard, "credible_routes": 2},
        "handrail": 0.0,
        "catch": 0.5,
    }


def _ns_hr(handrail: float) -> dict:
    """Nav score dominé par handrail (jaccard faible, catch neutre)."""
    return {
        "route_diversity": {"jaccard": 0.0, "credible_routes": 1},
        "handrail": handrail,
        "catch": 0.5,
    }


# ---------------------------------------------------------------------------
# C18 — minimum legs route_choice (TD3+)
# Règle : min_route_choice_legs {"TD3": 1, "TD4": 2, "TD5": 2}, min_jaccard=0.25
# ---------------------------------------------------------------------------

class TestC18MinRouteChoice:

    def test_td3_zero_route_choice_triggers_warning(self, ctrl):
        # 0 legs avec jaccard ≥ 0.25 alors que TD3 requiert ≥ 1 → WARNING C18
        nav_scores = [_ns_rc(0.10), _ns_rc(0.05), _ns_rc(0.15)]
        issues = ctrl._check_c18_min_route_choice([], nav_scores, "TD3")
        assert len(issues) == 1
        assert issues[0].code == "C18"
        assert issues[0].severity == "WARNING"

    def test_td3_one_qualifying_leg_no_warning(self, ctrl):
        # 1 leg avec jaccard=0.30 ≥ 0.25 → satisfait le min de 1 pour TD3
        nav_scores = [_ns_rc(0.30), _ns_rc(0.10), _ns_rc(0.10)]
        issues = ctrl._check_c18_min_route_choice([], nav_scores, "TD3")
        assert issues == []

    def test_td4_one_qualifying_leg_triggers_warning(self, ctrl):
        # TD4 requiert ≥ 2 legs — 1 qualifié → WARNING
        nav_scores = [_ns_rc(0.30), _ns_rc(0.10), _ns_rc(0.10)]
        issues = ctrl._check_c18_min_route_choice([], nav_scores, "TD4")
        assert len(issues) == 1
        assert issues[0].code == "C18"

    def test_td4_two_qualifying_legs_no_warning(self, ctrl):
        nav_scores = [_ns_rc(0.30), _ns_rc(0.35), _ns_rc(0.10)]
        issues = ctrl._check_c18_min_route_choice([], nav_scores, "TD4")
        assert issues == []

    def test_td1_not_in_rules_silent(self, ctrl):
        # TD1 absent de min_route_choice_legs → silencieux
        nav_scores = [_ns_rc(0.0)] * 5
        issues = ctrl._check_c18_min_route_choice([], nav_scores, "TD1")
        assert issues == []

    def test_td2_not_in_rules_silent(self, ctrl):
        nav_scores = [_ns_rc(0.0)] * 5
        issues = ctrl._check_c18_min_route_choice([], nav_scores, "TD2")
        assert issues == []

    def test_jaccard_exact_min_threshold_counts(self, ctrl):
        # jaccard=0.25 == min_jaccard → doit compter
        nav_scores = [_ns_rc(0.25), _ns_rc(0.10)]
        issues = ctrl._check_c18_min_route_choice([], nav_scores, "TD3")
        assert issues == []


# ---------------------------------------------------------------------------
# C19 — handrail excess (TD4/TD5)
# Règle : max_handrail_ratio {"TD4": 0.70, "TD5": 0.60}, handrail_threshold=0.70
# ---------------------------------------------------------------------------

class TestC19HandrailExcess:

    def test_td5_87pct_handrail_triggers_warning(self, ctrl):
        # 7/8 = 87.5% > 60% → WARNING C19
        nav_scores = [_ns_hr(0.80)] * 7 + [_ns_hr(0.20)]
        issues = ctrl._check_c19_handrail_excess([], nav_scores, "TD5")
        assert len(issues) == 1
        assert issues[0].code == "C19"
        assert issues[0].severity == "WARNING"

    def test_td5_50pct_handrail_no_warning(self, ctrl):
        # 4/8 = 50% ≤ 60% → OK
        nav_scores = [_ns_hr(0.80)] * 4 + [_ns_hr(0.20)] * 4
        issues = ctrl._check_c19_handrail_excess([], nav_scores, "TD5")
        assert issues == []

    def test_td4_100pct_handrail_triggers_warning(self, ctrl):
        # TD4 : max 70% — 8/8 = 100% > 70% → WARNING
        nav_scores = [_ns_hr(0.80)] * 8
        issues = ctrl._check_c19_handrail_excess([], nav_scores, "TD4")
        assert len(issues) == 1
        assert issues[0].code == "C19"

    def test_td4_60pct_handrail_no_warning(self, ctrl):
        # 6/10 = 60% ≤ 70% → OK
        nav_scores = [_ns_hr(0.80)] * 6 + [_ns_hr(0.20)] * 4
        issues = ctrl._check_c19_handrail_excess([], nav_scores, "TD4")
        assert issues == []

    def test_td3_not_in_rules_silent(self, ctrl):
        # TD3 absent de max_handrail_ratio → silencieux même avec 100% handrail
        nav_scores = [_ns_hr(0.90)] * 8
        issues = ctrl._check_c19_handrail_excess([], nav_scores, "TD3")
        assert issues == []

    def test_handrail_below_threshold_not_counted(self, ctrl):
        # handrail=0.65 < threshold=0.70 → ne compte pas comme handrail leg
        nav_scores = [_ns_hr(0.65)] * 8
        issues = ctrl._check_c19_handrail_excess([], nav_scores, "TD5")
        assert issues == []


# ---------------------------------------------------------------------------
# C20 — route_choice excess (TD3)
# Règle : max_route_choice_ratio {"TD3": 0.60}, min_jaccard=0.25
# ---------------------------------------------------------------------------

class TestC20RouteChoiceExcess:

    def test_td3_65pct_route_choice_triggers_warning(self, ctrl):
        # 13/20 = 65% > 60% → WARNING C20
        nav_scores = [_ns_rc(0.40)] * 13 + [_ns_rc(0.05)] * 7
        issues = ctrl._check_c20_route_choice_excess([], nav_scores, "TD3")
        assert len(issues) == 1
        assert issues[0].code == "C20"
        assert issues[0].severity == "WARNING"

    def test_td3_50pct_route_choice_no_warning(self, ctrl):
        # 5/10 = 50% ≤ 60% → OK
        nav_scores = [_ns_rc(0.40)] * 5 + [_ns_rc(0.05)] * 5
        issues = ctrl._check_c20_route_choice_excess([], nav_scores, "TD3")
        assert issues == []

    def test_td3_exact_60pct_no_warning(self, ctrl):
        # 6/10 = 60% = seuil → condition ratio ≤ max_ratio → OK (pas strictement supérieur)
        nav_scores = [_ns_rc(0.40)] * 6 + [_ns_rc(0.05)] * 4
        issues = ctrl._check_c20_route_choice_excess([], nav_scores, "TD3")
        assert issues == []

    def test_td4_not_in_rules_silent(self, ctrl):
        # TD4 absent de max_route_choice_ratio → silencieux
        nav_scores = [_ns_rc(0.80)] * 10
        issues = ctrl._check_c20_route_choice_excess([], nav_scores, "TD4")
        assert issues == []

    def test_td5_not_in_rules_silent(self, ctrl):
        nav_scores = [_ns_rc(0.80)] * 10
        issues = ctrl._check_c20_route_choice_excess([], nav_scores, "TD5")
        assert issues == []

    def test_jaccard_below_min_not_counted(self, ctrl):
        # jaccard=0.20 < min_jaccard=0.25 → ne compte pas → 0% → OK
        nav_scores = [_ns_rc(0.20)] * 10
        issues = ctrl._check_c20_route_choice_excess([], nav_scores, "TD3")
        assert issues == []
