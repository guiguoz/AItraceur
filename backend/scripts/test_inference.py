"""
test_inference.py — Validation visuelle du scorer patch_scorer_v2.pkl

Usage :
    python scripts/test_inference.py --image path/to/map.png [--n 20] [--mpp 0.5]
    python scripts/test_inference.py --image data/rg2/dataset/train/pos/event_0_ctrl_0_pos_000.png

Sorties :
    - Tableau texte : px | py | score | qualité
    - Image annotée : *_scored.png avec cercles colorés transparents
        Vert   (score ≥ 0.65) : excellent emplacement
        Orange (0.45 ≤ score < 0.65) : moyen
        Rouge  (score < 0.45) : mauvais

Le script ajoute toujours un candidat au centre de l'image (attendu : score élevé
si l'image fournie est un patch positif issu du dataset d'entraînement).
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Ajout du répertoire src/ au path pour l'import du scorer
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from services.learning.ocad_patch_scorer import OcadPatchScorer  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Couleurs des cercles (RGBA avec transparence)
# ---------------------------------------------------------------------------
def _score_to_color(score: float | None) -> tuple[int, int, int, int]:
    """Retourne (R, G, B, A) selon le score."""
    if score is None:
        return (128, 128, 128, 140)   # gris — hors carte
    if score >= 0.65:
        return (30, 200, 60, 180)     # vert  — excellent
    if score >= 0.45:
        return (255, 165, 0, 180)     # orange — moyen
    return (220, 40, 40, 180)         # rouge  — mauvais


def _draw_circle_alpha(
    base: Image.Image,
    cx: int,
    cy: int,
    radius: int,
    fill_rgba: tuple,
    outline_rgba: tuple,
    outline_width: int = 2,
) -> Image.Image:
    """Dessine un cercle plein semi-transparent sur base (RGB)."""
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=fill_rgba,
        outline=outline_rgba,
        width=outline_width,
    )
    result = Image.alpha_composite(base.convert("RGBA"), overlay)
    return result.convert("RGB")


def _draw_label(
    img: Image.Image,
    cx: int,
    cy: int,
    text: str,
    color: tuple,
) -> Image.Image:
    """Ajoute un label texte au-dessus du cercle."""
    draw = ImageDraw.Draw(img)
    # Texte avec ombre pour lisibilité
    draw.text((cx + 1, cy - 20 + 1), text, fill=(0, 0, 0), anchor="mm")
    draw.text((cx, cy - 20), text, fill=color[:3], anchor="mm")
    return img


def annotate_image(
    map_img: Image.Image,
    results: list[dict],
    output_path: Path,
    radius: int = 18,
) -> None:
    """
    Sauvegarde une image annotée avec cercles colorés semi-transparents.

    Args:
        map_img: Image carte originale.
        results: Liste [{px, py, score}].
        output_path: Chemin de sortie.
        radius: Rayon des cercles en pixels.
    """
    annotated = map_img.copy()

    for r in results:
        px, py = int(r["px"]), int(r["py"])
        score = r.get("score")
        fill = _score_to_color(score)
        outline = (fill[0], fill[1], fill[2], 255)

        annotated = _draw_circle_alpha(annotated, px, py, radius, fill, outline)

        label = f"{score:.2f}" if score is not None else "N/A"
        _draw_label(annotated, px, py, label, fill)

    annotated.save(output_path)
    log.info("Image annotée sauvegardée : %s", output_path)


def print_table(results: list[dict]) -> None:
    """Affiche un tableau texte des résultats."""
    print()
    print(f"{'#':>3}  {'px':>5}  {'py':>5}  {'score':>6}  {'qualité'}")
    print("-" * 38)
    sorted_results = sorted(results, key=lambda r: r.get("score") or 0, reverse=True)
    for i, r in enumerate(sorted_results):
        score = r.get("score")
        score_str = f"{score:.4f}" if score is not None else "  N/A"
        if score is None:
            qual = "hors carte"
        elif score >= 0.65:
            qual = "EXCELLENT"
        elif score >= 0.45:
            qual = "moyen"
        else:
            qual = "mauvais"
        print(f"{i+1:>3}  {r['px']:>5}  {r['py']:>5}  {score_str}  {qual}")

    valid = [r for r in results if r.get("score") is not None]
    if valid:
        scores = [r["score"] for r in valid]
        print("-" * 38)
        print(f"     Candidats scorés : {len(valid)}/{len(results)}")
        print(f"     Score moyen      : {np.mean(scores):.4f}")
        print(f"     Score max        : {np.max(scores):.4f}")
        print(f"     Score min        : {np.min(scores):.4f}")

    print()
    top3 = sorted_results[:3]
    print("Top-3 meilleurs emplacements :")
    for i, r in enumerate(top3):
        score = r.get("score")
        score_fmt = f"{score:.4f}" if score is not None else "N/A"
        print(f"  {i+1}. px={r['px']}, py={r['py']}, score={score_fmt}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test visuel du scorer OcadPatchScorer v2 sur une image de carte"
    )
    parser.add_argument(
        "--image", "-i", required=True, type=Path,
        help="Image de carte à analyser (PNG, JPG…)"
    )
    parser.add_argument(
        "--n", "-n", type=int, default=20,
        help="Nombre de points aléatoires à générer (default: 20)"
    )
    parser.add_argument(
        "--mpp", type=float, default=0.5,
        help="Mètres par pixel de la carte (default: 0.5 = échelle entraînement RG2)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Graine aléatoire pour reproductibilité (default: 42)"
    )
    parser.add_argument(
        "--radius", type=int, default=18,
        help="Rayon des cercles annotés en pixels (default: 18)"
    )
    args = parser.parse_args()

    # --- Chargement image ---
    if not args.image.exists():
        log.error("Image introuvable : %s", args.image)
        sys.exit(1)

    map_img = Image.open(args.image).convert("RGB")
    w, h = map_img.size
    log.info("Image chargée : %s (%d×%d px)", args.image.name, w, h)

    # --- Chargement scorer ---
    # base_dir = backend/ (deux niveaux au-dessus de scripts/)
    base_dir = Path(__file__).parents[1]
    scorer = OcadPatchScorer.load(base_dir=base_dir)
    if scorer is None:
        log.error(
            "Modèle patch_scorer_v2.pkl introuvable dans %s/data/models/",
            base_dir
        )
        log.error("Lancez d'abord : python scripts/train_control_scorer.py --phase xgboost")
        sys.exit(1)

    # --- Génération des candidats ---
    random.seed(args.seed)
    candidates = []

    # Point central (toujours inclus — attendu score élevé sur patch positif)
    candidates.append({"px": w // 2, "py": h // 2, "label": "centre"})

    # Points aléatoires
    for _ in range(args.n - 1):
        candidates.append({
            "px": random.randint(0, w - 1),
            "py": random.randint(0, h - 1),
        })

    log.info("Scoring de %d candidats (mpp=%.3f m/px)…", len(candidates), args.mpp)

    # --- Inférence ---
    results = scorer.score_map_image(map_img, candidates, mpp=args.mpp)

    # --- Affichage ---
    print_table(results)

    # --- Annotation visuelle ---
    output_path = args.image.parent / (args.image.stem + "_scored.png")
    annotate_image(map_img, results, output_path, radius=args.radius)
    print(f"Image annotée : {output_path}")


if __name__ == "__main__":
    main()
