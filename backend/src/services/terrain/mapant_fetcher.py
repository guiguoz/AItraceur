"""
Mapant tile fetcher — retrieves LIDAR-derived ISOM raster tiles from mapant.fr.

Mapant generates orienteering-style maps from LIDAR + OSM data, with ISOM
color encoding that lets us infer terrain features from pixel colors.

ISOM color palette (approximate sRGB):
  Brown  (#9b6f37 / #c8a06e) → contours, relief, micro-terrain
  Yellow (#f5f500 / #ffe88c) → open land
  White  (#ffffff / #f2f2e8) → fast forest / open forest
  Green  (#00b400 / #4ca800) → slow forest / impenetrable
  Blue   (#00a0ff / #73c8ff) → water
  Black  (#000000 / #222222) → paths, cliffs, boulders, man-made

Usage:
  from services.terrain.mapant_fetcher import MapantFetcher
  fetcher = MapantFetcher()
  features = fetcher.get_terrain_features(lat=48.5, lon=2.3, radius_m=100)
"""

import hashlib
import io
import logging
import math
import time
from pathlib import Path
from typing import Optional
import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mapant.fr tile URL (XYZ slippy map tiles, EPSG:3857)
MAPANT_FR_TILE_URL = "https://mapant.fr/tile/{z}/{x}/{y}.png"

# Zoom level for feature extraction (z=15 → ~1.2m/pixel at lat 48°)
DEFAULT_ZOOM = 15

# Tile cache directory
CACHE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "mapant_cache"

# Request settings
REQUEST_DELAY_S = 0.2
TIMEOUT_S = 10
MAX_RETRIES = 3

# ISOM color ranges (HSV-based classification)
# Each entry: (name, hue_min, hue_max, sat_min, val_min, val_max)
# Using HSV where H in [0,360], S/V in [0,1]
_COLOR_CLASSES = [
    # Brown contours: hue 20-40, moderate saturation
    ("relief",       20,  40, 0.3, 0.3, 0.9),
    # Yellow open land: hue 50-65, high saturation
    ("open",         50,  65, 0.5, 0.7, 1.0),
    # Green forest: hue 90-150, medium-high saturation
    ("slow_forest",  90, 150, 0.4, 0.2, 0.7),
    # Blue water: hue 190-220
    ("water",       190, 220, 0.4, 0.4, 1.0),
    # Black paths/cliffs: very low value
    ("black_feature",  0, 360, 0.0, 0.0, 0.15),
    # White fast forest: low saturation, high value
    ("fast_forest",    0, 360, 0.0, 0.85, 1.0),
]


# ---------------------------------------------------------------------------
# Tile math
# ---------------------------------------------------------------------------

def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert WGS84 to XYZ tile coordinates."""
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def tile_to_lat_lon(x: int, y: int, zoom: int) -> tuple[float, float]:
    """Convert XYZ tile top-left corner to WGS84."""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_r = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_r)
    return lat, lon


def meters_per_pixel(lat: float, zoom: int) -> float:
    """Ground resolution in metres per pixel at given lat/zoom."""
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)


def pixel_offset(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Pixel offset within tile (0-255, 0-255)."""
    tx, ty = lat_lon_to_tile(lat, lon, zoom)
    n = 2 ** zoom
    # Fractional tile position
    fx = (lon + 180.0) / 360.0 * n - tx
    lat_r = math.radians(lat)
    fy = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n - ty
    return int(fx * 256), int(fy * 256)


# ---------------------------------------------------------------------------
# Color classification
# ---------------------------------------------------------------------------

def rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    cmax = max(r, g, b)
    cmin = min(r, g, b)
    delta = cmax - cmin

    if delta == 0:
        h = 0.0
    elif cmax == r:
        h = 60.0 * (((g - b) / delta) % 6)
    elif cmax == g:
        h = 60.0 * ((b - r) / delta + 2)
    else:
        h = 60.0 * ((r - g) / delta + 4)

    s = 0.0 if cmax == 0 else delta / cmax
    v = cmax
    return h, s, v


def classify_pixel(r: int, g: int, b: int, a: int = 255) -> Optional[str]:
    """Return ISOM terrain class for a pixel, or None if transparent/unclassified."""
    if a < 128:
        return None
    h, s, v = rgb_to_hsv(r, g, b)
    for name, h_min, h_max, s_min, v_min, v_max in _COLOR_CLASSES:
        if h_min <= h <= h_max and s >= s_min and v_min <= v <= v_max:
            return name
    return "other"


# ---------------------------------------------------------------------------
# Main fetcher class
# ---------------------------------------------------------------------------

class MapantFetcher:
    """Fetch Mapant tiles and extract terrain feature vectors."""

    def __init__(
        self,
        tile_url: str = MAPANT_FR_TILE_URL,
        zoom: int = DEFAULT_ZOOM,
        cache_dir: Path = CACHE_DIR,
        use_cache: bool = True,
    ):
        self.tile_url = tile_url
        self.zoom = zoom
        self.cache_dir = cache_dir
        self.use_cache = use_cache
        self._session = self._make_session()
        if use_cache:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry = Retry(total=MAX_RETRIES, backoff_factor=0.5, status_forcelist=[429, 500, 503])
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers["User-Agent"] = "AItraceur-ML-TerrainFetcher/1.0"
        return s

    def _cache_path(self, z: int, x: int, y: int) -> Path:
        return self.cache_dir / f"{z}_{x}_{y}.png"

    def fetch_tile(self, x: int, y: int, z: Optional[int] = None) -> Optional[bytes]:
        """Fetch a single PNG tile. Returns raw bytes or None."""
        z = z or self.zoom
        cache_path = self._cache_path(z, x, y)

        if self.use_cache and cache_path.exists():
            return cache_path.read_bytes()

        url = self.tile_url.format(z=z, x=x, y=y)
        try:
            time.sleep(REQUEST_DELAY_S)
            r = self._session.get(url, timeout=TIMEOUT_S)
            if r.status_code == 404:
                log.debug("Tile %d/%d/%d not covered by Mapant", z, x, y)
                return None
            r.raise_for_status()
            data = r.content
            if self.use_cache:
                cache_path.write_bytes(data)
            return data
        except Exception as e:
            log.debug("Tile fetch error %s: %s", url, e)
            return None

    def get_patch(
        self,
        lat: float,
        lon: float,
        radius_m: float = 100.0,
    ) -> Optional[bytes]:
        """
        Fetch the tile covering (lat, lon) and crop a square patch
        of radius_m around the point. Returns PNG bytes or None.
        """
        try:
            from PIL import Image
        except ImportError:
            log.error("Pillow not installed: pip install Pillow")
            return None

        tx, ty = lat_lon_to_tile(lat, lon, self.zoom)
        tile_bytes = self.fetch_tile(tx, ty)
        if tile_bytes is None:
            return None

        img = Image.open(io.BytesIO(tile_bytes)).convert("RGBA")
        px, py = pixel_offset(lat, lon, self.zoom)
        mpp = meters_per_pixel(lat, self.zoom)
        half_px = int(radius_m / mpp)

        # Pad if patch extends beyond tile (simple: use single tile for now)
        left   = max(0, px - half_px)
        top    = max(0, py - half_px)
        right  = min(255, px + half_px)
        bottom = min(255, py + half_px)

        patch = img.crop((left, top, right, bottom))
        buf = io.BytesIO()
        patch.save(buf, format="PNG")
        return buf.getvalue()

    def get_terrain_features(
        self,
        lat: float,
        lon: float,
        radius_m: float = 100.0,
    ) -> dict:
        """
        Extract terrain feature vector from Mapant tile at (lat, lon).

        Returns dict with:
          - covered: bool (Mapant has data for this location)
          - relief_ratio: float (fraction of pixels classified as relief/contours)
          - open_ratio: float (open land)
          - slow_forest_ratio: float (green = slow/impenetrable)
          - fast_forest_ratio: float (white forest = fast)
          - water_ratio: float
          - black_feature_ratio: float (paths, cliffs, rocks)
          - terrain_complexity: float (Shannon entropy of class distribution)
          - dominant_terrain: str (most common class)
          - mapant_zoom: int
        """
        empty = {
            "covered": False,
            "relief_ratio": 0.0,
            "open_ratio": 0.0,
            "slow_forest_ratio": 0.0,
            "fast_forest_ratio": 0.0,
            "water_ratio": 0.0,
            "black_feature_ratio": 0.0,
            "terrain_complexity": 0.0,
            "dominant_terrain": "unknown",
            "mapant_zoom": self.zoom,
        }

        try:
            from PIL import Image
        except ImportError:
            log.error("Pillow not installed: pip install Pillow")
            return empty

        tx, ty = lat_lon_to_tile(lat, lon, self.zoom)
        tile_bytes = self.fetch_tile(tx, ty)
        if tile_bytes is None:
            return empty

        img = Image.open(io.BytesIO(tile_bytes)).convert("RGBA")
        px, py = pixel_offset(lat, lon, self.zoom)
        mpp = meters_per_pixel(lat, self.zoom)
        half_px = int(radius_m / mpp)

        left   = max(0, px - half_px)
        top    = max(0, py - half_px)
        right  = min(255, px + half_px)
        bottom = min(255, py + half_px)

        patch = img.crop((left, top, right, bottom))
        pixels = list(patch.getdata())

        counts: dict[str, int] = {
            "relief": 0, "open": 0, "slow_forest": 0,
            "fast_forest": 0, "water": 0, "black_feature": 0, "other": 0,
        }
        total = 0
        for pixel in pixels:
            r, g, b, a = pixel
            cls = classify_pixel(r, g, b, a)
            if cls:
                counts[cls] = counts.get(cls, 0) + 1
                total += 1

        if total == 0:
            return empty

        ratios = {k: v / total for k, v in counts.items()}

        # Shannon entropy (terrain complexity)
        import math as _math
        entropy = -sum(
            p * _math.log2(p) for p in ratios.values() if p > 0
        )
        max_entropy = _math.log2(len(counts))
        complexity = entropy / max_entropy if max_entropy > 0 else 0.0

        dominant = max(
            (k for k in counts if k != "other"),
            key=lambda k: counts[k],
            default="unknown",
        )

        return {
            "covered": True,
            "relief_ratio": round(ratios.get("relief", 0.0), 4),
            "open_ratio": round(ratios.get("open", 0.0), 4),
            "slow_forest_ratio": round(ratios.get("slow_forest", 0.0), 4),
            "fast_forest_ratio": round(ratios.get("fast_forest", 0.0), 4),
            "water_ratio": round(ratios.get("water", 0.0), 4),
            "black_feature_ratio": round(ratios.get("black_feature", 0.0), 4),
            "terrain_complexity": round(complexity, 4),
            "dominant_terrain": dominant,
            "mapant_zoom": self.zoom,
        }

    def check_coverage(self, lat: float, lon: float) -> bool:
        """Quick check if Mapant covers this location."""
        tx, ty = lat_lon_to_tile(lat, lon, self.zoom)
        return self.fetch_tile(tx, ty) is not None
