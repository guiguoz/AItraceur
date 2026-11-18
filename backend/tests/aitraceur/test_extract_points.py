"""Tests des adaptateurs _extract_circuit_points et _extract_sprint_points.

Les fixtures JSON dans fixtures/v1_outputs/ représentent le format réel des
sorties de _circuit_impl et de _sprint_tasks[task_id]["result"].
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.aitraceur.evalbench.replay_v1 import (
    _extract_circuit_points,
    _extract_sprint_points,
)

FIXTURES = Path(__file__).parent / "fixtures" / "v1_outputs"


class TestExtractCircuitPoints:
    def setup_method(self) -> None:
        self.result = json.loads((FIXTURES / "circuit_sample.json").read_text(encoding="utf-8"))

    def test_returns_four_points(self) -> None:
        pts = _extract_circuit_points(self.result)
        assert len(pts) == 4

    def test_first_point_is_lng_lat(self) -> None:
        pts = _extract_circuit_points(self.result)
        # Premier point : [2.350, 49.120] → (2.350, 49.120)
        assert pts[0] == pytest.approx((2.350, 49.120))

    def test_all_tuples_of_floats(self) -> None:
        pts = _extract_circuit_points(self.result)
        for p in pts:
            assert len(p) == 2
            assert all(isinstance(v, float) for v in p)

    def test_raises_on_empty_circuits(self) -> None:
        with pytest.raises(ValueError, match="Aucun circuit"):
            _extract_circuit_points({"circuits": []})


class TestExtractSprintPoints:
    def setup_method(self) -> None:
        self.result = json.loads((FIXTURES / "sprint_sample.json").read_text(encoding="utf-8"))

    def test_returns_four_points(self) -> None:
        pts = _extract_sprint_points(self.result)
        assert len(pts) == 4

    def test_first_point_is_lng_lat(self) -> None:
        pts = _extract_sprint_points(self.result)
        assert pts[0] == pytest.approx((2.350, 49.120))

    def test_x_is_lng_y_is_lat(self) -> None:
        pts = _extract_sprint_points(self.result)
        # x=2.355, y=49.125 → (lng=2.355, lat=49.125)
        assert pts[1] == pytest.approx((2.355, 49.125))

    def test_empty_controls_returns_empty_list(self) -> None:
        pts = _extract_sprint_points({"controls": []})
        assert pts == []
