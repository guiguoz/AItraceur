"""Banc d'essai CLI pour le moteur v1.

Usage depuis backend/ :
    python -m src.aitraceur.evalbench.run v1 \\
        --captures ../captures \\
        --seeds 0 1 2 3 4 \\
        --out ../runs/p0_baseline
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, quantiles

from src.aitraceur.evalbench.metrics import course_metrics, lnglat_to_local_m
from src.aitraceur.evalbench.replay_v1 import replay


def main() -> None:
    parser = argparse.ArgumentParser(description="Banc d'essai moteur v1")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("v1", help="Rejouer des captures v1")
    p.add_argument("--captures", required=True, type=Path)
    p.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    p.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    if args.command == "v1":
        run_v1(captures=args.captures, seeds=args.seeds, out_dir=args.out)


def run_v1(captures: Path, seeds: list[int], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    capture_files = sorted(captures.glob("*.json"))
    if not capture_files:
        print(f"[bench] Aucun fichier capture dans {captures}", file=sys.stderr)
        sys.exit(1)

    results: list[dict] = []
    determinism: dict[str, dict] = {}
    cache_states: dict[str, dict] = {}

    for cap in capture_files:
        body = json.loads(cap.read_text(encoding="utf-8"))
        kind = cap.name.split("_")[0]
        cluster_r = 60.0 if kind == "sprint" else 150.0
        bbox_wgs = _bbox_from_body(body)
        forbidden_wgs: list = body.get("forbidden_zones_polygons") or []

        # ── Préchauffage (non mesuré) ──────────────────────────────────────────
        # Chauffe le cache sprint_features : froid et chaud produisent des
        # candidats différents → sans préchauffage, seed 0 mesuré « froid »
        # diffère du rejeu déterminisme → fausse alarme determinism=False.
        npz_before = _count_npz_caches()
        osm_before = _count_osm_caches()
        print(
            f"[bench] {cap.name} préchauffage (hmc_npz={npz_before}, osm_json={osm_before})...",
            flush=True,
        )
        replay(cap, 0)
        npz_after = _count_npz_caches()
        osm_after = _count_osm_caches()
        cache_states[cap.name] = {
            "hmc_npz_before": npz_before,
            "hmc_npz_after": npz_after,
            "osm_json_before": osm_before,
            "osm_json_after": osm_after,
        }

        # ── Mesures warm (tous les seeds) ─────────────────────────────────────
        seed0_points: list[tuple[float, float]] | None = None
        for seed in seeds:
            rr = replay(cap, seed)
            row: dict = {
                "capture": rr.capture,
                "kind": rr.kind,
                "seed": rr.seed,
                "ok": rr.ok,
                "error": rr.error,
                "runtime_s": round(rr.runtime_s, 3),
            }
            if rr.ok and len(rr.points_lnglat) >= 2 and bbox_wgs is not None:
                try:
                    row.update(_compute_metrics(
                        rr.points_lnglat, bbox_wgs, forbidden_wgs, cluster_r,
                    ))
                except Exception as exc:
                    row["metrics_error"] = str(exc)
            results.append(row)
            if seed == 0:
                seed0_points = rr.points_lnglat
            print(
                f"[bench] {cap.name} seed={seed} ok={rr.ok} t={rr.runtime_s:.1f}s",
                flush=True,
            )

        # ── Vérification déterminisme (rejeu seed 0 après les mesures) ────────
        r0 = replay(cap, 0)
        identical = (
            seed0_points is not None
            and r0.ok
            and seed0_points == r0.points_lnglat
        )
        determinism[cap.name] = {"identical": identical}
        print(f"[bench] {cap.name} déterminisme={identical}", flush=True)

    _write_jsonl(out_dir / "results.jsonl", results)
    _write_summary(out_dir / "summary.md", results, capture_files, determinism)
    (out_dir / "determinism.json").write_text(
        json.dumps({"results": determinism}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_metadata(out_dir / "run_metadata.json", capture_files, cache_states)
    print(f"[bench] Résultats dans {out_dir}", flush=True)


# ---------------------------------------------------------------------------
# Helpers géométriques
# ---------------------------------------------------------------------------

def _bbox_from_body(body: dict) -> tuple[float, float, float, float] | None:
    bb = body.get("bounding_box") or {}
    if not all(k in bb for k in ("min_x", "min_y", "max_x", "max_y")):
        return None
    return bb["min_x"], bb["min_y"], bb["max_x"], bb["max_y"]


def _compute_metrics(
    points_lnglat: list[tuple[float, float]],
    bbox_wgs: tuple[float, float, float, float],
    forbidden_wgs: list,
    cluster_r: float,
) -> dict:
    center = ((bbox_wgs[0] + bbox_wgs[2]) / 2, (bbox_wgs[1] + bbox_wgs[3]) / 2)
    pts_m = lnglat_to_local_m(points_lnglat, center)

    corners = [
        (bbox_wgs[0], bbox_wgs[1]),
        (bbox_wgs[2], bbox_wgs[1]),
        (bbox_wgs[2], bbox_wgs[3]),
        (bbox_wgs[0], bbox_wgs[3]),
    ]
    corners_m = lnglat_to_local_m(corners, center)
    xs = [p[0] for p in corners_m]
    ys = [p[1] for p in corners_m]
    bbox_m = (min(xs), min(ys), max(xs), max(ys))

    forbidden_m: list[list[tuple[float, float]]] = []
    for poly_raw in forbidden_wgs:
        if not poly_raw or len(poly_raw) < 3:
            continue
        poly_pts = [(float(pt[0]), float(pt[1])) for pt in poly_raw]
        forbidden_m.append(lnglat_to_local_m(poly_pts, center))

    m = course_metrics(pts_m, area_bbox=bbox_m, forbidden=forbidden_m, cluster_radius_m=cluster_r)
    return {
        "n_controls": m.n_controls,
        "length_m": m.length_m,
        "leg_min_m": m.leg_min_m,
        "leg_max_m": m.leg_max_m,
        "leg_cv": m.leg_cv,
        "min_pair_dist_m": m.min_pair_dist_m,
        "n_pairs_below_30m": m.n_pairs_below_30m,
        "n_pairs_below_60m": m.n_pairs_below_60m,
        "crossings": m.crossings,
        "doglegs": m.doglegs,
        "max_in_radius": m.max_in_radius,
        "n_clustered": m.n_clustered,
        "coverage_4x4": m.coverage_4x4,
        "hull_ratio": m.hull_ratio,
        "is_loop": m.is_loop,
        "forbidden_hits": m.forbidden_hits,
    }


# ---------------------------------------------------------------------------
# Écriture des fichiers de sortie
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


_SUMMARY_KEYS = [
    "length_m", "leg_min_m", "leg_max_m", "leg_cv",
    "min_pair_dist_m", "n_pairs_below_30m", "n_pairs_below_60m",
    "crossings", "doglegs", "max_in_radius", "n_clustered",
    "coverage_4x4", "hull_ratio", "is_loop", "forbidden_hits",
]


def _write_summary(
    path: Path,
    results: list[dict],
    captures: list[Path],
    determinism: dict[str, dict],
) -> None:
    lines = ["# Résumé banc d'essai moteur v1\n"]
    for cap in captures:
        ok_rows = [r for r in results if r["capture"] == cap.name and r.get("ok")]
        lines.append(f"\n## {cap.name}\n")
        det = determinism.get(cap.name, {})
        identical = det.get("identical")
        det_symbol = "✓" if identical else ("✗" if identical is False else "?")
        lines.append(f"Déterminisme : {det_symbol}  \n")
        if not ok_rows:
            lines.append("_Aucun résultat valide._\n")
            continue
        lines.append(f"N trajectoires valides : {len(ok_rows)}\n\n")
        lines.append("| Indicateur | Médiane | IQR |\n|---|---|---|\n")
        for k in _SUMMARY_KEYS:
            vals = [r[k] for r in ok_rows if k in r]
            if not vals:
                continue
            med = median(vals)
            iqr = (quantiles(vals, n=4)[2] - quantiles(vals, n=4)[0]) if len(vals) >= 4 else (max(vals) - min(vals))
            lines.append(f"| {k} | {med:.2f} | {iqr:.2f} |\n")
    path.write_text("".join(lines), encoding="utf-8")


def _count_npz_caches() -> int:
    """Compte les fichiers heatmap (.npz) dans le répertoire temporaire."""
    import tempfile
    return len(list(Path(tempfile.gettempdir()).glob("aitraceur_hmc_*.npz")))


def _count_osm_caches() -> int:
    """Compte les fichiers OSM/sprint_features (.json) dans le répertoire temporaire."""
    import tempfile
    d = Path(tempfile.gettempdir()) / "aitraceur_osm"
    return len(list(d.glob("*.json"))) if d.is_dir() else 0


def _write_metadata(path: Path, captures: list[Path], cache_states: dict[str, dict]) -> None:
    import numpy as np
    import scipy

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL,
        ).strip())
    except Exception:
        commit, dirty = "unknown", None

    try:
        import urllib.request as _ur
        _ur.urlopen("http://localhost:8089/health", timeout=2)
        tile_ok = True
    except Exception:
        tile_ok = False

    from src.core.config import settings

    meta = {
        "commit": commit,
        "dirty": dirty,
        "AITRACEUR_ONLINE": settings.AITRACEUR_ONLINE,
        "tile_service_reachable": tile_ok,
        "python_version": sys.version,
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "n_captures": len(captures),
        "sprint_features_cache": cache_states,
    }
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
