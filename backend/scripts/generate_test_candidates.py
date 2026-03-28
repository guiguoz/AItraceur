#!/usr/bin/env python3
"""
scripts/generate_test_candidates.py — Génère des candidats de test pour run_generator.py.

Usage :
    python scripts/generate_test_candidates.py
    python scripts/generate_test_candidates.py --num 20 --output data/candidates.json
    python scripts/generate_test_candidates.py --seed 123 --lambert  # coordonnées Lambert-93

Le fichier produit est directement consommable par :
    python scripts/run_generator.py --candidates data/candidates.json --output out/course.geojson
"""
import argparse
import json
import random
from pathlib import Path

# Valeurs de detail_type acceptées par DetailType(value) dans load_candidates
_DETAIL_TYPES = [
    "knoll", "hill_top", "saddle", "depression", "pit", "reentrant",
    "boulder", "boulder_cluster", "cliff_foot",
    "pond_edge", "stream_junction", "spring",
    "path_junction", "path_bend", "path_end",
    "building_corner", "wall_corner", "wall_end",
]

# Plages de coordonnées (mètres)
# Lambert-93 : zone Île-de-France (~Paris)
_LAMBERT_X = (640_000.0, 660_000.0)
_LAMBERT_Y = (6_855_000.0, 6_875_000.0)
# Petit terrain synthétique (compatible avec les GeoTIFF de run_visual_tests.py)
_SYNTHETIC_X = (50.0, 550.0)
_SYNTHETIC_Y = (50.0, 550.0)


def generate_candidates(
    num: int,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    rng: random.Random,
) -> list[dict]:
    candidates = []
    for i in range(1, num + 1):
        candidates.append({
            "id": i,
            "x": round(rng.uniform(*x_range), 2),
            "y": round(rng.uniform(*y_range), 2),
            "detail_type": rng.choice(_DETAIL_TYPES),
            "symbol_id": rng.choice([101, 102, 103, 104, 201, 202, 301]),
            "attractiveness_score": round(rng.uniform(0.4, 1.0), 3),
            "readability_score":    round(rng.uniform(0.5, 1.0), 3),
            "technical_level":      rng.randint(1, 4),
        })
    return candidates


def main() -> None:
    p = argparse.ArgumentParser(
        description="Génère des candidats aléatoires pour run_generator.py.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--num",    type=int,  default=20,
                   help="Nombre de candidats à générer.")
    p.add_argument("--output", default="data/candidates.json",
                   help="Fichier JSON de sortie.")
    p.add_argument("--seed",   type=int,  default=42,
                   help="Graine aléatoire (reproductibilité).")
    p.add_argument("--lambert", action="store_true",
                   help="Utiliser des coordonnées Lambert-93 (Île-de-France) "
                        "au lieu du terrain synthétique [0–600 m].")
    args = p.parse_args()

    rng = random.Random(args.seed)
    x_range, y_range = (
        (_LAMBERT_X, _LAMBERT_Y) if args.lambert else (_SYNTHETIC_X, _SYNTHETIC_Y)
    )

    candidates = generate_candidates(args.num, x_range, y_range, rng)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")

    mode = "Lambert-93" if args.lambert else "synthétique [0–600 m]"
    print(f"OK  {len(candidates)} candidats ({mode}) → {out.resolve()}")
    print(f"\nTest rapide :")
    print(f"  python scripts/run_generator.py \\")
    print(f"      --candidates {args.output} \\")
    print(f"      --output output/course.geojson")


if __name__ == "__main__":
    main()
