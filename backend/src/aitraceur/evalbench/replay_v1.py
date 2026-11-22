"""Rejoue une requête capturée via le moteur v1 (src.main).

Seul module du moteur v2 autorisé à importer src.main — exception inscrite
dans tests/aitraceur/test_architecture.py.

Lancer depuis backend/ pour que les chemins relatifs de src.main fonctionnent.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ReplayResult:
    capture: str
    kind: str
    seed: int
    ok: bool
    error: Optional[str]
    points_lnglat: list[tuple[float, float]]  # (lng, lat) — départ, postes, arrivée
    runtime_s: float


def replay(capture_path: Path, seed: int) -> ReplayResult:
    """Charge un corps capturé, force ga_seed=seed, appelle le moteur v1."""
    import src.main as _main  # noqa: PLC0415

    capture = capture_path.name
    body = json.loads(capture_path.read_text(encoding="utf-8"))
    body["ga_seed"] = seed
    kind = _kind_from_name(capture)

    t0 = time.monotonic()
    try:
        if kind == "circuit":
            result = _main._circuit_impl(body)
            if "error" in result:
                raise RuntimeError(result["error"])
            points = _extract_circuit_points(result)

        elif kind == "sprint":
            task_id = str(uuid.uuid4())
            _main._sprint_tasks[task_id] = {"status": "processing", "result": None}
            _main._sprint_impl(task_id, body)
            task = _main._sprint_tasks.get(task_id, {})
            if task.get("status") == "error":
                err = (task.get("result") or {}).get("error", "unknown error")
                return ReplayResult(
                    capture=capture, kind=kind, seed=seed,
                    ok=False, error=err, points_lnglat=[],
                    runtime_s=time.monotonic() - t0,
                )
            result = task.get("result") or {}
            if "error" in result:
                return ReplayResult(
                    capture=capture, kind=kind, seed=seed,
                    ok=False, error=result["error"], points_lnglat=[],
                    runtime_s=time.monotonic() - t0,
                )
            points = _extract_sprint_points(result)

        else:
            raise ValueError(f"Kind inconnu : {kind!r}")

        return ReplayResult(
            capture=capture, kind=kind, seed=seed,
            ok=True, error=None,
            points_lnglat=points,
            runtime_s=time.monotonic() - t0,
        )
    except Exception as exc:
        return ReplayResult(
            capture=capture, kind=kind, seed=seed,
            ok=False, error=str(exc), points_lnglat=[],
            runtime_s=time.monotonic() - t0,
        )


def _kind_from_name(filename: str) -> str:
    return filename.split("_")[0]


def _extract_circuit_points(result: dict) -> list[tuple[float, float]]:
    """Extrait (lng, lat) du premier circuit retourné par _circuit_impl.

    Le champ controls contient des dicts {"x": lng, "y": lat, ...} — format réel
    de ai_generator.py (GeneratedCircuit.controls).
    """
    circuits = result.get("circuits") or []
    if not circuits:
        raise ValueError("Aucun circuit dans le résultat _circuit_impl")
    controls = circuits[0].get("controls") or []
    return [(float(c["x"]), float(c["y"])) for c in controls]


def _extract_sprint_points(result: dict) -> list[tuple[float, float]]:
    """Extrait (lng, lat) des contrôles sprint retournés par _sprint_impl.

    Le champ controls contient des dicts {"x": lng, "y": lat, ...}.
    """
    controls = result.get("controls") or []
    return [(float(c["x"]), float(c["y"])) for c in controls]
