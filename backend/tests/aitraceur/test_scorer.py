"""
Tests — Couche 5 : scoring.

Couvre :
  - score_course : sous-scores, global_score, grade
  - Cas extrêmes : parcours trop court, trop long, dog-legs
"""
from __future__ import annotations

import pytest

from src.aitraceur.model.course import Course
from src.aitraceur.scoring.scorer import score_course
from src.aitraceur.scoring.breakdown import CourseScoreBreakdown


class TestScoreCourse:
    def _make_course(self, ten_candidates, forest_profile, n: int = 8):
        controls = ten_candidates[:n]
        return Course(controls=controls, profile=forest_profile)

    def test_returns_breakdown(self, ten_candidates, forest_profile):
        course = self._make_course(ten_candidates, forest_profile)
        bd = score_course(course, profile=forest_profile)
        assert isinstance(bd, CourseScoreBreakdown)

    def test_global_score_in_range(self, ten_candidates, forest_profile):
        course = self._make_course(ten_candidates, forest_profile)
        bd = score_course(course, profile=forest_profile)
        assert 0.0 <= bd.global_score <= 100.0

    def test_subscores_in_unit_range(self, ten_candidates, forest_profile):
        course = self._make_course(ten_candidates, forest_profile)
        bd = score_course(course, profile=forest_profile)
        for field_name in [
            "distance_score", "climb_score", "technical_score",
            "variety_score", "structure_score", "spatial_score", "safety_score",
        ]:
            val = getattr(bd, field_name)
            assert 0.0 <= val <= 1.0, f"{field_name} = {val} hors [0,1]"

    def test_grade_letter(self, ten_candidates, forest_profile):
        course = self._make_course(ten_candidates, forest_profile)
        bd = score_course(course, profile=forest_profile)
        assert bd.grade in {"A", "B", "C", "D"}

    def test_to_dict(self, ten_candidates, forest_profile):
        course = self._make_course(ten_candidates, forest_profile)
        bd = score_course(course, profile=forest_profile)
        d = bd.to_dict()
        assert "global_score" in d
        assert "grade" in d
        assert "distance_score" in d

    def test_short_course_penalized(self, ten_candidates, forest_profile):
        """Un parcours avec seulement 2 postes doit avoir un score faible."""
        short = Course(controls=ten_candidates[:2], profile=forest_profile)
        bd_short = score_course(short, profile=forest_profile)

        long = Course(controls=ten_candidates[:8], profile=forest_profile)
        bd_long = score_course(long, profile=forest_profile)

        # Le parcours plus complet doit scorer mieux
        assert bd_long.global_score > bd_short.global_score

    def test_no_crash_single_control(self, ten_candidates, forest_profile):
        """Un seul poste ne doit pas crasher (même si le score est minimal)."""
        single = Course(controls=ten_candidates[:1], profile=forest_profile)
        bd = score_course(single, profile=forest_profile)
        assert bd.global_score >= 0.0

    def test_weights_sum_reflected(self, ten_candidates, forest_profile):
        """Le score global doit être cohérent avec la somme pondérée des sous-scores."""
        course = self._make_course(ten_candidates, forest_profile)
        bd = score_course(course, profile=forest_profile)
        w = forest_profile.weights
        expected = (
            w.distance * bd.distance_score
            + w.climb * bd.climb_score
            + w.technical * bd.technical_score
            + w.variety * bd.variety_score
            + w.structure * bd.structure_score
            + w.spatial * bd.spatial_score
            + w.safety * bd.safety_score
        ) * 100.0
        assert abs(bd.global_score - expected) < 0.1
