"""
scripts/run_visual_tests.py — Banc d'essai automatisé du moteur de pathfinding 3D.

Génère 3 terrains synthétiques (GeoTIFFs 200×200 px, résolution 3 m) représentant
des problèmes classiques de Course d'Orientation, puis appelle visualize_leg.py
pour produire 3 images PNG de validation.

Grille commune :
    transform = from_origin(west=0, north=600, xsize=3, ysize=3)
    → 200×200 px = 600×600 m en coordonnées géographiques
    → x ∈ [0, 600 m]  (col = x / 3)
    → y ∈ [0, 600 m]  (row = (600 - y) / 3)

Scénarios :
    1. test_hill   — Colline conique : A* doit contourner par les flancs.
    2. test_green  — Mur vert   : A* doit passer par la faille dans la végétation dense.
    3. test_ravine — Ravin      : A* doit détourner par le gué progressif à gauche.

Usage :
    python scripts/run_visual_tests.py
    python scripts/run_visual_tests.py --output-dir tests/output
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import rasterio
    from rasterio.transform import from_origin
except ImportError:
    sys.exit("ERREUR : rasterio est requis.  pip install rasterio")

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parent.parent
_VISUALIZE = _BACKEND / "scripts" / "visualize_leg.py"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run_visual_tests")

# ---------------------------------------------------------------------------
# Constantes communes à tous les rasters
# ---------------------------------------------------------------------------
_H = 200
_W = 200
_CELL = 3.0                                     # résolution (m/pixel)
_TRANSFORM = from_origin(west=0.0, north=600.0, xsize=_CELL, ysize=_CELL)


# ===========================================================================
# Utilitaire de sauvegarde
# ===========================================================================

def save_raster(path: Path, grid: np.ndarray) -> None:
    """
    Sauvegarde un tableau numpy (H, W) en GeoTIFF float32.

    Le fichier est toujours écrasé (mode 'w').  Le dossier parent est
    créé automatiquement si nécessaire.

    Args:
        path:  Chemin de sortie (.tif).
        grid:  Tableau 2D float32 (H, W).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        str(path),
        mode="w",
        driver="GTiff",
        height=grid.shape[0],
        width=grid.shape[1],
        count=1,
        dtype=np.float32,
        crs="EPSG:2154",
        transform=_TRANSFORM,
    ) as dst:
        dst.write(grid[np.newaxis, :, :].astype(np.float32))


# ===========================================================================
# Conversion indices ↔ coordonnées
# ===========================================================================

def rc_to_xy(row: int, col: int) -> tuple[float, float]:
    """
    Convertit (row, col) en coordonnées géographiques (x, y) en mètres.

    Cohérent avec la fonction xy_to_rowcol de visualize_leg.py :
        col_f = (x - transform.c) / transform.a  →  x = col * cell
        row_f = (y - transform.f) / transform.e  →  y = 600 - row * cell
    """
    x = col * _CELL
    y = 600.0 - row * _CELL
    return x, y


# ===========================================================================
# SCÉNARIO 1 — "La Colline"
# ===========================================================================

def generate_hill() -> tuple[np.ndarray, np.ndarray]:
    """
    MNT : colline conique gaussienne au centre (+40 m, σ = 25 px = 75 m).
    VEG : 1.0 partout (forêt courable uniforme).

    Attente A* : contournement par les flancs nord ou sud de la colline.
    La ligne directe (est→ouest en passant par le sommet) est pénalisée par
    les fortes pentes (Tobler) — le chemin optimal fait un détour.
    """
    col_idx, row_idx = np.meshgrid(
        np.arange(_W, dtype=np.float32),
        np.arange(_H, dtype=np.float32),
    )
    sigma = 25.0
    elev = 40.0 * np.exp(
        -((col_idx - 100.0) ** 2 + (row_idx - 100.0) ** 2) / (2.0 * sigma ** 2)
    )
    veg = np.ones((_H, _W), dtype=np.float32)
    return elev.astype(np.float32), veg


# ===========================================================================
# SCÉNARIO 2 — "Le Mur Vert"
# ===========================================================================

def generate_green_wall() -> tuple[np.ndarray, np.ndarray]:
    """
    MNT : terrain plat (0 m).
    VEG : bande dense (0.2) en x = [240, 360 m] (col 80–120) sur toute la hauteur,
          avec une faille praticable (1.0) en y = [465, 555 m] (row 15–45).

    Géométrie de la décision :
      - Traversée directe par la bande dense :
            120 m × coût × 5 (veg pénalité) = 600 m-équivalent
      - Détour par la faille (row 15–45, row start=100) :
            montée de 255 m + 120 m + descente de 255 m = 630 m réels
            mais à vitesse pleine → ~630 m-équivalent
      → Le détour par la faille est légèrement avantageux ;
        la faille est visiblement empruntée sur le PNG.

    Attente A* : chemin remontant vers la faille, traversée en blanc, redescente.
    """
    elev = np.zeros((_H, _W), dtype=np.float32)
    veg  = np.ones((_H, _W),  dtype=np.float32)

    # Bande dense sur toute la hauteur (cols 80–120)
    veg[:, 80:121] = 0.2

    # Faille praticable dans la bande (rows 15–45)
    veg[15:46, 80:121] = 1.0

    return elev, veg


# ===========================================================================
# SCÉNARIO 3 — "La Descente Dangereuse"
# ===========================================================================

def generate_ravine() -> tuple[np.ndarray, np.ndarray]:
    """
    MNT : plateau à 40 m au nord, plaine à 0 m au sud, séparés par :
      - une falaise abrupte (40 m / 30 m ≈ 133 % de pente) sur cols 40–199
        (Tobler ≈ 0.008 → 125× plus lent),
      - un gué progressif (40 m / 360 m ≈ 11 % de pente) sur cols 0–39
        (Tobler ≈ 0.57 → 1.75× plus lent).

    VEG : 1.0 partout.

    Profil en coupe (col ≥ 40) :
        rows  0–89  → 40 m  (plateau)
        rows 90–99  → 40 → 0 m en 10 px = 30 m  (falaise)
        rows 100+   → 0 m  (plaine)

    Profil en coupe (col < 40) — gué :
        rows  0–39  → 40 m  (plateau)
        rows 40–159 → 40 → 0 m en 120 px = 360 m  (descente douce)
        rows 160+   → 0 m  (plaine)

    Attente A* : depuis le plateau NE, zigzag jusqu'au gué SO, puis retour SE.
    """
    elev = np.zeros((_H, _W), dtype=np.float32)

    # Plateau (toutes colonnes, rows 0–89)
    elev[:90, :] = 40.0

    # Falaise abrupte — cols 40+, rows 90–99
    cliff_vals = np.linspace(40.0, 0.0, 10, endpoint=False, dtype=np.float32)
    elev[90:100, 40:] = cliff_vals[:, np.newaxis]

    # Gué progressif — cols 0–39, rows 40–159
    ford_vals = np.linspace(40.0, 0.0, 120, endpoint=False, dtype=np.float32)
    elev[40:160, :40] = ford_vals[:, np.newaxis]

    veg = np.ones((_H, _W), dtype=np.float32)
    return elev.astype(np.float32), veg


# ===========================================================================
# Dataclass Scénario
# ===========================================================================

@dataclass
class Scenario:
    """Paramètres complets d'un scénario de test visuel."""

    name:      str
    label:     str
    elev_path: Path
    veg_path:  Path
    start_xy:  tuple[float, float]   # (x, y) en mètres géographiques
    end_xy:    tuple[float, float]   # (x, y) en mètres géographiques
    out_path:  Path


# ===========================================================================
# Génération des rasters + construction des scénarios
# ===========================================================================

def build_scenarios(output_dir: Path) -> list[Scenario]:
    """
    Génère les 3 couples (MNT.tif, VEG.tif) et construit la liste des scénarios.

    Les fichiers sont systématiquement écrasés si déjà présents.
    """
    scenarios: list[Scenario] = []

    # ------------------------------------------------------------------
    # Scénario 1 — La Colline
    # ------------------------------------------------------------------
    elev1, veg1 = generate_hill()
    elev1_path  = output_dir / "hill_elev.tif"
    veg1_path   = output_dir / "hill_veg.tif"
    save_raster(elev1_path, elev1)
    save_raster(veg1_path, veg1)
    log.info("[1/3] hill      — rasters générés : %s, %s", elev1_path.name, veg1_path.name)

    scenarios.append(Scenario(
        name      = "test_hill",
        label     = "La Colline",
        elev_path = elev1_path,
        veg_path  = veg1_path,
        # Départ : flanc ouest (col=20, row=100) ; Arrivée : flanc est (col=180, row=100)
        start_xy  = rc_to_xy(row=100, col=20),    # (60.0, 300.0)
        end_xy    = rc_to_xy(row=100, col=180),   # (540.0, 300.0)
        out_path  = output_dir / "test_hill.png",
    ))

    # ------------------------------------------------------------------
    # Scénario 2 — Le Mur Vert
    # ------------------------------------------------------------------
    elev2, veg2 = generate_green_wall()
    elev2_path  = output_dir / "green_elev.tif"
    veg2_path   = output_dir / "green_veg.tif"
    save_raster(elev2_path, elev2)
    save_raster(veg2_path, veg2)
    log.info("[2/3] green     — rasters générés : %s, %s", elev2_path.name, veg2_path.name)

    scenarios.append(Scenario(
        name      = "test_green",
        label     = "Le Mur Vert",
        elev_path = elev2_path,
        veg_path  = veg2_path,
        # Départ : gauche (col=20, row=100) ; Arrivée : droite (col=180, row=100)
        start_xy  = rc_to_xy(row=100, col=20),    # (60.0, 300.0)
        end_xy    = rc_to_xy(row=100, col=180),   # (540.0, 300.0)
        out_path  = output_dir / "test_green.png",
    ))

    # ------------------------------------------------------------------
    # Scénario 3 — La Descente Dangereuse
    # ------------------------------------------------------------------
    elev3, veg3 = generate_ravine()
    elev3_path  = output_dir / "ravine_elev.tif"
    veg3_path   = output_dir / "ravine_veg.tif"
    save_raster(elev3_path, elev3)
    save_raster(veg3_path, veg3)
    log.info("[3/3] ravine    — rasters générés : %s, %s", elev3_path.name, veg3_path.name)

    scenarios.append(Scenario(
        name      = "test_ravine",
        label     = "La Descente Dangereuse",
        elev_path = elev3_path,
        veg_path  = veg3_path,
        # Départ : plateau NE (col=170, row=20) ; Arrivée : plaine SE (col=170, row=180)
        start_xy  = rc_to_xy(row=20,  col=170),   # (510.0, 540.0)
        end_xy    = rc_to_xy(row=180, col=170),   # (510.0,  60.0)
        out_path  = output_dir / "test_ravine.png",
    ))

    return scenarios


# ===========================================================================
# Exécution d'un scénario via subprocess
# ===========================================================================

def run_scenario(scenario: Scenario) -> bool:
    """
    Appelle visualize_leg.py en subprocess pour un scénario donné.

    Returns:
        True si returncode == 0, False sinon.
    """
    cmd = [
        sys.executable,
        str(_VISUALIZE),
        "--elev",  str(scenario.elev_path),
        "--veg",   str(scenario.veg_path),
        "--start", str(scenario.start_xy[0]), str(scenario.start_xy[1]),
        "--end",   str(scenario.end_xy[0]),   str(scenario.end_xy[1]),
        "--out",   str(scenario.out_path),
    ]

    log.info(
        "%-12s | start=(%.0f, %.0f)  end=(%.0f, %.0f)  out=%s",
        scenario.name,
        scenario.start_xy[0], scenario.start_xy[1],
        scenario.end_xy[0],   scenario.end_xy[1],
        scenario.out_path.name,
    )

    result = subprocess.run(cmd, text=True)
    return result.returncode == 0


# ===========================================================================
# Point d'entrée
# ===========================================================================

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Banc d'essai visuel du moteur A* Tobler (3 scénarios synthétiques).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--output-dir", default="tests/output",
        help="Dossier de sortie pour les rasters GeoTIFF et les PNG.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    output_dir = _BACKEND / args.output_dir

    log.info("Dossier de sortie : %s", output_dir)
    log.info("Script visualize : %s", _VISUALIZE)

    if not _VISUALIZE.is_file():
        log.error("visualize_leg.py introuvable : %s", _VISUALIZE)
        sys.exit(1)

    # 1. Génération des rasters
    log.info("─" * 60)
    log.info("Génération des rasters synthétiques…")
    scenarios = build_scenarios(output_dir)

    # 2. Exécution des scénarios
    log.info("─" * 60)
    log.info("Lancement de visualize_leg.py pour chaque scénario…")

    results: list[tuple[str, str, bool]] = []
    for sc in scenarios:
        log.info("─" * 40)
        log.info("Scénario : %s — %s", sc.name, sc.label)
        ok = run_scenario(sc)
        status = "OK" if ok else "ERROR"
        results.append((sc.name, sc.label, ok))
        log.info("→ %s  [%s]  PNG=%s", sc.name, status, sc.out_path)

    # 3. Récapitulatif
    log.info("─" * 60)
    log.info("RÉCAPITULATIF")
    all_ok = True
    for name, label, ok in results:
        status = "✓ OK   " if ok else "✗ ERROR"
        log.info("  %s  %-20s  %s", status, name, label)
        if not ok:
            all_ok = False

    if all_ok:
        log.info("Tous les scénarios ont réussi. PNGs dans : %s", output_dir)
    else:
        log.error("Un ou plusieurs scénarios ont échoué.")
        sys.exit(1)


if __name__ == "__main__":
    main()
