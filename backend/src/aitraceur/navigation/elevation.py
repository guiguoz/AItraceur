"""
ElevationProvider — lecture et interpolation d'un raster MNT (GeoTIFF).

Charge le raster en mémoire au démarrage pour éviter les I/O répétés.
L'interpolation bilinéaire donne une altitude lisse entre cellules voisines,
ce qui est critique pour un calcul de pente réaliste.

Exemple :
    provider = ElevationProvider("/data/mnt_lidar_3m.tif")
    alt = provider.get_elevation(456230.0, 6902150.0)   # Lambert-93
"""
from __future__ import annotations

from typing import Optional, Tuple

try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False

try:
    import rasterio                           # noqa: F401
    _RASTERIO_OK = True
except ImportError:
    _RASTERIO_OK = False


class ElevationProvider:
    """
    Lecture et interpolation bilinéaire d'un raster MNT.

    Le raster est chargé entièrement en mémoire (np.ndarray float32).
    Les points hors emprise retournent l'altitude de la cellule bord la plus proche.

    Attributes:
        _grid:      Tableau (H, W) float32 — altitudes en mètres.
        _transform: Transformation affine rasterio (origine + résolution).
        _height:    Nombre de lignes du raster.
        _width:     Nombre de colonnes du raster.
    """

    def __init__(self, geotiff_path: str) -> None:
        if not _NP_OK:
            raise ImportError("numpy est requis.")
        if not _RASTERIO_OK:
            raise ImportError("rasterio est requis : pip install rasterio")

        import rasterio as rio

        with rio.open(geotiff_path) as src:
            self._grid: np.ndarray = src.read(1).astype(np.float32)
            self._transform = src.transform
            self._nodata: Optional[float] = src.nodata
            self._height, self._width = self._grid.shape

        # Remplacer les valeurs nodata par 0 m (évite les NaN dans les calculs)
        if self._nodata is not None:
            self._grid = np.where(
                np.isclose(self._grid, self._nodata), 0.0, self._grid
            ).astype(np.float32)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def get_elevation(self, x: float, y: float) -> float:
        """
        Retourne l'altitude au point (x, y) en coordonnées projetées (m).

        Interpolation bilinéaire depuis les 4 cellules voisines.
        Clamp sur les bords si le point est hors emprise.

        Args:
            x: Coordonnée Est (mètres).
            y: Coordonnée Nord (mètres).

        Returns:
            Altitude en mètres.
        """
        row_f, col_f = self._to_rowcol_float(x, y)

        # Clamp sur les bords du raster
        row_f = max(0.0, min(row_f, self._height - 1.0001))
        col_f = max(0.0, min(col_f, self._width  - 1.0001))

        r0 = int(row_f)
        c0 = int(col_f)
        dr = row_f - r0
        dc = col_f - c0

        r1 = min(r0 + 1, self._height - 1)
        c1 = min(c0 + 1, self._width  - 1)

        # Interpolation bilinéaire
        v00 = float(self._grid[r0, c0])
        v01 = float(self._grid[r0, c1])
        v10 = float(self._grid[r1, c0])
        v11 = float(self._grid[r1, c1])

        return (
            v00 * (1.0 - dr) * (1.0 - dc)
            + v01 * (1.0 - dr) * dc
            + v10 * dr         * (1.0 - dc)
            + v11 * dr         * dc
        )

    def get_elevation_grid(self) -> "np.ndarray":
        """
        Retourne la grille d'altitude complète (vue lecture seule).

        Returns:
            ndarray (H, W) float32 — altitudes en mètres.
        """
        return self._grid

    # ------------------------------------------------------------------
    # Méthodes privées
    # ------------------------------------------------------------------

    def _to_rowcol_float(self, x: float, y: float) -> Tuple[float, float]:
        """
        Convertit des coordonnées monde en position fractionnaire (row_f, col_f).

        Utilise la transformation affine rasterio :
          x = t.c + col * t.a   (t.a = résolution pixel en X)
          y = t.f + row * t.e   (t.e < 0 car Y décroît vers le bas)
        """
        t = self._transform
        col_f = (x - t.c) / t.a
        row_f = (y - t.f) / t.e
        return row_f, col_f
