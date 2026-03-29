"""
extract_vikazimut_patches.py — Extrait des patches d'entraînement XGBoost depuis le
dataset Vikazimut (parcours français, cartes JPG géoréférencées).

Entrées :
  vikazimut/index.json       — index produit par index_vikazimut.py
  vikazimut/maps/N.jpg       — cartes JPG

Sorties :
  vikazimut/patches/train/pos/   — patches positifs (postes réels)
  vikazimut/patches/train/neg/   — patches négatifs (positions aléatoires)
  vikazimut/patches/metadata.csv — compatible train_control_scorer.py

Usage :
  cd backend
  python scripts/extract_vikazimut_patches.py
  python scripts/extract_vikazimut_patches.py --normalize      # normalisation OCAD→MapAnt
  python scripts/extract_vikazimut_patches.py --resume         # reprend depuis dernier run
  python scripts/extract_vikazimut_patches.py --limit 50       # test sur 50 parcours

Réentraînement XGBoost avec les nouvelles données :
  python scripts/train_control_scorer.py --dataset-dir ../vikazimut/patches
  # ou merger avec RG2 (voir README inline ci-dessous)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ─── Chemins par défaut ──────────────────────────────────────────────────────

BACKEND_DIR = Path(__file__).parent.parent
VIKAZIMUT_DIR = BACKEND_DIR.parent / "vikazimut"
INDEX_PATH = VIKAZIMUT_DIR / "index.json"


# ─── Constantes (alignées sur DatasetGenerator dans scrape_rg2.py) ───────────

FOV_METERS: float = 128.0    # côté réel couvert par chaque patch (mètres)
PATCH_PX: int = 256          # dimensions de sortie (pixels)
NEG_MIN_M: float = 60.0      # distance min d'un vrai poste pour les négatifs
NEG_RATIO: int = 2           # négatifs par positif
MIN_VALID_PX: int = 32       # taille de crop minimale avant resize

# Seuils couleur pour le filtre négatifs (identiques à DatasetGenerator)
WATER_B_MIN: int = 150
MARGIN_BRIGHT: int = 248
BORDER_DARK: int = 25


# ─── Géométrie ────────────────────────────────────────────────────────────────

def compute_mpp(bounds: dict, img_width: int, img_height: int) -> float:
    """Calcule la résolution en mètres/pixel depuis la LatLonBox KML."""
    lat_c = (bounds["north"] + bounds["south"]) / 2.0
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_c))
    width_m = (bounds["east"] - bounds["west"]) * m_per_deg_lon
    height_m = (bounds["north"] - bounds["south"]) * m_per_deg_lat
    if img_width <= 0 or img_height <= 0 or width_m <= 0 or height_m <= 0:
        raise ValueError(f"Dimensions invalides: img={img_width}×{img_height}, "
                         f"bbox={width_m:.1f}×{height_m:.1f}m")
    return ((width_m / img_width) + (height_m / img_height)) / 2.0


def wgs84_to_pixel(
    lat: float, lng: float,
    bounds: dict,
    img_width: int, img_height: int,
) -> tuple[float, float]:
    """
    Convertit WGS84 → coordonnées pixel, en tenant compte de la rotation KML.

    La LatLonBox KML définit un rectangle tourné (rotation en degrés CCW depuis
    le nord). La formule centre-relative avec matrice de rotation garantit que
    même pour des rotations de ~20° (observées dans le dataset), le patch est
    bien centré sur le bon feature terrain.
    """
    west, east = bounds["west"], bounds["east"]
    south, north = bounds["south"], bounds["north"]
    theta = math.radians(bounds.get("rotation") or 0.0)

    lat_c = (north + south) / 2.0
    lng_c = (east + west) / 2.0
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_c))
    width_m = (east - west) * m_per_deg_lon
    height_m = (north - south) * m_per_deg_lat

    # Delta depuis le centre (mètres)
    dx = (lng - lng_c) * m_per_deg_lon   # mètres vers l'est
    dy = (lat - lat_c) * m_per_deg_lat   # mètres vers le nord

    # Rotation : aligner avec les axes image (x=droite=est, y=bas=sud)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    dx_r =  dx * cos_t + dy * sin_t
    dy_r = -dx * sin_t + dy * cos_t

    px = (0.5 + dx_r / width_m) * img_width
    py = (0.5 - dy_r / height_m) * img_height
    return px, py


def pixel_to_wgs84(
    px: float, py: float,
    bounds: dict,
    img_width: int, img_height: int,
) -> tuple[float, float]:
    """Inverse de wgs84_to_pixel — utilisé pour les coordonnées des négatifs."""
    west, east = bounds["west"], bounds["east"]
    south, north = bounds["south"], bounds["north"]
    theta = math.radians(bounds.get("rotation") or 0.0)

    lat_c = (north + south) / 2.0
    lng_c = (east + west) / 2.0
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_c))
    width_m = (east - west) * m_per_deg_lon
    height_m = (north - south) * m_per_deg_lat

    # Pixel → delta centre (frame rotaté)
    dx_r = (px / img_width - 0.5) * width_m
    dy_r = (0.5 - py / img_height) * height_m

    # Dérotation
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    dx = dx_r * cos_t - dy_r * sin_t
    dy = dx_r * sin_t + dy_r * cos_t

    lat = lat_c + dy / m_per_deg_lat
    lng = lng_c + dx / m_per_deg_lon
    return lat, lng


# ─── Extraction de patches ────────────────────────────────────────────────────

def crop_patch(
    img: "Image.Image", px: float, py: float, half_px: int,
) -> Optional["Image.Image"]:
    """
    Crop ±half_px autour de (px, py), resize à PATCH_PX×PATCH_PX.
    Retourne None si >25% du crop dépasse les bords.
    Identique à DatasetGenerator._crop_fixed_fov.
    """
    x0, y0 = int(px) - half_px, int(py) - half_px
    x1, y1 = int(px) + half_px, int(py) + half_px

    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(img.width, x1), min(img.height, y1)
    full_area = (x1 - x0) * (y1 - y0)
    clip_area = max(0, cx1 - cx0) * max(0, cy1 - cy0)
    if full_area <= 0 or clip_area < full_area * 0.75:
        return None

    crop = img.crop((cx0, cy0, cx1, cy1))
    if crop.width < MIN_VALID_PX or crop.height < MIN_VALID_PX:
        return None
    return crop.resize((PATCH_PX, PATCH_PX), Image.LANCZOS)


def is_valid_negative(img: "Image.Image", px: float, py: float) -> bool:
    """
    Filtre couleur pour les négatifs.
    Rejette : marges blanches, bords noirs, eau (bleu dominant), zones OOB (vert olive).
    Identique à DatasetGenerator._is_valid_negative.
    """
    xi, yi = int(px), int(py)
    if not (0 <= xi < img.width and 0 <= yi < img.height):
        return False
    r, g, b = img.getpixel((xi, yi))[:3]
    if r >= MARGIN_BRIGHT and g >= MARGIN_BRIGHT and b >= MARGIN_BRIGHT:
        return False
    if r <= BORDER_DARK and g <= BORDER_DARK and b <= BORDER_DARK:
        return False
    if b >= WATER_B_MIN and b > r * 1.5 and b > g * 1.2:
        return False
    if g > r and g > b and 80 <= g <= 160 and r < 130 and b < 100:
        return False
    return True


def generate_negatives(
    img: "Image.Image",
    controls_px: list[tuple[float, float]],
    target: int,
    mpp: float,
    crop_half_px: int,
    rng: random.Random,
    max_attempts: int = 100,
) -> list[tuple["Image.Image", float, float]]:
    """Génère des patches négatifs en espace pixel. Identique à _generate_negatives."""
    neg_min_px = NEG_MIN_M / max(mpp, 1e-9)
    margin = crop_half_px + 4
    results: list[tuple["Image.Image", float, float]] = []
    attempts = 0

    while len(results) < target and attempts < target * max_attempts:
        attempts += 1
        px = rng.uniform(margin, img.width - margin)
        py = rng.uniform(margin, img.height - margin)

        if any(math.hypot(px - cx, py - cy) < neg_min_px for cx, cy in controls_px):
            continue
        if not is_valid_negative(img, px, py):
            continue
        patch = crop_patch(img, px, py, crop_half_px)
        if patch is not None:
            results.append((patch, px, py))

    return results


def maybe_normalize(patch: "Image.Image") -> "Image.Image":
    """Normalise les couleurs OCAD→MapAnt via match_histograms (optionnel)."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(BACKEND_DIR / "src"))
        from services.learning.style_normalizer import normalize_ocad_to_mapant
        return normalize_ocad_to_mapant(patch)
    except Exception:
        return patch


# ─── Discipline → course_type ─────────────────────────────────────────────────

def discipline_to_course_type(discipline: str) -> str:
    """
    Mappe la discipline Vikazimut vers le course_type RG2.
    "urbano" → "sprint" (poids 2.0× dans train_control_scorer.py)
    """
    d = (discipline or "").lower()
    if d == "urbano":
        return "sprint"
    if d == "foresto":
        return "forest"
    return "unknown"


# ─── Stats ────────────────────────────────────────────────────────────────────

@dataclass
class ExtractionStats:
    total: int = 0
    processed: int = 0
    skipped_no_bounds: int = 0
    skipped_no_map: int = 0
    skipped_small_mpp: int = 0
    skipped_parse_error: int = 0
    positives: int = 0
    negatives: int = 0
    neg_shortfall: int = 0
    normalized: int = 0
    by_discipline: dict = field(default_factory=dict)


# ─── Pipeline par parcours ────────────────────────────────────────────────────

def process_course(
    entry: dict,
    patches_dir: Path,
    pos_dir: Path,
    neg_dir: Path,
    normalize: bool,
    rng: random.Random,
) -> list[dict]:
    """
    Pipeline complet pour un parcours :
    1. Ouvre la carte JPG
    2. Calcule mpp + crop_half_px
    3. Extrait un patch pour chaque poste "Control"
    4. Génère NEG_RATIO négatifs par poste
    5. Retourne les lignes CSV (liste vide si échec)
    """
    bounds = entry.get("bounds")
    map_path = entry.get("map_jpg")
    controls = entry.get("controls") or []
    course_id = entry["id"]
    discipline = entry.get("discipline", "")
    course_type = discipline_to_course_type(discipline)
    n_all = entry.get("n_controls", 0)

    if not bounds:
        return []
    if not map_path or not Path(map_path).exists():
        return []

    try:
        img = Image.open(map_path).convert("RGB")
    except Exception:
        return []

    try:
        mpp = compute_mpp(bounds, img.width, img.height)
    except ValueError:
        return []

    crop_half_px = max(MIN_VALID_PX, int((FOV_METERS / 2.0) / mpp))
    if crop_half_px < MIN_VALID_PX:
        return []

    rows: list[dict] = []
    controls_px: list[tuple[float, float]] = []

    # ── Positifs (postes réels, type "Control") ────────────────────────────
    ctrl_idx = 0
    for c in controls:
        if c.get("type") != "Control":
            continue
        lat, lng = c["lat"], c["lng"]

        try:
            px, py = wgs84_to_pixel(lat, lng, bounds, img.width, img.height)
        except Exception:
            continue

        patch = crop_patch(img, px, py, crop_half_px)
        if patch is None:
            continue

        if normalize:
            patch = maybe_normalize(patch)

        fname = f"{course_id}_{ctrl_idx}.png"
        patch.save(pos_dir / fname, format="PNG")

        rows.append({
            "img_path": f"train/pos/{fname}",
            "label": 1,
            "fov_m": FOV_METERS,
            "mpp": round(mpp, 4),
            "course_type": course_type,
            "n_controls": n_all,
            "course_id": course_id,
            "discipline": discipline,
            "source": "vikazimut",
            "control_index": ctrl_idx,
            "lat": round(lat, 7),
            "lon": round(lng, 7),
        })
        controls_px.append((px, py))
        ctrl_idx += 1

    if not controls_px:
        return []

    # ── Négatifs ───────────────────────────────────────────────────────────
    target_neg = len(controls_px) * NEG_RATIO
    neg_patches = generate_negatives(img, controls_px, target_neg, mpp, crop_half_px, rng)

    for j, (neg_patch, npx, npy) in enumerate(neg_patches):
        if normalize:
            neg_patch = maybe_normalize(neg_patch)

        fname = f"{course_id}_neg{j}.png"
        neg_patch.save(neg_dir / fname, format="PNG")

        try:
            n_lat, n_lng = pixel_to_wgs84(npx, npy, bounds, img.width, img.height)
        except Exception:
            n_lat, n_lng = 0.0, 0.0

        rows.append({
            "img_path": f"train/neg/{fname}",
            "label": 0,
            "fov_m": FOV_METERS,
            "mpp": round(mpp, 4),
            "course_type": course_type,
            "n_controls": n_all,
            "course_id": course_id,
            "discipline": discipline,
            "source": "vikazimut",
            "control_index": -1,
            "lat": round(n_lat, 7),
            "lon": round(n_lng, 7),
        })

    return rows


# ─── Main ─────────────────────────────────────────────────────────────────────

FIELDNAMES = [
    "img_path", "label", "fov_m", "mpp", "course_type",
    "n_controls", "course_id", "discipline", "source",
    "control_index", "lat", "lon",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrait des patches d'entraînement Vikazimut")
    parser.add_argument("--index", default=str(INDEX_PATH),
                        help="Chemin vers vikazimut/index.json")
    parser.add_argument("--out-dir", default=str(VIKAZIMUT_DIR / "patches"),
                        help="Répertoire de sortie des patches")
    parser.add_argument("--normalize", action="store_true",
                        help="Normalise les couleurs OCAD→MapAnt (plus lent, ~+25 min)")
    parser.add_argument("--resume", action="store_true",
                        help="Ignore les parcours déjà traités (teste l'existence du 1er patch)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Graine aléatoire globale (défaut: 42)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Nombre max de parcours à traiter (0=tous, pour debug)")
    parser.add_argument("--neg-ratio", type=int, default=NEG_RATIO,
                        help=f"Négatifs par positif (défaut: {NEG_RATIO})")
    args = parser.parse_args()

    if not PIL_AVAILABLE:
        print("[ERREUR] Pillow requis : pip install pillow", file=sys.stderr)
        sys.exit(1)

    index_path = Path(args.index)
    if not index_path.exists():
        print(f"[ERREUR] index.json introuvable : {index_path}", file=sys.stderr)
        sys.exit(1)

    patches_dir = Path(args.out_dir)
    pos_dir = patches_dir / "train" / "pos"
    neg_dir = patches_dir / "train" / "neg"
    pos_dir.mkdir(parents=True, exist_ok=True)
    neg_dir.mkdir(parents=True, exist_ok=True)

    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    foot_o = [e for e in index if e.get("is_foot_o")]
    total = len(foot_o)
    if args.limit > 0:
        foot_o = foot_o[:args.limit]
    print(f"Extraction depuis {len(foot_o)}/{total} parcours foot-O…")
    if args.normalize:
        print("  Normalisation OCAD→MapAnt activée (plus lent)")

    meta_path = patches_dir / "metadata.csv"
    meta_exists = meta_path.exists() and args.resume

    stats = ExtractionStats(total=len(foot_o))
    global_rng = random.Random(args.seed)

    with open(meta_path, "a" if args.resume else "w", newline="", encoding="utf-8") as meta_f:
        writer = csv.DictWriter(meta_f, fieldnames=FIELDNAMES)
        if not meta_exists:
            writer.writeheader()

        for i, entry in enumerate(foot_o, 1):
            if i % 200 == 0 or i == len(foot_o):
                print(f"  {i}/{len(foot_o)}  pos={stats.positives}  neg={stats.negatives}",
                      flush=True)

            course_id = entry["id"]
            discipline = entry.get("discipline", "")

            # --resume : saute si le 1er patch existe déjà
            if args.resume and (pos_dir / f"{course_id}_0.png").exists():
                continue

            # Comptes pour les stats de skip
            if not entry.get("bounds"):
                stats.skipped_no_bounds += 1
                continue
            map_path = entry.get("map_jpg")
            if not map_path or not Path(map_path).exists():
                stats.skipped_no_map += 1
                continue

            # RNG reproductible par parcours
            course_rng = random.Random(args.seed ^ (course_id * 2654435761 & 0xFFFFFFFF))

            rows = process_course(
                entry, patches_dir, pos_dir, neg_dir,
                normalize=args.normalize,
                rng=course_rng,
            )

            if not rows:
                stats.skipped_parse_error += 1
                continue

            pos_rows = [r for r in rows if r["label"] == 1]
            neg_rows = [r for r in rows if r["label"] == 0]
            expected_neg = len(pos_rows) * args.neg_ratio
            if len(neg_rows) < expected_neg:
                stats.neg_shortfall += expected_neg - len(neg_rows)

            for row in rows:
                writer.writerow(row)

            stats.positives += len(pos_rows)
            stats.negatives += len(neg_rows)
            stats.processed += 1
            stats.by_discipline[discipline] = stats.by_discipline.get(discipline, 0) + 1

    # ── Résumé ────────────────────────────────────────────────────────────
    print("\n-- Résumé ------------------------------------------")
    print(f"  Parcours traités      : {stats.processed}/{stats.total}")
    print(f"  Patches positifs      : {stats.positives}")
    print(f"  Patches négatifs      : {stats.negatives}")
    print(f"  Total patches         : {stats.positives + stats.negatives}")
    if stats.neg_shortfall:
        print(f"  Manque négatifs       : {stats.neg_shortfall} (cartes trop vides/petites)")
    if stats.skipped_no_bounds:
        print(f"  Skipped sans bounds   : {stats.skipped_no_bounds}")
    if stats.skipped_no_map:
        print(f"  Skipped sans carte    : {stats.skipped_no_map}")
    if stats.skipped_parse_error:
        print(f"  Skipped erreurs       : {stats.skipped_parse_error}")
    print(f"  Disciplines : {dict(sorted(stats.by_discipline.items(), key=lambda x: -x[1]))}")
    print(f"\n  metadata.csv : {meta_path}")
    print(f"  Patches dir  : {patches_dir}")

    print("\n-- Réentraînement XGBoost --------------------------")
    print("  Vikazimut seul :")
    print(f"    python scripts/train_control_scorer.py --dataset-dir ../vikazimut/patches")
    print("  Merger avec RG2 (recommandé) :")
    print("    Concaténer les deux metadata.csv avec chemins absolus,")
    print("    puis pointer --dataset-dir sur le répertoire racine fusionné.")


if __name__ == "__main__":
    main()
