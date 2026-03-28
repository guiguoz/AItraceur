"""
Tests pour les nouvelles couches métier :
  - ControlCandidate : nouveaux champs (visibility_radius, trap_potential, …)
  - Leg / compute_leg_features
  - LegCache
  - controls/enricher : enrich_candidates, select_elite_candidates
  - scoring/flow : rhythm, variation, flow, controls_quality, legs_quality
  - CourseMetrics : nouveaux champs enrichis
  - CourseScoreBreakdown : 3 nouveaux sous-scores
  - build_cost_matrix : paramètre n_workers
"""
from __future__ import annotations

import math
import pytest
from shapely.geometry import Point

from src.aitraceur.controls.candidate import ControlCandidate, DetailType
from src.aitraceur.controls.enricher import enrich_candidates, select_elite_candidates
from src.aitraceur.matrix.leg_cache import LegCache
from src.aitraceur.model.leg import Leg, compute_leg_features
from src.aitraceur.scoring.flow import (
    compute_flow_score,
    compute_rhythm_score,
    compute_variation_score,
    score_controls_quality,
    score_legs_quality,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cand(cid: str, x: float, y: float,
          detail: DetailType = DetailType.BOULDER,
          attr: float = 0.8) -> ControlCandidate:
    return ControlCandidate(
        id=cid,
        geom=Point(x, y),
        detail_type=detail,
        attractiveness_score=attr,
        readability_score=0.85,
        allowed_profiles=frozenset({"FOREST_MD_ORANGE", "SPRINT_URBAN"}),
    )


# ---------------------------------------------------------------------------
# P1 — ControlCandidate nouveaux champs
# ---------------------------------------------------------------------------

class TestControlCandidateNewFields:
    def test_defaults(self):
        c = _cand("c1", 0, 0)
        assert c.visibility_radius == 30.0
        assert c.trap_potential == 0.0
        assert c.landmark_strength == 0.5
        assert c.approach_directions == []

    def test_quality_score_range(self):
        c = _cand("c1", 0, 0)
        assert 0.0 <= c.quality_score <= 1.0

    def test_quality_score_high_isolation(self):
        from dataclasses import replace
        c = replace(
            _cand("c1", 0, 0),
            isolation_score=1.0,
            landmark_strength=1.0,
            trap_potential=0.0,
        )
        assert c.quality_score >= c.composite_score

    def test_composite_score_unchanged(self):
        """composite_score ne doit pas avoir changé de formule."""
        c = _cand("c1", 0, 0, attr=0.8)
        expected = 0.6 * 0.8 + 0.4 * 0.85
        assert abs(c.composite_score - expected) < 1e-9


# ---------------------------------------------------------------------------
# P2 — Leg et compute_leg_features
# ---------------------------------------------------------------------------

class TestLeg:
    def test_compute_basic(self):
        start = _cand("s", 0, 0)
        end   = _cand("e", 300, 0)
        leg = compute_leg_features(start, end)
        assert leg.start_id == "s"
        assert leg.end_id == "e"
        assert abs(leg.distance - 300.0) < 1e-6
        assert 0.0 <= leg.bearing_deg <= 360.0

    def test_bearing_change_first_leg_is_zero(self):
        start = _cand("s", 0, 0)
        end   = _cand("e", 100, 0)
        leg = compute_leg_features(start, end, prev_bearing=None)
        assert leg.bearing_change_deg == 0.0

    def test_bearing_change_computed(self):
        start = _cand("s", 0, 0)
        end   = _cand("e", 100, 0)
        leg = compute_leg_features(start, end, prev_bearing=180.0)
        # Arrivée cap 90° (Est), précédent cap 180° (Sud) → changement = 90°
        assert 80.0 < leg.bearing_change_deg < 100.0

    def test_scores_in_range(self):
        start = _cand("s", 0, 0)
        end   = _cand("e", 200, 100)
        leg = compute_leg_features(start, end)
        assert 0.0 <= leg.route_choice_complexity <= 1.0
        assert 0.0 <= leg.runnability <= 1.0
        assert 0.0 <= leg.technical_difficulty <= 1.0
        assert 0.0 <= leg.risk_level <= 1.0

    def test_travel_time_positive(self):
        start = _cand("s", 0, 0)
        end   = _cand("e", 600, 0)
        leg = compute_leg_features(start, end, base_speed_m_per_min=6.0)
        assert leg.travel_time is not None
        assert leg.travel_time > 0.0

    def test_leg_is_frozen(self):
        start = _cand("s", 0, 0)
        end   = _cand("e", 100, 0)
        leg = compute_leg_features(start, end)
        with pytest.raises((AttributeError, TypeError)):
            leg.distance = 999.0  # type: ignore


# ---------------------------------------------------------------------------
# P8 (matrix) — LegCache
# ---------------------------------------------------------------------------

class TestLegCache:
    def _make_leg(self, sid: str, eid: str) -> Leg:
        return Leg(
            start_id=sid, end_id=eid,
            distance=100.0, bearing_deg=90.0, bearing_change_deg=0.0,
            route_choice_complexity=0.1, runnability=0.9,
            technical_difficulty=0.2, risk_level=0.15,
        )

    def test_put_and_get(self):
        cache = LegCache()
        leg = self._make_leg("a", "b")
        cache.put(leg)
        assert cache.get("a", "b") is leg

    def test_get_missing_returns_none(self):
        cache = LegCache()
        assert cache.get("x", "y") is None

    def test_invalidate_removes_entries(self):
        cache = LegCache()
        cache.put(self._make_leg("a", "b"))
        cache.put(self._make_leg("c", "a"))
        removed = cache.invalidate("a")
        assert removed == 2
        assert len(cache) == 0

    def test_clear(self):
        cache = LegCache()
        cache.put(self._make_leg("a", "b"))
        cache.clear()
        assert len(cache) == 0

    def test_get_or_compute_caches(self):
        cache = LegCache()
        start = _cand("s", 0, 0)
        end   = _cand("e", 100, 0)
        leg1 = cache.get_or_compute(start, end)
        leg2 = cache.get_or_compute(start, end)
        assert leg1 is leg2   # même objet = cache hit


# ---------------------------------------------------------------------------
# P5 — controls/enricher
# ---------------------------------------------------------------------------

class TestEnricher:
    def _cluster_candidates(self) -> list[ControlCandidate]:
        """3 blocs regroupés + 1 isolé."""
        return [
            _cand("b1", 0, 0,   DetailType.BOULDER),
            _cand("b2", 5, 0,   DetailType.BOULDER),
            _cand("b3", 10, 0,  DetailType.BOULDER),
            _cand("iso", 500, 500, DetailType.KNOLL),
        ]

    def test_enrich_sets_landmark(self):
        cands = [_cand("c1", 0, 0, DetailType.BOULDER)]
        enriched = enrich_candidates(cands)
        assert len(enriched) == 1
        # Boulder → landmark = 0.80
        assert abs(enriched[0].landmark_strength - 0.80) < 1e-9

    def test_enrich_isolation_cluster(self):
        cands = self._cluster_candidates()
        enriched = enrich_candidates(cands)
        iso_idx = next(i for i, c in enumerate(enriched) if c.id == "iso")
        b1_idx  = next(i for i, c in enumerate(enriched) if c.id == "b1")
        # Le candidat isolé doit avoir une isolation_score > les blocs groupés
        assert enriched[iso_idx].isolation_score > enriched[b1_idx].isolation_score

    def test_enrich_trap_potential_cluster(self):
        cands = self._cluster_candidates()
        enriched = enrich_candidates(cands)
        iso_idx = next(i for i, c in enumerate(enriched) if c.id == "iso")
        b1_idx  = next(i for i, c in enumerate(enriched) if c.id == "b1")
        # Le candidat isolé a un trap_potential < le cluster de blocs
        assert enriched[iso_idx].trap_potential < enriched[b1_idx].trap_potential

    def test_enrich_empty(self):
        assert enrich_candidates([]) == []

    def test_select_elite_basic(self):
        cands = [_cand(f"c{i}", i * 10, 0) for i in range(50)]
        elite = select_elite_candidates(cands, max_count=10)
        assert len(elite) <= 10

    def test_select_elite_min_separation(self):
        cands = [_cand(f"c{i}", i * 5, 0) for i in range(100)]
        elite = select_elite_candidates(cands, max_count=50, min_separation_m=20.0)
        for i in range(len(elite) - 1):
            for j in range(i + 1, len(elite)):
                dist = math.hypot(elite[i].x - elite[j].x, elite[i].y - elite[j].y)
                assert dist >= 20.0 - 1e-6, f"Séparation insuffisante: {dist:.1f}m"

    def test_select_elite_fewer_than_max(self):
        cands = [_cand(f"c{i}", i * 100, 0) for i in range(5)]
        elite = select_elite_candidates(cands, max_count=20)
        assert len(elite) == 5


# ---------------------------------------------------------------------------
# P7 — scoring/flow
# ---------------------------------------------------------------------------

class TestRhythmScore:
    def test_uniform_legs_low(self):
        dists = [300.0] * 10
        score = compute_rhythm_score(dists)
        assert score < 0.3   # CV = 0 → pénalisé

    def test_varied_legs_high(self):
        dists = [100.0, 800.0, 150.0, 600.0, 200.0, 700.0]
        score = compute_rhythm_score(dists)
        assert score > 0.5

    def test_single_leg(self):
        assert compute_rhythm_score([500.0]) == 0.5

    def test_output_range(self):
        import random
        rng = random.Random(42)
        for _ in range(20):
            dists = [rng.uniform(100, 1000) for _ in range(8)]
            s = compute_rhythm_score(dists)
            assert 0.0 <= s <= 1.0


class TestFlowScore:
    def _make_leginfo(self, bc: float, dist: float):
        from src.aitraceur.model.course import LegInfo
        return LegInfo(
            from_idx=0, to_idx=1,
            from_type=DetailType.BOULDER, to_type=DetailType.KNOLL,
            straight_dist_m=dist,
            cost=dist,
            bearing_deg=90.0,
            bearing_change_deg=bc,
        )

    def test_good_bearing_changes(self):
        legs = [self._make_leginfo(bc=75.0, dist=400.0) for _ in range(6)]
        score = compute_flow_score(legs)
        assert score > 0.7

    def test_dogleg_penalized(self):
        legs = [self._make_leginfo(bc=10.0, dist=300.0) for _ in range(5)]
        score = compute_flow_score(legs)
        assert score < 0.7

    def test_uturn_penalized(self):
        legs = [self._make_leginfo(bc=170.0, dist=300.0) for _ in range(5)]
        score = compute_flow_score(legs)
        assert score < 0.5

    def test_empty_legs(self):
        assert compute_flow_score([]) == 0.5


class TestControlsQuality:
    def test_high_quality_controls(self):
        from dataclasses import replace
        controls = [
            replace(_cand("start", 0, 0), attractiveness_score=0.9,
                    isolation_score=0.95, landmark_strength=0.9),
            replace(_cand("c1", 100, 0), attractiveness_score=0.9,
                    isolation_score=0.95, landmark_strength=0.9),
            replace(_cand("finish", 200, 0), attractiveness_score=0.9,
                    isolation_score=0.95, landmark_strength=0.9),
        ]
        score = score_controls_quality(controls)
        assert score >= 0.7

    def test_no_intermediate(self):
        controls = [_cand("s", 0, 0), _cand("f", 100, 0)]
        assert score_controls_quality(controls) == 0.5

    def test_output_range(self):
        controls = [_cand(f"c{i}", i * 50, 0) for i in range(5)]
        s = score_controls_quality(controls)
        assert 0.0 <= s <= 1.0


class TestLegsQuality:
    def _make_enriched_leginfo(self, rcc: float, runn: float, tech: float):
        from src.aitraceur.model.course import LegInfo
        return LegInfo(
            from_idx=0, to_idx=1,
            from_type=DetailType.BOULDER, to_type=DetailType.KNOLL,
            straight_dist_m=300.0, cost=350.0,
            bearing_deg=90.0, bearing_change_deg=60.0,
            route_choice_complexity=rcc,
            runnability=runn,
            technical_difficulty=tech,
        )

    def test_high_quality_legs(self):
        legs = [self._make_enriched_leginfo(0.4, 0.9, 0.3) for _ in range(4)]
        score = score_legs_quality(legs)
        assert score >= 0.5

    def test_empty_legs(self):
        assert score_legs_quality([]) == 0.5

    def test_output_range(self):
        legs = [self._make_enriched_leginfo(0.2, 0.7, 0.4)]
        s = score_legs_quality(legs)
        assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# Intégration — CourseMetrics nouveaux champs via compute_metrics
# ---------------------------------------------------------------------------

class TestCourseMetricsIntegration:
    def test_new_fields_present(self, ten_candidates, forest_profile):
        from src.aitraceur.model.course import Course
        course = Course(controls=ten_candidates[:6], profile=forest_profile)
        course = course.compute_metrics()
        m = course.metrics
        assert hasattr(m, "mean_controls_quality")
        assert hasattr(m, "mean_legs_quality")
        assert hasattr(m, "rhythm_score")
        assert hasattr(m, "variation_score")
        assert hasattr(m, "flow_score")

    def test_new_fields_in_range(self, ten_candidates, forest_profile):
        from src.aitraceur.model.course import Course
        course = Course(controls=ten_candidates[:6], profile=forest_profile)
        course = course.compute_metrics()
        m = course.metrics
        for attr in ("mean_controls_quality", "mean_legs_quality",
                     "rhythm_score", "variation_score", "flow_score"):
            val = getattr(m, attr)
            assert 0.0 <= val <= 1.0, f"{attr} = {val} hors [0,1]"

    def test_leginfo_new_fields(self, ten_candidates, forest_profile):
        from src.aitraceur.model.course import Course
        course = Course(controls=ten_candidates[:4], profile=forest_profile)
        course = course.compute_metrics()
        for leg in course.metrics.legs:
            assert hasattr(leg, "route_choice_complexity")
            assert hasattr(leg, "runnability")
            assert hasattr(leg, "technical_difficulty")
            assert hasattr(leg, "risk_level")
            assert 0.0 <= leg.runnability <= 1.0


# ---------------------------------------------------------------------------
# Intégration — CourseScoreBreakdown 3 nouveaux sous-scores
# ---------------------------------------------------------------------------

class TestBreakdownNewScores:
    def test_new_fields_in_breakdown(self, ten_candidates, forest_profile):
        from src.aitraceur.model.course import Course
        from src.aitraceur.scoring.scorer import score_course
        course = Course(controls=ten_candidates[:6], profile=forest_profile)
        bd = score_course(course)
        assert hasattr(bd, "controls_quality_score")
        assert hasattr(bd, "legs_quality_score")
        assert hasattr(bd, "flow_score")
        assert 0.0 <= bd.controls_quality_score <= 1.0
        assert 0.0 <= bd.legs_quality_score <= 1.0
        assert 0.0 <= bd.flow_score <= 1.0

    def test_to_dict_includes_new_fields(self, ten_candidates, forest_profile):
        from src.aitraceur.model.course import Course
        from src.aitraceur.scoring.scorer import score_course
        course = Course(controls=ten_candidates[:6], profile=forest_profile)
        bd = score_course(course)
        d = bd.to_dict()
        assert "controls_quality_score" in d
        assert "legs_quality_score" in d
        assert "flow_score" in d
