#!/usr/bin/env python3
"""
visualize_leg.py — Validation visuelle du moteur de choix d'itinéraire (A* Tobler).

Génère une carte PNG montrant :
  - Fond hillshade (ombrage relief calculé via numpy)
  - Overlay végétation vert semi-transparent (si --veg fourni)
  - Ligne directe start→end en rouge pointillé
  - Chemin optimal A* Tobler en bleu continu
  - Marqueurs Départ (vert) et Arrivée (rouge)
  - Métriques console : temps, distance, dénivelé positif

Usage :
    python scripts/visualize_leg.py \\
        --elev data/mnt_lidar.tif \\
        --veg  data/veg_factor.tif \\
        --start 452100 6901500 \\
        --end   453800 6902200 \\
        --out   output/leg_preview.png
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# HEADLESS — DOIT PRÉCÉDER TOUT IMPORT DE PYPLOT
# Évite les Segmentation Fault en environnement sans display (MINGW64 / CI).
# ---------------------------------------------------------------------------
import os
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (import après use())

# ---------------------------------------------------------------------------
# Imports standard
# ---------------------------------------------------------------------------
import argparse
import math
import sys
from typing import List, Optional, Tuple

import numpy as np

try:
    import rasterio
except ImportError:
    sys.exit("ERREUR : rasterio est requis.  pip install rasterio")

# ---------------------------------------------------------------------------
# Ajout de src/ au PYTHONPATH
# Le script peut être lancé depuis backend/ ou scripts/ ou en chemin absolu.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    os.path.join(_HERE, "..", "src"),   # lancé depuis scripts/
    os.path.join(_HERE, "src"),         # lancé depuis backend/
):
    _candidate = os.path.normpath(_candidate)
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

try:
    from aitraceur.navigation.terrain_3d import (
        TerrainMovementCost,
        _astar,                      # API interne — seule fonction qui retourne le chemin complet
        compute_climb_along_path,
    )
except ImportError as exc:
    sys.exit(
        f"ERREUR : impossible d'importer le moteur terrain_3d.\n"
        f"  → Lancez le script depuis backend/ ou vérifiez PYTHONPATH.\n"
        f"  Détail : {exc}"
    )


# ===========================================================================
# Chargement des rasters
# ===========================================================================

def load_raster(path: str) -> Tuple[np.ndarray, "rasterio.transform.Affine"]:
    """
    Charge la bande 1 d'un GeoTIFF en float32.

    Les valeurs nodata sont remplacées par 0 pour éviter les NaN dans les
    calculs de gradient (hillshade) et de pente (Tobler).

    Args:
        path: Chemin vers le GeoTIFF.

    Returns:
        (grid, transform) — grid (H, W) float32, transform affine rasterio.
    """
    with rasterio.open(path) as src:
        grid: np.ndarray = src.read(1).astype(np.float32)
        nodata = src.nodata
        transform = src.transform
    if nodata is not None:
        grid = np.where(np.isclose(grid, nodata), 0.0, grid).astype(np.float32)
    return grid, transform


# ===========================================================================
# Conversion de coordonnées
# ===========================================================================

def xy_to_rowcol(
    x: float,
    y: float,
    transform: "rasterio.transform.Affine",
    height: int,
    width: int,
) -> Tuple[int, int]:
    """
    Convertit des coordonnées projetées (x, y) en indices entiers (row, col).

    Transformation affine rasterio :
        col_f = (x - t.c) / t.a       (t.a = résolution X, positif)
        row_f = (y - t.f) / t.e       (t.e = résolution Y, négatif car Y ↓)

    Le résultat est clampé dans [0, h-1] × [0, w-1] pour éviter tout
    débordement hors grille.

    Args:
        x, y:          Coordonnées projetées (mètres).
        transform:     Transformation affine du raster source.
        height, width: Dimensions du raster pour clipping.

    Returns:
        (row, col) entiers, garantis dans les bornes du raster.
    """
    col_f = (x - transform.c) / transform.a
    row_f = (y - transform.f) / transform.e
    row = int(round(row_f))
    col = int(round(col_f))
    return (
        max(0, min(row, height - 1)),
        max(0, min(col, width  - 1)),
    )


# ===========================================================================
# Ombrage du relief (Hillshade)
# ===========================================================================

def compute_hillshade(
    elev: np.ndarray,
    cell_size: float = 1.0,
    azimuth_deg: float = 315.0,
    altitude_deg: float = 45.0,
) -> np.ndarray:
    """
    Calcule l'ombrage du relief (modèle de Lambert) depuis la grille d'altitudes.

    Args:
        elev:         Grille d'altitudes (H, W) float.
        cell_size:    Résolution spatiale en mètres.
        azimuth_deg:  Direction de la source lumineuse (315 = NW).
        altitude_deg: Angle d'élévation solaire en degrés.

    Returns:
        Grille hillshade (H, W) float32 dans [0.0, 1.0].
    """
    az  = math.radians(azimuth_deg)
    alt = math.radians(altitude_deg)

    dy, dx = np.gradient(elev, cell_size)
    slope  = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dy, dx)

    shade = (
        np.cos(alt) * np.cos(slope)
        + np.sin(alt) * np.sin(slope) * np.cos(az - aspect)
    )
    return np.clip(shade, 0.0, 1.0).astype(np.float32)


# ===========================================================================
# Pathfinding A* — récupération du chemin complet
# ===========================================================================

def find_optimal_path(
    start_rc: Tuple[int, int],
    end_rc: Tuple[int, int],
    terrain_model: TerrainMovementCost,
) -> Tuple[float, float, float, List[Tuple[int, int]]]:
    """
    Lance A* et reconstruit le chemin cellule par cellule.

    Args:
        start_rc:       (row, col) cellule de départ.
        end_rc:         (row, col) cellule d'arrivée.
        terrain_model:  Modèle de coût TerrainMovementCost.

    Returns:
        (time_seconds, dist_m_2d, climb_m, path)
        Retourne (inf, 0, 0, []) si aucun chemin n'existe.
    """
    time_s, path = _astar(start_rc, end_rc, terrain_model)

    if not path or not math.isfinite(time_s):
        return math.inf, 0.0, 0.0, []

    cell = terrain_model.cell_size
    dist_m = 0.0
    for i in range(1, len(path)):
        r1, c1 = path[i - 1]
        r2, c2 = path[i]
        dist_m += cell * (1.4142 if (r1 != r2 and c1 != c2) else 1.0)

    climb_m = compute_climb_along_path(path, terrain_model.elevation_grid)
    return time_s, dist_m, climb_m, path


# ===========================================================================
# Fenêtre de visualisation
# ===========================================================================

def crop_window(
    start_r: int,
    start_c: int,
    end_r:   int,
    end_c:   int,
    height:  int,
    width:   int,
    padding_factor: float = 0.30,
    min_padding:    int   = 40,
) -> Tuple[int, int, int, int]:
    """
    Calcule la fenêtre d'affichage (r0, r1, c0, c1) centrée sur la jambe.

    Args:
        start_r/c, end_r/c: Coordonnées pixel des extrémités.
        height, width:      Dimensions du raster source.
        padding_factor:     Marge = factor × max(span_r, span_c).
        min_padding:        Marge minimale en cellules.

    Returns:
        (r0, r1, c0, c1) indices valides pour un slicing numpy.
    """
    span = max(abs(end_r - start_r), abs(end_c - start_c), 1)
    pad  = max(min_padding, int(padding_factor * span))

    r0 = max(0,      min(start_r, end_r) - pad)
    r1 = min(height, max(start_r, end_r) + pad)
    c0 = max(0,      min(start_c, end_c) - pad)
    c1 = min(width,  max(start_c, end_c) + pad)
    return r0, r1, c0, c1


# ===========================================================================
# Rendu matplotlib — fonction principale de tracé
# ===========================================================================

def render_path(
    path: List[Tuple[int, int]],
    elev_grid: np.ndarray,
    veg_grid: Optional[np.ndarray],
    transform: "rasterio.transform.Affine",
    start_rc: Tuple[int, int],
    end_rc: Tuple[int, int],
    time_s: float,
    dist_m: float,
    climb_m: float,
    out_path: str,
) -> None:
    """
    Génère et sauvegarde la carte PNG de validation du chemin A*.

    Couches superposées (de bas en haut) :
      1. Hillshade — fond en niveaux de gris.
      2. Overlay végétation — vert semi-transparent (zones veg_factor < 0.99).
      3. Ligne directe — rouge pointillée.
      4. Chemin A* — bleu continu, épaisseur 2.5.
      5. Marqueurs Départ (vert) / Arrivée (rouge) avec étiquettes.

    La figure est impérativement fermée après sauvegarde (plt.close('all'))
    pour libérer toute la mémoire matplotlib — critique en mode subprocess répété.

    Args:
        path:       Chemin A* comme liste de (row, col).
        elev_grid:  Grille d'altitudes complète (H, W) float32.
        veg_grid:   Grille de végétation (H, W) float32, ou None.
        transform:  Transformation affine rasterio du raster élévation.
        start_rc:   (row, col) cellule de départ.
        end_rc:     (row, col) cellule d'arrivée.
        time_s:     Temps de parcours en secondes.
        dist_m:     Distance A* en mètres.
        climb_m:    Dénivelé positif en mètres.
        out_path:   Chemin de sortie du PNG.

    Raises:
        RuntimeError: Si le rendu matplotlib échoue (propagé depuis main).
    """
    h, w = elev_grid.shape
    start_r, start_c = start_rc
    end_r,   end_c   = end_rc

    r0, r1, c0, c1 = crop_window(start_r, start_c, end_r, end_c, h, w)

    cell_size = abs(float(transform.a))
    elev_crop = elev_grid[r0:r1, c0:c1]
    hillshade  = compute_hillshade(elev_crop, cell_size=cell_size)

    fig, ax = plt.subplots(figsize=(12, 10), dpi=150)
    try:
        ax.imshow(
            hillshade, cmap="gray", vmin=0.0, vmax=1.0,
            origin="upper", interpolation="bilinear",
        )

        # Overlay végétation (vert semi-transparent)
        if veg_grid is not None:
            veg_crop = veg_grid[r0:r1, c0:c1]
            mask = veg_crop < 0.99

            rgba = np.zeros((*veg_crop.shape, 4), dtype=np.float32)
            rgba[mask, 0] = 0.08
            rgba[mask, 1] = 0.60
            rgba[mask, 2] = 0.08
            rgba[mask, 3] = np.clip(0.25 + 0.65 * (1.0 - veg_crop[mask]), 0.1, 0.75)
            ax.imshow(rgba, origin="upper", interpolation="nearest")

        # Chemin A* (bleu continu)
        if path:
            path_cols = [c - c0 for _, c in path]
            path_rows = [r - r0 for r, _ in path]
            ax.plot(
                path_cols, path_rows,
                color="#1565C0", linewidth=2.5,
                solid_capstyle="round", solid_joinstyle="round",
                label=f"Chemin A* ({len(path)} cellules)",
                zorder=4,
            )

        # Ligne directe (rouge pointillée)
        ax.plot(
            [start_c - c0, end_c - c0],
            [start_r - r0, end_r - r0],
            color="#C62828", linestyle="--", linewidth=1.5,
            label="Ligne directe",
            zorder=3,
        )

        # Marqueurs Départ / Arrivée
        _MK = dict(markersize=13, markeredgecolor="white", markeredgewidth=2, zorder=5)
        ax.plot(start_c - c0, start_r - r0, "o", color="#2E7D32", **_MK, label="Départ")
        ax.plot(end_c   - c0, end_r   - r0, "o", color="#C62828", **_MK, label="Arrivée")

        _LB = dict(ha="center", va="center", fontsize=9, fontweight="bold",
                   color="white", zorder=6)
        ax.annotate("D", (start_c - c0, start_r - r0), **_LB)
        ax.annotate("A", (end_c   - c0, end_r   - r0), **_LB)

        # Titre avec métriques
        minutes = int(time_s // 60)
        seconds = int(time_s % 60)
        km_eff  = dist_m / 1000.0 + climb_m / 100.0
        ax.set_title(
            f"Chemin optimal A* (Tobler)   —   "
            f"Temps : {minutes:02d}:{seconds:02d}   |   "
            f"Distance : {dist_m:.0f} m   |   "
            f"Dénivelé+ : {climb_m:.1f} m   |   "
            f"km-effort : {km_eff:.2f}",
            fontsize=12, pad=14,
        )

        ax.legend(loc="lower right", fontsize=9, framealpha=0.88)
        ax.set_xlabel("Colonne (pixels)", fontsize=9)
        ax.set_ylabel("Ligne (pixels)",   fontsize=9)

        sm = plt.cm.ScalarMappable(cmap="gray", norm=plt.Normalize(vmin=0, vmax=1))
        sm.set_array([])
        fig.colorbar(sm, ax=ax, fraction=0.025, pad=0.02, label="Hillshade")

        # Sauvegarde
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        plt.tight_layout()
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"\n[OK] Carte sauvegardée → {out_path}")

    finally:
        # Libère TOUTE la mémoire matplotlib — critique pour appels répétés en subprocess
        plt.close("all")


# ===========================================================================
# Interface en ligne de commande
# ===========================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="visualize_leg.py",
        description="Validation visuelle du chemin optimal A* (Tobler) sur MNT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--elev", required=True, metavar="GeoTIFF",
        help="MNT GeoTIFF (altitudes en mètres).",
    )
    p.add_argument(
        "--veg", default=None, metavar="GeoTIFF",
        help="Végétation GeoTIFF (facteur vitesse [0–1]). Optionnel.",
    )
    p.add_argument(
        "--start", required=True, nargs=2, type=float, metavar=("X", "Y"),
        help="Coordonnées du départ en mètres projetés (ex : 452100 6901500).",
    )
    p.add_argument(
        "--end", required=True, nargs=2, type=float, metavar=("X", "Y"),
        help="Coordonnées de l'arrivée en mètres projetés.",
    )
    p.add_argument(
        "--out", default="leg_preview.png", metavar="PNG",
        help="Chemin du fichier PNG de sortie (défaut : leg_preview.png).",
    )
    p.add_argument(
        "--speed", default=6.0, type=float, metavar="KMH",
        help="Vitesse de base en km/h (défaut : 6.0).",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    # ------------------------------------------------------------------
    # 1. Chargement des rasters
    # ------------------------------------------------------------------
    print(f"\n[1/4] Chargement MNT          : {args.elev}")
    elev_grid, transform = load_raster(args.elev)
    h, w = elev_grid.shape
    cell_size = abs(float(transform.a))
    print(f"      Dimensions : {w} × {h} px   résolution : {cell_size:.1f} m/px")
    print(f"      Altitude min/max : {elev_grid.min():.1f} / {elev_grid.max():.1f} m")

    veg_grid: Optional[np.ndarray] = None
    if args.veg:
        print(f"[1/4] Chargement végétation   : {args.veg}")
        veg_raw, _ = load_raster(args.veg)
        if veg_raw.shape == elev_grid.shape:
            veg_grid = np.clip(veg_raw, 0.0, 1.0)
            open_pct = float(np.mean(veg_grid >= 0.99)) * 100
            print(f"      Terrain ouvert : {open_pct:.1f}%")
        else:
            print(
                f"      AVERTISSEMENT : dimensions veg {veg_raw.shape} ≠ elev {elev_grid.shape}."
                f" Overlay végétation désactivé."
            )

    # ------------------------------------------------------------------
    # 2. Modèle de coût TerrainMovementCost
    # ------------------------------------------------------------------
    print(f"\n[2/4] Modèle Tobler           : vitesse base {args.speed:.1f} km/h")
    veg_for_model = veg_grid if veg_grid is not None else np.ones_like(elev_grid)
    terrain_model = TerrainMovementCost(
        elev_grid, veg_for_model,
        cell_size=cell_size,
        base_speed_kmh=args.speed,
    )

    # ------------------------------------------------------------------
    # 3. Conversion coordonnées → cellules + pathfinding A*
    # ------------------------------------------------------------------
    sx, sy = args.start
    ex, ey = args.end
    start_rc = xy_to_rowcol(sx, sy, transform, h, w)
    end_rc   = xy_to_rowcol(ex, ey, transform, h, w)

    print(f"\n[3/4] Départ  ({sx:.1f}, {sy:.1f})  →  cellule {start_rc}")
    print(f"      Arrivée ({ex:.1f}, {ey:.1f})  →  cellule {end_rc}")
    print("      Calcul A* en cours...")

    time_s, dist_m, climb_m, path = find_optimal_path(start_rc, end_rc, terrain_model)

    if not path:
        sys.exit(
            "\nERREUR : aucun chemin trouvé.\n"
            "  → Vérifiez que les coordonnées sont dans l'emprise du raster\n"
            "    et que les cellules départ/arrivée sont accessibles."
        )

    # ------------------------------------------------------------------
    # Métriques console
    # ------------------------------------------------------------------
    minutes   = int(time_s // 60)
    seconds   = int(time_s % 60)
    direct_m  = math.hypot(ex - sx, ey - sy)
    detour_pct = (dist_m / direct_m - 1.0) * 100.0 if direct_m > 0 else 0.0
    km_eff    = dist_m / 1000.0 + climb_m / 100.0

    print()
    print("┌─────────────────────────────────────┐")
    print(f"│  Temps           : {minutes:02d}:{seconds:02d}  ({time_s:.0f} s)   │")
    print(f"│  Distance A*     : {dist_m:>8.0f} m              │")
    print(f"│  Ligne directe   : {direct_m:>8.0f} m              │")
    print(f"│  Détour          : {detour_pct:>+7.1f} %              │")
    print(f"│  Dénivelé+       : {climb_m:>8.1f} m              │")
    print(f"│  km-effort IOF   : {km_eff:>8.3f} km             │")
    print(f"│  Cellules chemin : {len(path):>8d}               │")
    print("└─────────────────────────────────────┘")

    # ------------------------------------------------------------------
    # 4. Rendu PNG — encapsulé dans try/except pour crash-proof
    # ------------------------------------------------------------------
    print(f"\n[4/4] Rendu PNG               : {args.out}")
    try:
        render_path(
            path=path,
            elev_grid=elev_grid,
            veg_grid=veg_grid,
            transform=transform,
            start_rc=start_rc,
            end_rc=end_rc,
            time_s=time_s,
            dist_m=dist_m,
            climb_m=climb_m,
            out_path=args.out,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERREUR] Rendu matplotlib échoué : {exc}", file=sys.stderr)
        plt.close("all")
        sys.exit(1)


if __name__ == "__main__":
    main()
