"""
RG2 Data Pipeline — AItraceur ML Dataset Builder
=================================================

4-step pipeline:
  1. Discovery  : scrape routegadget.co.uk → extract all club subdomains
  2. Scraping   : for each club, fetch maps (worldfile) + events + courses (xpos/ypos)
  3. Transform  : pixel coords → WGS84 via worldfile affine formula
  4. Export     : GeoJSON / CSV with positive (is_control=1) + negative (is_control=0) samples

Worldfile formula (from RG2 source map.php):
  lon = A * xpos - B * ypos + C      (note: ypos in JSON is negated vs raw pixel)
  lat = D * xpos - E * ypos + F

Usage:
  python scrape_rg2.py                          # discover + scrape all (GeoJSON only)
  python scrape_rg2.py --generate-dataset       # scrape + generate image patches (CNN dataset)
  python scrape_rg2.py --instance https://...   # single club
  python scrape_rg2.py --discover-only          # list clubs, no scraping
  python scrape_rg2.py --max-events 50          # limit events per club
  python scrape_rg2.py --neg-ratio 2            # negatives per positive (default: 2)

Output (GeoJSON mode):
  data/rg2/rg2_controls.geojson   — all positive + negative samples (WGS84)
  data/rg2/rg2_scrape_log.json    — scraping statistics

Output (--generate-dataset mode):
  data/rg2/dataset/positive/      — 256x256 patches centered on real controls (label=1)
  data/rg2/dataset/negative/      — 256x256 patches on random non-control spots (label=0)
  data/rg2/dataset/metadata.csv   — img_path, label, scale, course_type, n_controls, ...
"""

import argparse
import csv
import io
import json
import logging
import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PORTAL_URL = "https://www.routegadget.co.uk/"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "rg2"
OUTPUT_CONTROLS = OUTPUT_DIR / "rg2_controls.geojson"
OUTPUT_LOG = OUTPUT_DIR / "rg2_scrape_log.json"
DATASET_DIR = OUTPUT_DIR / "dataset"

REQUEST_DELAY_S = 1.0         # polite delay between API calls
TIMEOUT_S = 20
MAX_RETRIES = 2
MIN_CONTROLS_PER_COURSE = 3   # discard courses with too few controls
NEG_DISTANCE_M = 50.0         # minimum metres from real control for negatives

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rg2pipeline")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Worldfile:
    """Affine transform: pixel (x, y) → geographic (lon, lat)."""
    A: float  # x scale (degrees lon per pixel x)
    B: float  # y rotation (degrees lon per pixel y)
    C: float  # lon origin (top-left)
    D: float  # x rotation (degrees lat per pixel x)
    E: float  # y scale (degrees lat per pixel y)
    F: float  # lat origin (top-left)
    mapid: int
    name: str
    mapfile: str = ""        # map image filename for /kartat/ endpoint
    scale: int = 4000        # nominal map scale (e.g. 4000 = 1:4000)

    def pixel_to_wgs84(self, xpos: float, ypos: float) -> tuple[float, float]:
        """
        Standard affine worldfile transform: lon = A*x + B*y + C, lat = D*x + E*y + F.
        ypos is raw pixel y (positive, increasing downward). E is negative in the API
        so the formula correctly maps downward pixels to decreasing latitude (southward).
        """
        lon = self.A * xpos + self.B * ypos + self.C
        lat = self.D * xpos + self.E * ypos + self.F
        return lon, lat

    def meters_per_pixel(self) -> float:
        """
        Spatial resolution in metres/pixel derived from worldfile coefficients.
        A ≈ degrees_lon/pixel, E ≈ degrees_lat/pixel (both for unrotated maps).
        At latitude F: 1° lat ≈ 111320 m, 1° lon ≈ 111320 * cos(lat) m.
        We use the lat component (E) for the primary resolution estimate,
        averaged with the lon component scaled by cos(lat) for robustness.
        """
        lat_rad = math.radians(abs(self.F))
        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(lat_rad)
        res_y = abs(self.E) * m_per_deg_lat
        res_x = abs(self.A) * m_per_deg_lon
        if res_x > 0 and res_y > 0:
            return (res_x + res_y) / 2.0
        return max(res_x, res_y, 1e-9)

    def is_valid(self) -> bool:
        return self.E != 0 and self.F != 0


@dataclass
class ControlSample:
    lat: float
    lon: float
    is_control: int           # 1 = real control, 0 = negative sample
    source_instance: str
    event_id: int
    event_name: str
    event_date: str
    course_name: str
    course_type: str
    control_code: str
    control_index: int
    n_controls: int
    mapid: int
    coord_method: str         # "worldfile" | "unknown"


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=MAX_RETRIES, backoff_factor=1.0,
                  status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = "AItraceur-ML-DataCollector/1.0 (orienteering research)"
    return session


# ---------------------------------------------------------------------------
# STEP 1 — Discovery: scrape portal for club subdomains
# ---------------------------------------------------------------------------

def discover_instances(session: requests.Session) -> list[str]:
    """
    Scrape https://www.routegadget.co.uk/ to find all club subdomain URLs.
    Returns list of base URLs like 'https://www.slow.routegadget.co.uk/rg2'.
    """
    log.info("Discovering RG2 instances from %s", PORTAL_URL)
    instances = set()

    try:
        r = session.get(PORTAL_URL, timeout=TIMEOUT_S)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = str(a["href"]).strip()
            # Look for subdomain links: https://www.CLUB.routegadget.co.uk/...
            if "routegadget.co.uk" not in href:
                continue
            parsed = urlparse(href)
            host = parsed.netloc  # e.g. www.slow.routegadget.co.uk
            if not host or host == "www.routegadget.co.uk":
                continue
            # Build canonical base URL with /rg2 suffix
            base = f"https://{host}/rg2"
            instances.add(base)

    except Exception as e:
        log.error("Discovery failed: %s", e)

    result = sorted(instances)
    log.info("Discovered %d club instances", len(result))
    return result


# ---------------------------------------------------------------------------
# STEP 2 — Scraping: fetch maps + events + courses per instance
# ---------------------------------------------------------------------------

def rg2_get(session: requests.Session, base_url: str, params: dict) -> Optional[dict]:
    """GET rg2api.php with params. Returns parsed JSON data field or None."""
    url = base_url.rstrip("/") + "/rg2api.php"
    try:
        r = session.get(url, params=params, timeout=TIMEOUT_S)
        r.raise_for_status()
        body = r.json()
        # All RG2 GET responses: {"data": <payload>}
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body
    except Exception as e:
        log.debug("GET %s %s → %s", url, params, e)
        return None


def fetch_maps(session: requests.Session, base_url: str) -> dict[int, Worldfile]:
    """
    GET type=maps → returns all maps for the instance.
    Response: {"data": {"maps": [{mapid, name, georeferenced, A, B, C, D, E, F}], ...}}
    Only maps with georeferenced=true have the worldfile params.
    Returns dict: mapid → Worldfile.
    """
    time.sleep(REQUEST_DELAY_S)
    data = rg2_get(session, base_url, {"type": "maps"})
    if not data:
        return {}

    # Parse map list
    if isinstance(data, dict):
        maps_list = data.get("maps", [])
    elif isinstance(data, list):
        maps_list = data
    else:
        return {}

    worldfiles: dict[int, Worldfile] = {}
    for m in maps_list:
        if not isinstance(m, dict):
            continue
        if not m.get("georeferenced", False):
            continue
        try:
            # Extract scale: RG2 may expose it as 'scale', 'mapscale', or via mapfile name
            scale_raw = m.get("scale") or m.get("mapscale") or 4000
            try:
                scale_val = int(float(str(scale_raw)))
            except (TypeError, ValueError):
                scale_val = 4000

            wf = Worldfile(
                A=float(m["A"]), B=float(m["B"]), C=float(m["C"]),
                D=float(m["D"]), E=float(m["E"]), F=float(m["F"]),
                mapid=int(m["mapid"]),
                name=str(m.get("name", "")),
                mapfile=str(m.get("mapfile", m.get("filename", ""))),
                scale=scale_val,
            )
            if wf.is_valid():
                worldfiles[wf.mapid] = wf
        except (KeyError, TypeError, ValueError):
            continue

    log.info("[%s] %d georeferenced maps", base_url, len(worldfiles))
    return worldfiles


def fetch_events(session: requests.Session, base_url: str) -> list[dict]:
    """
    GET type=events → list of events with id, mapid, name, date.
    Response: {"data": {"events": [...], "API version": "2.2.2"}}
    """
    time.sleep(REQUEST_DELAY_S)
    data = rg2_get(session, base_url, {"type": "events"})
    if not data:
        return []

    if isinstance(data, dict):
        events = data.get("events", [])
    elif isinstance(data, list):
        events = data
    else:
        return []

    return [e for e in events if isinstance(e, dict) and e.get("id")]


def fetch_courses(session: requests.Session, base_url: str, event_id: int) -> list[dict]:
    """
    GET type=event&id={event_id} → courses with xpos/ypos arrays.
    Response: {"data": {"courses": [{courseid, name, codes, xpos, ypos}], ...}}

    xpos[i], ypos[i] = pixel coordinates of control i on the map image.
    Note: ypos is already negated in PHP (y = -1 * raw_y).
    """
    time.sleep(REQUEST_DELAY_S)
    data = rg2_get(session, base_url, {"type": "event", "id": event_id})
    if not data:
        return []

    if isinstance(data, dict):
        courses = data.get("courses", [])
    elif isinstance(data, list):
        courses = data
    else:
        return []

    return [c for c in courses if isinstance(c, dict)]


# ---------------------------------------------------------------------------
# STEP 3 — Transform: pixel (xpos, ypos) → WGS84
# ---------------------------------------------------------------------------

def infer_course_type(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["sprint", "city", "urban", "street", "ville"]):
        return "sprint"
    if any(k in n for k in ["middle", "moyen", "md", "short"]):
        return "middle"
    if any(k in n for k in ["long", "ld", "classic", "chase"]):
        return "long"
    if any(k in n for k in ["score", "rogaine"]):
        return "score"
    return "unknown"


def validate_wgs84(lat: float, lon: float) -> bool:
    return -85 <= lat <= 85 and -180 <= lon <= 180 and not (abs(lat) < 0.01 and abs(lon) < 0.01)


def extract_controls(
    session: requests.Session,
    base_url: str,
    event: dict,
    worldfiles: dict[int, Worldfile],
) -> list[ControlSample]:
    """
    For one event: fetch courses and convert pixel positions to WGS84.
    Returns list of ControlSample (positive examples only).
    """
    event_id = int(event["id"])
    mapid = int(event.get("mapid", 0))
    event_name = str(event.get("name", ""))
    event_date = str(event.get("date", ""))

    wf = worldfiles.get(mapid)
    if not wf:
        return []  # No worldfile for this map → can't convert

    courses = fetch_courses(session, base_url, event_id)
    if not courses:
        return []

    samples: list[ControlSample] = []

    for course in courses:
        course_name = str(course.get("name", course.get("courseid", "")))
        course_type = infer_course_type(course_name)
        xpos = course.get("xpos", [])
        ypos = course.get("ypos", [])
        codes = course.get("codes", [])

        if not isinstance(xpos, list) or not isinstance(ypos, list):
            continue
        if len(xpos) < MIN_CONTROLS_PER_COURSE or len(xpos) != len(ypos):
            continue

        n = len(xpos)
        for i in range(n):
            try:
                x = float(xpos[i])
                y = float(ypos[i])
                lon, lat = wf.pixel_to_wgs84(x, y)

                if not validate_wgs84(lat, lon):
                    continue

                code = str(codes[i]) if i < len(codes) else str(i)

                samples.append(ControlSample(
                    lat=round(lat, 7),
                    lon=round(lon, 7),
                    is_control=1,
                    source_instance=base_url,
                    event_id=event_id,
                    event_name=event_name,
                    event_date=event_date,
                    course_name=course_name,
                    course_type=course_type,
                    control_code=code,
                    control_index=i,
                    n_controls=n,
                    mapid=mapid,
                    coord_method="worldfile",
                ))
            except (TypeError, ValueError, ZeroDivisionError):
                continue

    return samples


# ---------------------------------------------------------------------------
# STEP 4 — Negative sampling
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two WGS84 points."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def map_bbox_from_controls(controls: list[ControlSample]) -> tuple[float, float, float, float]:
    """Bounding box (min_lat, max_lat, min_lon, max_lon) of a set of controls."""
    lats = [c.lat for c in controls]
    lons = [c.lon for c in controls]
    return min(lats), max(lats), min(lons), max(lons)


def generate_negatives(
    positives: list[ControlSample],
    neg_ratio: int = 2,
    min_dist_m: float = NEG_DISTANCE_M,
    max_attempts: int = 50,
) -> list[ControlSample]:
    """
    For each event, generate neg_ratio negative samples per positive.
    Negatives are random points within the map bbox, at least min_dist_m
    from any positive control.
    """
    if not positives:
        return []

    # Group by (source_instance, event_id, course_name)
    groups: dict[tuple, list[ControlSample]] = {}
    for c in positives:
        key = (c.source_instance, c.event_id, c.course_name)
        groups.setdefault(key, []).append(c)

    negatives: list[ControlSample] = []

    for key, group in groups.items():
        min_lat, max_lat, min_lon, max_lon = map_bbox_from_controls(group)
        lat_range = max_lat - min_lat
        lon_range = max_lon - min_lon

        # Pad bbox by 20%
        pad_lat = lat_range * 0.2
        pad_lon = lon_range * 0.2
        b_min_lat = min_lat - pad_lat
        b_max_lat = max_lat + pad_lat
        b_min_lon = min_lon - pad_lon
        b_max_lon = max_lon + pad_lon

        target = len(group) * neg_ratio
        generated = 0
        attempts = 0

        while generated < target and attempts < target * max_attempts:
            attempts += 1
            cand_lat = random.uniform(b_min_lat, b_max_lat)
            cand_lon = random.uniform(b_min_lon, b_max_lon)

            # Check minimum distance from all positives
            too_close = any(
                haversine_m(cand_lat, cand_lon, c.lat, c.lon) < min_dist_m
                for c in group
            )
            if too_close:
                continue

            ref = group[0]
            negatives.append(ControlSample(
                lat=round(cand_lat, 7),
                lon=round(cand_lon, 7),
                is_control=0,
                source_instance=ref.source_instance,
                event_id=ref.event_id,
                event_name=ref.event_name,
                event_date=ref.event_date,
                course_name=ref.course_name,
                course_type=ref.course_type,
                control_code="NEG",
                control_index=-1,
                n_controls=ref.n_controls,
                mapid=ref.mapid,
                coord_method="random_negative",
            ))
            generated += 1

    return negatives


# ---------------------------------------------------------------------------
# STEP 5 — Dataset Generator: image patches from RG2 map images
# ---------------------------------------------------------------------------

class DatasetGenerator:
    """
    Downloads map images from RG2 /kartat/ directory and crops fixed-FOV
    patches centered on control positions for CNN/XGBoost training.

    Key design choices:
    - FOV fixed at FOV_METERS × FOV_METERS (real-world extent), regardless of
      map scale. Each output tensor always covers the same ground area.
    - Spatial resolution R (m/px) derived from worldfile coefficients → used
      to compute how many pixels = FOV_METERS / 2 on each side.
    - Hard-negative filtering: rejects water (blue), OOB (olive), margins
      (near-white/black borders) to avoid trivial uninformative negatives.
    - Output: 256×256 PNG patches (Lanczos resize from dynamic crop region).
    """

    FOV_METERS = 128       # real-world side length each patch covers (metres)
    PATCH_PX = 256         # output tensor side (pixels)
    NEG_MIN_M = 60.0       # minimum metres from any positive for negatives
    NEG_RATIO = 2          # negative patches per positive
    MIN_VALID_PX = 32      # minimum crop dimension before resize (sanity check)

    # IOF ISOM approximate RGB ranges for exclusion during negative sampling
    _WATER_B_MIN = 150     # blue channel threshold for water detection
    _MARGIN_BRIGHT = 248   # near-white: outside map scan boundary
    _BORDER_DARK = 25      # near-black: map edge / scan artifact

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        worldfiles: dict,
    ):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.worldfiles = worldfiles
        self._image_cache: dict[int, Optional["Image.Image"]] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, events: list[dict]) -> dict:
        """
        For each event, download map image, crop positive + negative patches,
        append rows to metadata.csv. Returns stats dict.
        """
        if not PIL_AVAILABLE:
            log.error("Pillow not installed. Run: pip install pillow")
            return {"positives": 0, "negatives": 0, "error": "pillow_missing"}

        pos_dir = DATASET_DIR / "train" / "pos"
        neg_dir = DATASET_DIR / "train" / "neg"
        pos_dir.mkdir(parents=True, exist_ok=True)
        neg_dir.mkdir(parents=True, exist_ok=True)

        meta_path = DATASET_DIR / "metadata.csv"
        meta_exists = meta_path.exists()
        fieldnames = [
            "img_path", "label", "fov_m", "mpp", "course_type",
            "n_controls", "event_id", "event_name", "source_instance",
            "control_index", "mapid", "lat", "lon",
        ]

        stats = {"positives": 0, "negatives": 0, "maps_ok": 0, "maps_fail": 0}

        with open(meta_path, "a", newline="", encoding="utf-8") as meta_f:
            writer = csv.DictWriter(meta_f, fieldnames=fieldnames)
            if not meta_exists:
                writer.writeheader()

            for ev in events:
                event_id = int(ev.get("id", 0))
                mapid = int(ev.get("mapid", 0))
                event_name = str(ev.get("name", ""))

                wf = self.worldfiles.get(mapid)
                if not wf:
                    continue

                img = self._get_map_image(wf)
                if img is None:
                    stats["maps_fail"] += 1
                    continue
                stats["maps_ok"] += 1

                mpp = wf.meters_per_pixel()
                crop_half_px = max(
                    self.MIN_VALID_PX,
                    int((self.FOV_METERS / 2.0) / mpp),
                )

                courses = fetch_courses(self.session, self.base_url, event_id)
                for course in courses:
                    course_name = str(course.get("name", course.get("courseid", "")))
                    course_type = infer_course_type(course_name)
                    xpos = course.get("xpos", [])
                    ypos = course.get("ypos", [])

                    if not (isinstance(xpos, list) and isinstance(ypos, list)):
                        continue
                    if len(xpos) < MIN_CONTROLS_PER_COURSE:
                        continue

                    n = len(xpos)
                    controls_px: list[tuple[float, float]] = []

                    for i in range(n):
                        try:
                            px = float(xpos[i])
                            # RG2 ypos may be stored as raw_y (positive) or -raw_y (negated).
                            # abs() handles both conventions: raw pixel y is always positive.
                            py = abs(float(ypos[i]))
                        except (TypeError, ValueError):
                            continue

                        patch = self._crop_fixed_fov(img, px, py, crop_half_px)
                        if patch is None:
                            continue

                        fname = f"{event_id}_{mapid}_{i}.png"
                        out_path = pos_dir / fname
                        patch.save(out_path, format="PNG")

                        p_lon, p_lat = wf.pixel_to_wgs84(px, py)
                        writer.writerow({
                            "img_path": f"train/pos/{fname}",
                            "label": 1,
                            "fov_m": self.FOV_METERS,
                            "mpp": round(mpp, 4),
                            "course_type": course_type,
                            "n_controls": n,
                            "event_id": event_id,
                            "event_name": event_name,
                            "source_instance": self.base_url,
                            "control_index": i,
                            "mapid": mapid,
                            "lat": round(p_lat, 7),
                            "lon": round(p_lon, 7),
                        })
                        controls_px.append((px, py))
                        stats["positives"] += 1

                    # Generate hard negatives in pixel space
                    neg_patches = self._generate_negatives(
                        img, controls_px, len(controls_px) * self.NEG_RATIO, mpp, crop_half_px
                    )
                    for j, (neg_patch, npx, npy) in enumerate(neg_patches):
                        fname = f"{event_id}_{mapid}_neg{j}.png"
                        out_path = neg_dir / fname
                        neg_patch.save(out_path, format="PNG")

                        n_lon, n_lat = wf.pixel_to_wgs84(npx, npy)
                        writer.writerow({
                            "img_path": f"train/neg/{fname}",
                            "label": 0,
                            "fov_m": self.FOV_METERS,
                            "mpp": round(mpp, 4),
                            "course_type": course_type,
                            "n_controls": n,
                            "event_id": event_id,
                            "event_name": event_name,
                            "source_instance": self.base_url,
                            "control_index": -1,
                            "mapid": mapid,
                            "lat": round(n_lat, 7),
                            "lon": round(n_lon, 7),
                        })
                        stats["negatives"] += 1

        log.info("[DatasetGenerator] %s: +%d pos / +%d neg | maps ok=%d fail=%d",
                 self.base_url, stats["positives"], stats["negatives"],
                 stats["maps_ok"], stats["maps_fail"])
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _kartat_base(self) -> str:
        """Compute the web-root URL (strip /rg2 suffix)."""
        url = self.base_url
        if url.endswith("/rg2"):
            url = url[:-4]
        return url

    def _get_map_image(self, wf) -> Optional["Image.Image"]:
        """Download and cache map image from /kartat/{mapfile} or /kartat/{mapid}.{ext}."""
        if wf.mapid in self._image_cache:
            return self._image_cache[wf.mapid]

        kartat = self._kartat_base() + "/kartat/"
        # Build candidate URLs: prefer explicit mapfile, then mapid-based fallbacks
        candidates: list[str] = []
        if wf.mapfile:
            candidates.append(kartat + wf.mapfile)
        for ext in ("jpg", "jpeg", "png", "gif"):
            candidates.append(f"{kartat}{wf.mapid}.{ext}")

        for url in candidates:
            try:
                time.sleep(REQUEST_DELAY_S)
                r = self.session.get(url, timeout=30)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                log.info("Map image mapid=%d (%s): %dx%d px, %.2f m/px",
                         wf.mapid, url.split("/")[-1], img.width, img.height,
                         wf.meters_per_pixel())
                self._image_cache[wf.mapid] = img
                return img
            except Exception as e:
                log.debug("Failed to download map image %s: %s", url, e)

        log.warning("No map image found for mapid=%d (tried %d URLs)", wf.mapid, len(candidates))
        self._image_cache[wf.mapid] = None
        return None

    def _crop_fixed_fov(
        self, img: "Image.Image", px: float, py: float, half_px: int
    ) -> Optional["Image.Image"]:
        """
        Crop a square region of ±half_px pixels around (px, py), then resize
        to PATCH_PX×PATCH_PX. Returns None if the crop is too close to the
        image boundary to be usable.
        """
        x0 = int(px) - half_px
        y0 = int(py) - half_px
        x1 = int(px) + half_px
        y1 = int(py) + half_px

        # Reject if more than 25% of the crop falls outside the image
        clip_x0 = max(0, x0)
        clip_y0 = max(0, y0)
        clip_x1 = min(img.width, x1)
        clip_y1 = min(img.height, y1)
        full_area = (x1 - x0) * (y1 - y0)
        clip_area = max(0, clip_x1 - clip_x0) * max(0, clip_y1 - clip_y0)
        if full_area <= 0 or clip_area < full_area * 0.75:
            return None

        crop = img.crop((clip_x0, clip_y0, clip_x1, clip_y1))
        if crop.width < self.MIN_VALID_PX or crop.height < self.MIN_VALID_PX:
            return None

        return crop.resize((self.PATCH_PX, self.PATCH_PX), Image.LANCZOS)

    def _is_valid_negative(self, img: "Image.Image", px: float, py: float) -> bool:
        """
        Color-based hard-negative filter. Checks the central pixel to exclude:
        - Near-white margin (outside scanned map area)
        - Water (blue dominant)
        - Out-of-bounds vegetation (olive green)
        - Pure black border/scan artifacts
        """
        xi, yi = int(px), int(py)
        if not (0 <= xi < img.width and 0 <= yi < img.height):
            return False

        r, g, b = img.getpixel((xi, yi))

        # Margin (nearly white = outside scan area)
        if r >= self._MARGIN_BRIGHT and g >= self._MARGIN_BRIGHT and b >= self._MARGIN_BRIGHT:
            return False

        # Black border / scan artifact
        if r <= self._BORDER_DARK and g <= self._BORDER_DARK and b <= self._BORDER_DARK:
            return False

        # Water: blue clearly dominant
        if b >= self._WATER_B_MIN and b > r * 1.5 and b > g * 1.2:
            return False

        # OOB / forbidden olive-green: green dominates, muted, not too bright
        if g > r and g > b and 80 <= g <= 160 and r < 130 and b < 100:
            return False

        return True

    def _generate_negatives(
        self,
        img: "Image.Image",
        controls_px: list[tuple[float, float]],
        target: int,
        mpp: float,
        crop_half_px: int,
        max_attempts: int = 100,
    ) -> list[tuple["Image.Image", float, float]]:
        """
        Generate hard-negative patches in pixel space.
        - Random (px, py) within image bounds with safe margin
        - Must be at least NEG_MIN_M / mpp pixels from every real control
        - Must pass color filter
        Returns list of (patch_image, px, py).
        """
        neg_min_px = self.NEG_MIN_M / max(mpp, 1e-9)
        margin = crop_half_px + 4
        results: list[tuple["Image.Image", float, float]] = []
        attempts = 0

        while len(results) < target and attempts < target * max_attempts:
            attempts += 1
            px = random.uniform(margin, img.width - margin)
            py = random.uniform(margin, img.height - margin)

            # Distance check from all real controls
            too_close = any(
                math.hypot(px - cx, py - cy) < neg_min_px
                for cx, cy in controls_px
            )
            if too_close:
                continue

            if not self._is_valid_negative(img, px, py):
                continue

            patch = self._crop_fixed_fov(img, px, py, crop_half_px)
            if patch is not None:
                results.append((patch, px, py))

        return results


# ---------------------------------------------------------------------------
# Output — GeoJSON
# ---------------------------------------------------------------------------

def to_geojson(samples: list[ControlSample]) -> dict:
    features = []
    for s in samples:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s.lon, s.lat],
            },
            "properties": {
                "is_control": s.is_control,
                "source_instance": s.source_instance,
                "event_id": s.event_id,
                "event_name": s.event_name,
                "event_date": s.event_date,
                "course_name": s.course_name,
                "course_type": s.course_type,
                "control_code": s.control_code,
                "control_index": s.control_index,
                "n_controls": s.n_controls,
                "mapid": s.mapid,
                "coord_method": s.coord_method,
            },
        })

    positives = sum(1 for s in samples if s.is_control == 1)
    negatives = sum(1 for s in samples if s.is_control == 0)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_samples": len(features),
            "positives": positives,
            "negatives": negatives,
        },
    }


def save_output(samples: list[ControlSample], log_data: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    geojson = to_geojson(samples)
    with open(OUTPUT_CONTROLS, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    log.info("Saved %d samples (%d pos / %d neg) → %s",
             len(samples),
             geojson["metadata"]["positives"],
             geojson["metadata"]["negatives"],
             OUTPUT_CONTROLS)

    with open(OUTPUT_LOG, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    log.info("Log → %s", OUTPUT_LOG)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def scrape_instance(
    session: requests.Session,
    base_url: str,
    max_valid_events: Optional[int],
    neg_ratio: int,
    generate_dataset: bool = False,
) -> tuple[list[ControlSample], dict]:
    """
    Full pipeline for one RG2 instance.
    Returns (samples_list, dataset_stats).
    - samples_list: positive + negative ControlSamples (for GeoJSON output)
    - dataset_stats: patch counts from DatasetGenerator (if generate_dataset=True)
    """
    base_url = base_url.rstrip("/")
    dataset_stats: dict = {}

    # 1. Fetch worldfiles
    worldfiles = fetch_maps(session, base_url)
    if not worldfiles:
        log.info("[%s] No georeferenced maps → skip", base_url)
        return [], dataset_stats

    # 2. Fetch events
    events = fetch_events(session, base_url)
    if not events:
        log.warning("[%s] No events", base_url)
        return [], dataset_stats

    # 3. Extract controls per event — only georeferenced events count toward the limit
    all_positives: list[ControlSample] = []
    events_with_courses = 0
    valid_events_processed = 0

    for ev in events:
        mapid = int(ev.get("mapid", 0))
        if mapid not in worldfiles:
            log.debug("[%s] Event %s skipped: map %d not georeferenced",
                      base_url, ev.get("id"), mapid)
            continue

        if max_valid_events and valid_events_processed >= max_valid_events:
            break
        valid_events_processed += 1

        pos = extract_controls(session, base_url, ev, worldfiles)
        if pos:
            all_positives.extend(pos)
            events_with_courses += 1

    log.info("[%s] %d/%d georef events with course data → %d controls",
             base_url, events_with_courses, valid_events_processed, len(all_positives))

    # 4. Image patch dataset generation (Direct Raster pipeline)
    if generate_dataset:
        gen = DatasetGenerator(session, base_url, worldfiles)
        # Only process georeferenced events (respects max_valid_events limit)
        geo_events = []
        n = 0
        for ev in events:
            if worldfiles.get(int(ev.get("mapid", 0))) is None:
                continue
            if max_valid_events and n >= max_valid_events:
                break
            geo_events.append(ev)
            n += 1
        dataset_stats = gen.run(geo_events)

    if not all_positives:
        return [], dataset_stats

    # 5. Generate WGS84 negative samples
    negatives = generate_negatives(all_positives, neg_ratio=neg_ratio)

    return all_positives + negatives, dataset_stats


def probe_instance(session: requests.Session, base_url: str) -> bool:
    """Quick probe: check events API returns data."""
    data = rg2_get(session, base_url, {"type": "events"})
    if not data:
        return False
    if isinstance(data, dict):
        events = data.get("events", [])
    elif isinstance(data, list):
        events = data
    else:
        return False
    return isinstance(events, list) and len(events) > 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RG2 → ML dataset pipeline")
    parser.add_argument("--instance", help="Single RG2 instance base URL")
    parser.add_argument("--discover-only", action="store_true",
                        help="Print discovered instances and exit")
    parser.add_argument("--generate-dataset", action="store_true",
                        help="Download map images + crop 256x256 patches (CNN dataset)")
    parser.add_argument("--max-valid-events", type=int, default=None,
                        help="Stop after N georeferenced events (skips non-georef events)")
    parser.add_argument("--neg-ratio", type=int, default=2,
                        help="Negative samples per positive (default: 2)")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    global REQUEST_DELAY_S
    REQUEST_DELAY_S = args.delay

    if args.generate_dataset and not PIL_AVAILABLE:
        print("ERROR: --generate-dataset requires Pillow. Install with: pip install pillow")
        return

    session = make_session()

    # ---- Determine instance list ----
    if args.instance:
        instances = [args.instance]
    else:
        instances = discover_instances(session)

    if args.discover_only:
        for url in instances:
            print(url)
        return

    if not instances:
        log.error("No instances found. Use --instance <url> to specify one.")
        return

    # ---- Scrape each instance ----
    all_samples: list[ControlSample] = []
    total_patches_pos = 0
    total_patches_neg = 0
    log_data: dict = {
        "started_at": datetime.utcnow().isoformat() + "Z",
        "generate_dataset": args.generate_dataset,
        "instances": {},
    }

    for url in instances:
        log.info("=== %s ===", url)

        if not probe_instance(session, url):
            log.warning("[%s] Unreachable", url)
            log_data["instances"][url] = {"status": "unreachable", "samples": 0}
            continue

        try:
            samples, ds_stats = scrape_instance(
                session, url, args.max_valid_events, args.neg_ratio, args.generate_dataset
            )
            all_samples.extend(samples)
            pos = sum(1 for s in samples if s.is_control == 1)
            neg = sum(1 for s in samples if s.is_control == 0)
            total_patches_pos += ds_stats.get("positives", 0)
            total_patches_neg += ds_stats.get("negatives", 0)
            log_data["instances"][url] = {
                "status": "ok",
                "positives": pos,
                "negatives": neg,
                "samples": pos + neg,
                "patches_pos": ds_stats.get("positives", 0),
                "patches_neg": ds_stats.get("negatives", 0),
            }
        except Exception as e:
            log.error("[%s] Error: %s", url, e)
            log_data["instances"][url] = {"status": "error", "error": str(e), "samples": 0}

    log_data["finished_at"] = datetime.utcnow().isoformat() + "Z"
    log_data["total_samples"] = len(all_samples)

    if all_samples:
        save_output(all_samples, log_data)
    else:
        log.warning("No samples extracted.")
        log.warning("Reason: RG2 courses data is only present when organizers")
        log.warning("explicitly uploaded course IOF XML via the RG2 manager.")
        log.warning("Most clubs use RG2 for GPS route recording only.")

    # ---- Summary ----
    pos_total = sum(1 for s in all_samples if s.is_control == 1)
    neg_total = sum(1 for s in all_samples if s.is_control == 0)
    ok = sum(1 for v in log_data["instances"].values() if v["status"] == "ok")
    has_data = sum(1 for v in log_data["instances"].values()
                   if v.get("positives", 0) > 0)

    print(f"\n{'='*55}")
    print(f"Instances probed    : {len(log_data['instances'])}")
    print(f"Instances reachable : {ok}")
    print(f"Instances with data : {has_data}")
    print(f"GeoJSON positives   : {pos_total}  (real controls, WGS84)")
    print(f"GeoJSON negatives   : {neg_total}  (non-control points, WGS84)")
    if all_samples:
        print(f"GeoJSON output      : {OUTPUT_CONTROLS}")
    if args.generate_dataset:
        print(f"Image patches pos   : {total_patches_pos}  (label=1)")
        print(f"Image patches neg   : {total_patches_neg}  (label=0)")
        print(f"Patches output      : {DATASET_DIR / 'train'}/")
        print(f"Metadata CSV        : {DATASET_DIR / 'metadata.csv'}")


if __name__ == "__main__":
    main()
