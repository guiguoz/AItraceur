"""
Mapant Tile Fetcher — AItraceur ML Dataset Builder
====================================================

For each control point in rg2_controls.geojson, fetches a raster patch
from the appropriate Mapant service and extracts terrain features.

Supported services (verified working):
  - Finland    : wmts.mapant.fi          (WMTS EPSG:3857)  → standard XYZ
  - Spain      : mapant.es               (WMS  EPSG:3857)  → WMS bbox
  - Switzerland: mapant.ch               (WMTS LV95)       → custom tile grid
  - Norway     : mapant.no               (XYZ  EPSG:32633) → UTM33 tile grid
  - Estonia    : mapantee.gokartor.se    (WMS  EPSG:3301)  → WMS bbox

Usage:
  python fetch_mapant_patches.py                    # process rg2_controls.geojson
  python fetch_mapant_patches.py --zoom 14          # override zoom level
  python fetch_mapant_patches.py --patch-size 256   # pixel patch size
  python fetch_mapant_patches.py --country FI       # single country
  python fetch_mapant_patches.py --limit 100        # max patches
  python fetch_mapant_patches.py --check            # test one tile per service

Output:
  data/mapant/patches/{country}/{lat}_{lon}.png  — raster patch
  data/mapant/features.csv                       — color histogram features
  data/mapant/dataset.geojson                    — merged dataset for ML
"""

import argparse
import csv
import json
import logging
import math
import time
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

# Optional pyproj for non-WebMercator projections
try:
    from pyproj import Transformer
    HAS_PYPROJ = True
except ImportError:
    HAS_PYPROJ = False
    logging.warning("pyproj not installed — Norway/Estonia/Switzerland unavailable. "
                    "Install with: pip install pyproj")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR     = Path(__file__).parent.parent / "data"
RG2_GEOJSON  = DATA_DIR / "rg2" / "rg2_controls.geojson"
OUTPUT_DIR   = DATA_DIR / "mapant"
PATCHES_DIR  = OUTPUT_DIR / "patches"
FEATURES_CSV = OUTPUT_DIR / "features.csv"
DATASET_JSON = OUTPUT_DIR / "dataset.geojson"

REQUEST_DELAY_S = 0.3    # polite delay between tile requests
TIMEOUT_S       = 15
DEFAULT_ZOOM    = 14     # z=14 ≈ 10m/px — good for forest features
DEFAULT_PATCH   = 256    # output patch pixel size

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("mapant")


# ---------------------------------------------------------------------------
# Country bounding boxes → service routing
# ---------------------------------------------------------------------------

COUNTRY_BBOX = {
    "EE": dict(lat_min=57.5,  lat_max=59.7,  lon_min=21.5,  lon_max=28.2),
    "FI": dict(lat_min=59.8,  lat_max=70.1,  lon_min=19.1,  lon_max=31.6),
    "NO": dict(lat_min=57.8,  lat_max=71.2,  lon_min=4.5,   lon_max=31.1),
    "ES": dict(lat_min=27.0,  lat_max=43.8,  lon_min=-18.5, lon_max=4.3),
    "CH": dict(lat_min=45.8,  lat_max=47.8,  lon_min=5.9,   lon_max=10.5),
}

# Priority order: smallest bbox first to avoid false positives in overlaps
_ROUTING_ORDER = ["CH", "EE", "FI", "ES", "NO"]


def detect_country(lat: float, lon: float) -> Optional[str]:
    for cc in _ROUTING_ORDER:
        b = COUNTRY_BBOX[cc]
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
            return cc
    return None


# ---------------------------------------------------------------------------
# Web Mercator helpers (no pyproj needed)
# ---------------------------------------------------------------------------

def _wm_x(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * (2 ** zoom)


def _wm_y(lat: float, zoom: int) -> float:
    lat_r = math.radians(lat)
    return (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * (2 ** zoom)


def _lon_lat_to_wm_m(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 → Web Mercator metres."""
    mx = 6378137.0 * math.radians(lon)
    my = 6378137.0 * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return mx, my


def _center_crop(img: Image.Image, cx: int, cy: int, size: int) -> Image.Image:
    """Crop `size`×`size` centered on (cx, cy), padding white if near edge."""
    w, h = img.size
    half = size // 2
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(w, cx + half), min(h, cy + half)
    crop = img.crop((x0, y0, x1, y1))
    if crop.size == (size, size):
        return crop
    padded = Image.new("RGB", (size, size), (255, 255, 255))
    padded.paste(crop, (half - (cx - x0), half - (cy - y0)))
    return padded


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

class MapantSession:
    def __init__(self):
        self._s = requests.Session()
        self._s.headers["User-Agent"] = "AItraceur-ML-Research/1.0 (orienteering)"

    def get_image(self, url: str, params: dict = None) -> Optional[Image.Image]:
        try:
            r = self._s.get(url, params=params, timeout=TIMEOUT_S)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")
            time.sleep(REQUEST_DELAY_S)
            return img
        except Exception as e:
            log.debug("Tile fetch failed %s %s → %s", url, params, e)
            return None


# ---------------------------------------------------------------------------
# Service implementations
# ---------------------------------------------------------------------------

def fetch_finland(s: MapantSession, lat: float, lon: float,
                  zoom: int, patch_px: int) -> Optional[Image.Image]:
    """
    WMTS EPSG:3857 — wmts.mapant.fi
    URL: https://wmts.mapant.fi/wmts_EPSG3857.php?z={z}&y={TileRow}&x={TileCol}
    Verified: HTTP 200 at Helsinki (60.17, 24.94)
    """
    tx = int(_wm_x(lon, zoom))
    ty = int(_wm_y(lat, zoom))
    img = s.get_image("https://wmts.mapant.fi/wmts_EPSG3857.php",
                      {"z": zoom, "y": ty, "x": tx})
    if img is None:
        return None
    # Pixel offset within the 256×256 tile
    px = int((_wm_x(lon, zoom) - tx) * img.width)
    py = int((_wm_y(lat, zoom) - ty) * img.height)
    return _center_crop(img, px, py, patch_px)


def fetch_spain(s: MapantSession, lat: float, lon: float,
                zoom: int, patch_px: int) -> Optional[Image.Image]:
    """
    WMS EPSG:3857 — mapant.es/wms
    Verified: HTTP 200 with 120KB PNG around Madrid
    """
    mpp = 156543.03 * math.cos(math.radians(lat)) / (2 ** zoom)
    half = mpp * patch_px / 2
    mx, my = _lon_lat_to_wm_m(lon, lat)
    bbox = f"{mx-half},{my-half},{mx+half},{my+half}"
    return s.get_image("https://mapant.es/wms", {
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
        "LAYERS": "mapant", "SRS": "EPSG:3857", "BBOX": bbox,
        "WIDTH": patch_px, "HEIGHT": patch_px, "FORMAT": "image/png",
    })


def fetch_switzerland(s: MapantSession, lat: float, lon: float,
                      zoom: int, patch_px: int) -> Optional[Image.Image]:
    """
    WMTS EPSG:2056 (Swiss LV95) — mapant.ch
    URL: https://mapant.ch/{TileMatrix}/{TileRow}/{TileCol}.png
    Grid origin: [2480000, 1302000] LV95, coverage: 354000×227000 m
    Levels 5-9: matrix size doubles each level.
    Verified: HTTP 200, tiles ~1-2 MB
    """
    if not HAS_PYPROJ:
        return None
    t = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)
    lv_x, lv_y = t.transform(lon, lat)

    # CH zoom: map web zoom 10-14 → CH level 5-9
    # Grid: level 9 = 354×227 tiles, each level halves: n = round(354 / 2^(9-z))
    ch_z = max(5, min(9, zoom - 5))
    n_cols = round(354 / (2 ** (9 - ch_z)))
    n_rows = round(227 / (2 ** (9 - ch_z)))
    tile_w = 354000.0 / n_cols
    tile_h = 227000.0 / n_rows
    ox, oy = 2480000.0, 1302000.0   # top-left origin

    col = int((lv_x - ox) / tile_w)
    row = int((oy - lv_y) / tile_h)
    col = max(0, min(col, n_cols - 1))
    row = max(0, min(row, n_rows - 1))

    img = s.get_image(f"https://mapant.ch/{ch_z}/{row}/{col}.png")
    if img is None:
        return None
    px = int((lv_x - (ox + col * tile_w)) / tile_w * img.width)
    py = int(((oy - row * tile_h) - lv_y) / tile_h * img.height)
    return _center_crop(img, px, py, patch_px)


def fetch_norway(s: MapantSession, lat: float, lon: float,
                 zoom: int, patch_px: int) -> Optional[Image.Image]:
    """
    Norway — mapant.no extract-png API (UTM33N bbox)
    Endpoint: GET /api/extract-png?x0=&y0=&x1=&y1=  (EPSG:32633 coordinates)
    Verified: HTTP 200 with bbox around Oslo area.
    The XYZ tile endpoint returns 404 — extract-png is the reliable method.
    """
    if not HAS_PYPROJ:
        return None
    t = Transformer.from_crs("EPSG:4326", "EPSG:32633", always_xy=True)
    ux, uy = t.transform(lon, lat)

    # metres per pixel at this zoom for lat
    mpp = 156543.03 * math.cos(math.radians(lat)) / (2 ** zoom)
    half = mpp * patch_px / 2

    return s.get_image("https://mapant.no/api/extract-png", {
        "x0": ux - half, "y0": uy - half,
        "x1": ux + half, "y1": uy + half,
    })


def fetch_estonia(s: MapantSession, lat: float, lon: float,
                  zoom: int, patch_px: int) -> Optional[Image.Image]:
    """
    WMS EPSG:3301 (Estonian National Grid) — mapantee.gokartor.se
    Verified: HTTP 200 at Tallinn bbox
    """
    if not HAS_PYPROJ:
        return None
    t = Transformer.from_crs("EPSG:4326", "EPSG:3301", always_xy=True)
    ex, ey = t.transform(lon, lat)
    mpp = 156543.03 * math.cos(math.radians(lat)) / (2 ** zoom)
    half = mpp * patch_px / 2
    bbox = f"{ex-half},{ey-half},{ex+half},{ey+half}"
    return s.get_image("https://mapantee.gokartor.se/ogc/wms.php", {
        "SERVICE": "WMS", "REQUEST": "GetMap", "v": "1",
        "LAYERS": "mapantee", "SRS": "EPSG:3301",
        "BBOX": bbox, "WIDTH": patch_px, "HEIGHT": patch_px,
        "FORMAT": "image/png",
    })


FETCHERS = {
    "FI": fetch_finland,
    "ES": fetch_spain,
    "CH": fetch_switzerland,
    "NO": fetch_norway,
    "EE": fetch_estonia,
}


def fetch_patch(s: MapantSession, lat: float, lon: float,
                zoom: int, patch_px: int) -> tuple[Optional[Image.Image], str]:
    cc = detect_country(lat, lon)
    if cc is None or cc not in FETCHERS:
        return None, cc or "XX"
    return FETCHERS[cc](s, lat, lon, zoom, patch_px), cc


# ---------------------------------------------------------------------------
# Terrain feature extraction
# ---------------------------------------------------------------------------

# ISOM approximate RGB palette (center, tolerance)
ISOM_PALETTE = {
    "brown_relief":  ((180, 120,  60), 30),   # contours, micro-relief
    "green_dense":   (( 80, 140,  80), 35),   # impassable veg
    "green_light":   ((160, 210, 160), 35),   # slow run veg
    "yellow_open":   ((255, 240, 130), 40),   # open terrain
    "blue_water":    (( 80, 150, 220), 40),   # water
    "black_detail":  (( 50,  50,  50), 40),   # paths, cliffs, boulders
    "white_forest":  ((240, 240, 240), 20),   # runnble open forest
}


def extract_features(img: Image.Image) -> dict:
    """Color histogram over ISOM palette. Returns fraction per class."""
    pixels = list(img.getdata())
    n = len(pixels)
    counts = {k: 0 for k in ISOM_PALETTE}
    for r, g, b in pixels:
        for name, (c, tol) in ISOM_PALETTE.items():
            if abs(r - c[0]) < tol and abs(g - c[1]) < tol and abs(b - c[2]) < tol:
                counts[name] += 1
                break
    return {k: round(v / n, 4) for k, v in counts.items()}


def is_empty_patch(img: Image.Image, threshold: float = 0.92) -> bool:
    pixels = list(img.getdata())
    white = sum(1 for r, g, b in pixels if r > 230 and g > 230 and b > 230)
    return white / len(pixels) > threshold


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def load_controls(path: Path, country_filter: Optional[str] = None) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    controls = []
    for feat in data["features"]:
        lon, lat = feat["geometry"]["coordinates"]
        cc = detect_country(lat, lon)
        if cc is None or (country_filter and cc != country_filter):
            continue
        controls.append({"lat": lat, "lon": lon, "country": cc, **feat["properties"]})
    return controls


def process(controls: list[dict], zoom: int, patch_px: int,
            limit: Optional[int]) -> list[dict]:
    s = MapantSession()
    results = []
    total = min(len(controls), limit) if limit else len(controls)
    skip_service = skip_empty = fetched = 0

    log.info("Processing %d controls (zoom=%d patch=%dpx)…", total, zoom, patch_px)

    for i, ctrl in enumerate(controls[:total]):
        lat, lon, cc = ctrl["lat"], ctrl["lon"], ctrl["country"]

        patch_dir = PATCHES_DIR / cc
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_path = patch_dir / f"{lat:.5f}_{lon:.5f}.png"

        if patch_path.exists():
            img = Image.open(patch_path).convert("RGB")
        else:
            img, _ = fetch_patch(s, lat, lon, zoom, patch_px)
            if img is None:
                skip_service += 1
                continue
            if is_empty_patch(img):
                skip_empty += 1
                continue
            img.save(patch_path)

        features = extract_features(img)
        results.append({**ctrl, "patch_path": str(patch_path), **features})
        fetched += 1

        if (i + 1) % 50 == 0:
            log.info("  %d/%d | fetched=%d no_svc=%d empty=%d",
                     i + 1, total, fetched, skip_service, skip_empty)

    log.info("Done — fetched=%d no_service=%d empty=%d", fetched, skip_service, skip_empty)
    return results


def save_csv(records: list[dict]) -> None:
    if not records:
        return
    FEATURES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(FEATURES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        w.writeheader()
        w.writerows(records)
    log.info("CSV → %s (%d rows)", FEATURES_CSV, len(records))


def save_geojson(records: list[dict]) -> None:
    if not records:
        return
    feats = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
        "properties": {k: v for k, v in r.items() if k not in ("lat", "lon")},
    } for r in records]
    dataset = {
        "type": "FeatureCollection", "features": feats,
        "metadata": {
            "total": len(feats),
            "positives": sum(1 for r in records if r.get("is_control") == 1),
            "negatives": sum(1 for r in records if r.get("is_control") == 0),
            "countries": sorted({r["country"] for r in records}),
        },
    }
    DATASET_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(DATASET_JSON, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    log.info("GeoJSON → %s", DATASET_JSON)


# ---------------------------------------------------------------------------
# Service check
# ---------------------------------------------------------------------------

def run_check(zoom: int, patch_px: int):
    test_points = {
        "FI": (60.17, 24.94),   # Helsinki
        "ES": (40.42, -3.70),   # Madrid
        "CH": (46.95,  7.45),   # Bern
        "NO": (59.91, 10.75),   # Oslo
        "EE": (59.44, 24.75),   # Tallinn
    }
    s = MapantSession()
    print(f"\nService check (zoom={zoom}, patch={patch_px}px):")
    print(f"{'CC':<5} {'Status':<10} {'Size':<14} {'Non-white%'}")
    print("-" * 44)
    for cc, (lat, lon) in test_points.items():
        img, _ = fetch_patch(s, lat, lon, zoom, patch_px)
        if img is None:
            print(f"{cc:<5} FAILED     -              -")
            continue
        pixels = list(img.getdata())
        nw = sum(1 for r, g, b in pixels if not (r > 230 and g > 230 and b > 230))
        pct = 100.0 * nw / len(pixels)
        status = "EMPTY" if pct < 5 else "OK"
        print(f"{cc:<5} {status:<10} {str(img.size):<14} {pct:.1f}%")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch Mapant patches for ML training")
    parser.add_argument("--input", default=str(RG2_GEOJSON))
    parser.add_argument("--zoom", type=int, default=DEFAULT_ZOOM)
    parser.add_argument("--patch-size", type=int, default=DEFAULT_PATCH)
    parser.add_argument("--country", choices=list(FETCHERS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--check", action="store_true",
                        help="Test one tile per service and exit")
    args = parser.parse_args()

    if args.check:
        run_check(args.zoom, args.patch_size)
        return

    controls = load_controls(Path(args.input), country_filter=args.country)
    log.info("Loaded %d controls | by country: %s",
             len(controls), dict(Counter(c["country"] for c in controls)))

    if not controls:
        log.warning("No controls in Mapant-covered countries.")
        log.warning("Current RG2 data covers UK — no Mapant service for UK.")
        log.warning("Add RG2 instances for FI/NO/ES/CH/EE to get terrain patches.")
        return

    records = process(controls, args.zoom, args.patch_size, args.limit)
    save_csv(records)
    save_geojson(records)

    pos = sum(1 for r in records if r.get("is_control") == 1)
    neg = sum(1 for r in records if r.get("is_control") == 0)
    print(f"\n{'='*50}")
    print(f"Processed   : {len(records)}")
    print(f"Positives   : {pos} | Negatives: {neg}")
    print(f"Patches     : {PATCHES_DIR}")
    print(f"Features CSV: {FEATURES_CSV}")
    print(f"Dataset     : {DATASET_JSON}")


if __name__ == "__main__":
    main()
