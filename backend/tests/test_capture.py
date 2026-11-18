"""Tests de backend/src/api/capture.py (étape 0.7)."""
from __future__ import annotations

import json
import os

import pytest

from src.api.capture import capture_request


BODY = {"bbox": [2.3, 48.8, 2.4, 48.9], "circuit_type": "sprint", "nb_postes": 15}


def test_no_capture_without_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("AITRACEUR_CAPTURE_DIR", raising=False)
    result = capture_request("circuit", BODY)
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_file_written_with_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("AITRACEUR_CAPTURE_DIR", str(tmp_path))
    path = capture_request("circuit", BODY)
    assert path is not None
    assert path.exists()
    assert path.name.startswith("circuit_")
    assert path.name.endswith(".json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == BODY


def test_identical_bodies_same_sha8(tmp_path, monkeypatch):
    monkeypatch.setenv("AITRACEUR_CAPTURE_DIR", str(tmp_path))
    p1 = capture_request("sprint", BODY)
    p2 = capture_request("sprint", BODY)
    assert p1 is not None and p2 is not None
    sha1 = p1.name.rsplit("_", 1)[-1].replace(".json", "")
    sha2 = p2.name.rsplit("_", 1)[-1].replace(".json", "")
    assert sha1 == sha2


def test_kind_in_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("AITRACEUR_CAPTURE_DIR", str(tmp_path))
    p = capture_request("sprint", BODY)
    assert p is not None
    assert p.name.startswith("sprint_")
