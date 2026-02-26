# =============================================
# Service de transformation de coordonnées OCAD
# Convertit les coordonnées OCAD vers WGS84
# =============================================

import math
from typing import Optional, Tuple, Dict, Any
from pyproj import Transformer, CRS


class OCADCoordinateTransformer:
    """
    Transforme les coordonnées OCAD vers WGS84 (EPSG:4326).
    """

    # Dictionary of common EPSG projections for OCAD
    KNOWN_PROJECTIONS = {
        2154: "EPSG:2154",  # Lambert-93 (France)
        2152: "EPSG:2152",  # Lambert-93 étendu
        4171: "EPSG:4171",  # RGF93
        4269: "EPSG:4269",  # NTF
        3857: "EPSG:3857",  # Web Mercator
        4326: "EPSG:4326",  # WGS84
    }

    # UTM zones
    UTM_NORTH_START = 32601
    UTM_NORTH_END = 32660
    UTM_SOUTH_START = 32701
    UTM_SOUTH_END = 32760

    def __init__(self, source_epsg: int):
        """
        Initialize transformer with source EPSG code.

        Args:
            source_epsg: EPSG code of the source coordinate system
        """
        self.source_epsg = source_epsg
        self.transformer: Optional[Transformer] = None

        self._create_transformer()

    def _create_transformer(self):
        """Create pyproj transformer."""
        try:
            # Try to get from known projections first
            source_crs = self.KNOWN_PROJECTIONS.get(self.source_epsg)

            if not source_crs:
                # Try UTM zones
                if self.UTM_NORTH_START <= self.source_epsg <= self.UTM_NORTH_END:
                    zone = self.source_epsg - self.UTM_NORTH_START + 1
                    source_crs = f"EPSG:326{zone:02d}"
                elif self.UTM_SOUTH_START <= self.source_epsg <= self.UTM_SOUTH_END:
                    zone = self.source_epsg - self.UTM_SOUTH_START + 1
                    source_crs = f"EPSG:327{zone:02d}"
                else:
                    # Try direct EPSG
                    source_crs = f"EPSG:{self.source_epsg}"

            if source_crs:
                self.transformer = Transformer.from_crs(
                    source_crs,
                    "EPSG:4326",
                    always_xy=True,  # Use (lon, lat) order
                )
                print(f"[DEBUG] Created transformer: {source_crs} -> EPSG:4326")
            else:
                print(f"[DEBUG] Unknown EPSG code: {self.source_epsg}")

        except Exception as e:
            print(f"[DEBUG] Error creating transformer: {e}")
            self.transformer = None

    def transform_point(self, x: float, y: float) -> Tuple[float, float]:
        """
        Transform a single point from source to WGS84.

        Args:
            x: X coordinate (easting)
            y: Y coordinate (northing)

        Returns:
            Tuple of (longitude, latitude) in WGS84
        """
        if not self.transformer:
            # Fallback: assume already WGS84
            return (x, y)

        try:
            lon, lat = self.transformer.transform(x, y)
            return (lon, lat)
        except Exception as e:
            print(f"[DEBUG] Transform error: {e}")
            return (x, y)

    def transform_bounds(
        self, min_x: float, min_y: float, max_x: float, max_y: float
    ) -> Dict[str, Any]:
        """
        Transform bounding box corners to WGS84.

        Returns:
            Dictionary with southWest, northEast, and corners
        """
        # Transform all 4 corners
        corners = [
            self.transform_point(min_x, min_y),  # bottom-left
            self.transform_point(max_x, min_y),  # bottom-right
            self.transform_point(min_x, max_y),  # top-left
            self.transform_point(max_x, max_y),  # top-right
        ]

        lats = [c[1] for c in corners]
        lons = [c[0] for c in corners]

        return {
            "southWest": [min(lats), min(lons)],
            "northEast": [max(lats), max(lons)],
            "corners": {
                "bottomLeft": [corners[0][1], corners[0][0]],
                "bottomRight": [corners[1][1], corners[1][0]],
                "topLeft": [corners[2][1], corners[2][0]],
                "topRight": [corners[3][1], corners[3][0]],
            },
        }


def detect_epsg_from_crs(crs_string: str) -> Optional[int]:
    """
    Detect EPSG code from CRS string.

    Args:
        crs_string: CRS string from OCAD file (e.g., "Lambert 93", "EPSG:2154")

    Returns:
        EPSG code if detected, None otherwise
    """
    if not crs_string:
        return None

    crs_lower = crs_string.lower()

    # Check for known projections
    if "lambert 93" in crs_lower or "lambert-93" in crs_lower:
        return 2154
    if "lambert 92" in crs_lower or "lambert-92" in crs_lower:
        return 2152
    if "lambert ii" in crs_lower:
        return 27572  # Lambert II zone
    if "lambert" in crs_lower and "72" in crs_lower:
        return 27572
    if "lambert" in crs_lower and "84" in crs_lower:
        return 27584
    if "wgs84" in crs_lower or "4326" in crs_lower:
        return 4326
    if "mercator" in crs_lower or "3857" in crs_lower:
        return 3857
    if "utm" in crs_lower:
        # Try to extract zone - handle multiple formats:
        # "UTM Zone 31N", "UTM 31", "zone 31"
        import re

        # Try "zone XX" pattern first
        match = re.search(r"zone\s*(\d+)", crs_lower)
        if not match:
            # Try just number after UTM
            match = re.search(r"utm\s*(\d+)", crs_lower)

        if match:
            zone = int(match.group(1))
            if "south" in crs_lower:
                return 32700 + zone
            else:
                return 32600 + zone

    # Try to extract EPSG code directly
    import re

    match = re.search(r"epsg[:\s]*(\d+)", crs_lower)
    if match:
        return int(match.group(1))

    return None


def create_transformer_from_crs(crs_string: str) -> Optional[OCADCoordinateTransformer]:
    """
    Create transformer from CRS string.

    Args:
        crs_string: CRS string from OCAD file

    Returns:
        OCADCoordinateTransformer instance or None
    """
    epsg = detect_epsg_from_crs(crs_string)

    if epsg:
        return OCADCoordinateTransformer(epsg)

    return None


# =============================================
# Helper function for OCAD parser
# =============================================
def convert_ocad_coords_to_wgs84(
    ocad_bounds: Dict[str, float], crs_string: str
) -> Optional[Dict[str, Any]]:
    """
    Convert OCAD bounds to WGS84 coordinates.

    Args:
        ocad_bounds: Dictionary with min_x, max_x, min_y, max_y
        crs_string: CRS string from OCAD file

    Returns:
        Dictionary with WGS84 bounds and corners, or None if failed
    """
    if not ocad_bounds or not crs_string:
        return None

    # Create transformer
    transformer = create_transformer_from_crs(crs_string)

    if not transformer or not transformer.transformer:
        print(f"[DEBUG] Could not create transformer for CRS: {crs_string}")
        return None

    # Transform bounds
    min_x = ocad_bounds.get("min_x", 0)
    max_x = ocad_bounds.get("max_x", 0)
    min_y = ocad_bounds.get("min_y", 0)
    max_y = ocad_bounds.get("max_y", 0)

    if not all([min_x, max_x, min_y, max_y]):
        return None

    return transformer.transform_bounds(min_x, min_y, max_x, max_y)
