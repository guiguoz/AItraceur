# =============================================
# Parser OCAD - Lecture de fichiers .ocd
# Sprint 1: Upload OCAD & Affichage Carte
# =============================================

import struct
import io
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path


# =============================================
# Exceptions personnalisées
# =============================================
class OCADParseError(Exception):
    """Erreur lors du parsing d'un fichier OCAD."""

    pass


class OCADVersionError(OCADParseError):
    """Version OCAD non supportée."""

    pass


# =============================================
# Structures de données
# =============================================
@dataclass
class OCADControl:
    """Un poste de contrôle."""

    number: int
    x: float  # Coordonnée X (en mètres)
    y: float  # Coordonnée Y (en mètres)
    code: str
    control_type: int = 0  # 0=control, 1=start, 2=finish
    description: Optional[str] = None


@dataclass
class OCADCourse:
    """Un circuit complet."""

    name: str
    category: Optional[str] = None
    controls: List[OCADControl] = field(default_factory=list)
    length_meters: Optional[float] = None
    climb_meters: Optional[float] = None
    winning_time_minutes: Optional[float] = None
    technical_level: Optional[int] = None
    number_of_controls: Optional[int] = None


@dataclass
class OCADData:
    """Données complètes extraites d'un fichier OCAD."""

    filename: str
    version: int
    file_type: int = 0
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    crs: Optional[str] = None
    scale: int = 10000
    courses: List[OCADCourse] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================
# Parser OCAD - Approche robuste par scan
# =============================================
class OCADParser:
    """
    Parser pour fichiers OCAD (.ocd)
    Utilise une approche par scan pour trouver les postes.
    """

    OCAD_MAGIC = 0x0CAD
    OCAD_VERSIONS = {9: "OCAD 9", 10: "OCAD 10", 11: "OCAD 11", 12: "OCAD 12"}

    def __init__(self):
        self.data: Optional[OCADData] = None

    def parse(self, file_path: Path) -> OCADData:
        with open(file_path, "rb") as f:
            return self._parse_stream(f, file_path.name)

    def parse_bytes(self, data: bytes, filename: str) -> OCADData:
        f = io.BytesIO(data)
        return self._parse_stream(f, filename)

    def _parse_stream(self, stream: io.BytesIO, filename: str) -> OCADData:
        # Get file size
        stream.seek(0, 2)
        file_size = stream.tell()
        stream.seek(0)

        # Read entire file as bytes
        file_data = stream.read()

        # Detect endianness
        endian = self._detect_endianness(file_data)

        # Read header
        header = self._read_header(file_data, endian)

        version = header.get("version", 12)
        if version not in self.OCAD_VERSIONS:
            self.OCAD_VERSIONS[version] = f"OCAD {version}"

        # Create data object
        self.data = OCADData(
            filename=filename,
            version=version,
            file_type=header.get("file_type", 0),
            crs=header.get("crs"),  # Use CRS from header if found
            scale=header.get("scale", 10000),
            min_x=header.get("min_x", 0),
            min_y=header.get("min_y", 0),
            max_x=header.get("max_x", 0),
            max_y=header.get("max_y", 0),
        )

        # Store header info in metadata for debugging
        self.data.metadata["header"] = header

        # Heuristic: if bounds look like Lambert-93 (coordinates in meters > 100000)
        # but CRS wasn't found, assume it's likely Lambert-93
        if not self.data.crs:
            if (
                self.data.min_x > 100000
                and self.data.max_x < 1500000
                and self.data.min_y > 5000000
                and self.data.max_y < 7500000
            ):
                # Looks like Lambert-93
                self.data.crs = "Lambert 93 (EPSG:2154) - auto-detected"
                print(
                    f"[DEBUG] Auto-detected Lambert-93 from bounds: {self.data.min_x}-{self.data.max_x}, {self.data.min_y}-{self.data.max_y}"
                )
            elif (
                self.data.min_x > -1000000
                and self.data.max_x < 1500000
                and self.data.min_y > 5000000
                and self.data.max_y < 8000000
            ):
                # Looks like Lambert-93 étendu
                self.data.crs = "Lambert-93 étendu (EPSG:2152) - auto-detected"
                print(f"[DEBUG] Auto-detected Lambert-93 étendu from bounds")
            elif (
                self.data.min_x > -2000000
                and self.data.max_x < 2000000
                and self.data.min_y > 0
                and self.data.max_y < 10000000
            ):
                # Looks like UTM
                self.data.crs = "UTM - auto-detected"
                print(f"[DEBUG] Auto-detected UTM from bounds")

        print(f"[DEBUG] OCAD CRS set to: {self.data.crs}")
        print(
            f"[DEBUG] OCAD bounds from header: min_x={self.data.min_x}, max_x={self.data.max_x}, min_y={self.data.min_y}, max_y={self.data.max_y}"
        )

        # Scan for control symbols and their coordinates
        controls = self._scan_for_controls(file_data, endian, header)

        if controls:
            self.data.metadata["raw_controls"] = len(controls)
            self._organize_controls(controls)

            # RECALCULATE bounds from actual control coordinates!
            # This is more reliable than header bounds
            control_x = [c.x for c in controls]
            control_y = [c.y for c in controls]

            if control_x and control_y:
                self.data.min_x = min(control_x)
                self.data.max_x = max(control_x)
                self.data.min_y = min(control_y)
                self.data.max_y = max(control_y)

                print(
                    f"[DEBUG] Recalculated bounds from controls: min_x={self.data.min_x}, max_x={self.data.max_x}, min_y={self.data.min_y}, max_y={self.data.max_y}"
                )

                # Auto-detect CRS based on control coordinates
                if not self.data.crs:
                    # Check coordinate ranges to determine CRS
                    avg_x = (self.data.min_x + self.data.max_x) / 2
                    avg_y = (self.data.min_y + self.data.max_y) / 2

                    print(f"[DEBUG] Average coordinates: x={avg_x}, y={avg_y}")

                    # UTM coordinates are typically in millions
                    # Check if coordinates look like UTM (millions)
                    if avg_x > 1000000 and avg_y > 1000000:
                        # Could be UTM - try to determine zone
                        # UTM zone 31N: 0°E to 6°E -> ~166000 to ~833000
                        # France is mostly in zones 30N, 31N, 32N
                        zone = int((avg_x - 166000) / 666000) + 30
                        zone = max(28, min(38, zone))  # Clamp to valid range
                        self.data.crs = f"UTM Zone {zone}N (EPSG:326{zone:02d}) - auto-detected from controls"
                        print(f"[DEBUG] Detected UTM zone: {zone}")

                    # Check for Lambert-93 (France)
                    # Lambert-93: X ~ 700000-1200000, Y ~ 6000000-7200000
                    elif 600000 < avg_x < 1300000 and 6000000 < avg_y < 7500000:
                        self.data.crs = (
                            "Lambert-93 (EPSG:2154) - auto-detected from controls"
                        )

                    # Check for local coordinates - these need external georef
                    elif avg_x < 100000 or avg_y < 100000:
                        self.data.crs = "Local coordinates - georeferencing required"
                        print(
                            f"[DEBUG] Coordinates appear to be local/paper - file needs georeferencing"
                        )

                    # Otherwise try generic UTM detection
                    else:
                        self.data.crs = (
                            "UTM (EPSG:automatic) - auto-detected from controls"
                        )

                    print(f"[DEBUG] CRS auto-detected: {self.data.crs}")
        else:
            # Fallback: create demo circuit
            self.data.courses.append(
                OCADCourse(
                    name="Circuit démo",
                    category="Demo",
                    controls=[
                        OCADControl(number=i, x=i * 100, y=i * 50, code="201.1")
                        for i in range(1, 11)
                    ],
                )
            )
            self.data.metadata["parsing_note"] = (
                "Circuitmo créé (parser dé n'a pas trouvé les postes)"
            )

        return self.data

    def _detect_endianness(self, data: bytes) -> str:
        """Detect if file is little-endian or big-endian."""
        if len(data) < 4:
            return "<"

        # Check magic at position 0
        magic_le = struct.unpack("<h", data[0:2])[0]
        magic_be = struct.unpack(">h", data[0:2])[0]

        if magic_le == self.OCAD_MAGIC:
            return "<"
        elif magic_be == self.OCAD_MAGIC:
            return ">"
        return "<"

    def _read_header(self, data: bytes, endian: str) -> Dict[str, Any]:
        """Read OCAD header."""
        header = {}

        if len(data) < 64:
            return header

        try:
            # Version at offset 4
            header["version"] = struct.unpack(f"{endian}h", data[4:6])[0]

            # File type at offset 2
            header["file_type"] = struct.unpack(f"{endian}b", data[2:3])[0]

            # Try to read bounds from offset 256 (common location)
            if len(data) >= 288:
                bounds_data = data[256:288]
                if len(bounds_data) == 32:
                    min_x, min_y, max_x, max_y = struct.unpack(
                        f"{endian}dddd", bounds_data
                    )
                    # Convert from 0.01mm to meters
                    header["min_x"] = min_x / 100000.0
                    header["min_y"] = min_y / 100000.0
                    header["max_x"] = max_x / 100000.0
                    header["max_y"] = max_y / 100000.0

            # Try scale at offset 224
            if len(data) >= 228:
                scale_data = data[224:228]
                if len(scale_data) == 4:
                    scale = struct.unpack(f"{endian}I", scale_data)[0]
                    if 1000 <= scale <= 100000:
                        header["scale"] = scale

            # Try to find CRS information
            # OCAD stores CRS info in various places depending on version
            # Check for common CRS strings in the file
            crs_strings = [
                b"Lambert 93",
                b"Lambert-93",
                b"EPSG:2154",
                b"EPSG:4326",
                b"Lambert 92",
                b"Lambert-92",
                b"WGS84",
                b"RGF93",
                b"UTM",
            ]

            data_str = data[:10000].decode("latin-1", errors="ignore")
            for crs_str in crs_strings:
                if crs_str.decode("latin-1") in data_str:
                    header["crs"] = crs_str.decode("latin-1")
                    print(f"[DEBUG] Found CRS in file: {header['crs']}")
                    break

            # Also check for grid parameters (Easting/Northing at offset ~296)
            # This tells OCAD where the paper coordinates are in real-world coordinates
            if len(data) >= 320:
                # Try multiple offsets for grid info
                for grid_offset in [296, 304, 312, 320]:
                    if len(data) >= grid_offset + 16:
                        grid_data = data[grid_offset : grid_offset + 16]
                        try:
                            easting, northing = struct.unpack(f"{endian}dd", grid_data)
                            # Valid easting/northing should be large numbers (hundreds of thousands)
                            if easting > 100000 or northing > 100000:
                                header["easting"] = easting
                                header["northing"] = northing
                                print(
                                    f"[DEBUG] Found grid origin at offset {grid_offset}: easting={easting}, northing={northing}"
                                )
                                break
                            elif abs(easting) > 1 and abs(northing) > 1:
                                # Could still be valid but small - show for debugging
                                print(
                                    f"[DEBUG] Found small grid values at offset {grid_offset}: easting={easting}, northing={northing}"
                                )
                        except:
                            pass

                # Also try reading at offset 328 (might have scale factor too)
                if len(data) >= 344:
                    try:
                        real_x0, real_y0, scale_num, scale_denom = struct.unpack(
                            f"{endian}ddii", data[328:344]
                        )
                        if real_x0 > 100000 or real_y0 > 100000:
                            header["real_x0"] = real_x0
                            header["real_y0"] = real_y0
                            header["scale_num"] = scale_num
                            header["scale_denom"] = scale_denom
                            print(
                                f"[DEBUG] Found real-world origin: ({real_x0}, {real_y0}), scale={scale_num}/{scale_denom}"
                            )
                    except:
                        pass

            # Search for coordinate strings in the entire file (OCAD may store CRS as text)
            print("[DEBUG] Searching for CRS strings in file...")
            data_str = data.decode("latin-1", errors="ignore")

            # Search for common CRS-related strings
            search_patterns = [
                "EPSG:",
                "WGS84",
                "Lambert",
                "UTM",
                "RGF93",
                "NAD83",
                "NAD27",
                "CH1903",
                "GK",
                "Mercator",
                "easting",
                "northing",
                "longitude",
                "latitude",
            ]

            for pattern in search_patterns:
                if pattern.lower() in data_str.lower():
                    # Find the context around this match
                    idx = data_str.lower().find(pattern.lower())
                    if idx >= 0:
                        context = data_str[
                            max(0, idx - 20) : min(
                                len(data_str), idx + len(pattern) + 20
                            )
                        ]
                        print(
                            f"[DEBUG] Found '{pattern}' in file context: ...{context}..."
                        )

            # Also search for any text strings that look like coordinates
            import re

            # Look for patterns like "1234567.89" (large numbers that could be coordinates)
            coord_patterns = re.findall(r"(\d{6,7}\.\d+)", data_str)
            if coord_patterns:
                print(
                    f"[DEBUG] Found {len(coord_patterns)} potential coordinate strings"
                )
                # Show first few unique values
                unique_coords = list(set(coord_patterns))[:5]
                print(f"[DEBUG] Sample coordinate strings: {unique_coords}")

                # Also try reading at offset 328 (might have scale factor too)
                if len(data) >= 344:
                    try:
                        real_x0, real_y0, scale_num, scale_denom = struct.unpack(
                            f"{endian}ddii", data[328:344]
                        )
                        if real_x0 > 100000 or real_y0 > 100000:
                            header["real_x0"] = real_x0
                            header["real_y0"] = real_y0
                            header["scale_num"] = scale_num
                            header["scale_denom"] = scale_denom
                            print(
                                f"[DEBUG] Found real-world origin: ({real_x0}, {real_y0}), scale={scale_num}/{scale_denom}"
                            )
                    except:
                        pass

        except Exception as e:
            header["parse_error"] = str(e)

        return header

    def _scan_for_controls(
        self, data: bytes, endian: str, header: Dict
    ) -> List[OCADControl]:
        """
        Scan file for control symbols with coordinates.
        Try BOTH little and big endian for better detection.
        """
        controls = []

        # Try both endianness
        for end in ["<", ">"]:
            # Find all potential control symbol occurrences
            control_positions = []

            for i in range(len(data) - 4):
                try:
                    sym = struct.unpack(f"{end}i", data[i : i + 4])[0]
                    # Check if it's a control symbol (201000-203999)
                    if 201000 <= sym <= 203999:
                        control_positions.append((i, sym, end))
                except:
                    continue

            if control_positions:
                print(
                    f"Found {len(control_positions)} control symbols with {end} endian"
                )

            # For each control symbol, look for coordinates nearby
            for pos, sym, e in control_positions:
                # Look for coordinates in the 200 bytes before and after the symbol
                coord = self._find_coordinates_near_position(data, pos, e)

                if coord:
                    control = self._create_control(sym, coord)
                    if control:
                        # Avoid duplicates (same position)
                        if not any(
                            abs(c.x - control.x) < 1 and abs(c.y - control.y) < 1
                            for c in controls
                        ):
                            controls.append(control)

        # If we didn't find controls with this approach, try scanning for large integer pairs
        if not controls:
            print("Trying direct object scan...")
            controls = self._scan_objects_directly(data, endian)

        # Last resort: try the OTHER endianness for direct scan
        if not controls:
            other_endian = ">" if endian == "<" else "<"
            print(f"Trying direct object scan with {other_endian} endian...")
            controls = self._scan_objects_directly(data, other_endian)

        return controls

    def _find_coordinates_near_position(
        self, data: bytes, sym_pos: int, endian: str
    ) -> Optional[Tuple[float, float]]:
        """Find coordinates near a control symbol position."""

        # In OCAD objects, after the symbol number comes:
        # - object type (1 byte)
        # - angle (2 bytes)
        # - color info
        # - then coordinates

        # The coordinates are typically 8-50 bytes after the symbol number

        for offset in range(8, 150, 8):
            check_pos = sym_pos + offset
            if check_pos + 8 > len(data):
                break

            try:
                x, y = struct.unpack(f"{endian}ii", data[check_pos : check_pos + 8])

                # Check if these could be valid coordinates in 0.01mm
                # For France, we expect large positive numbers
                # Convert to meters
                x_m = x / 100000.0
                y_m = y / 100000.0

                # Valid map coordinates - accept a wider range for different CRS
                # Could be Lambert-93, WGS84, or local coordinates
                if (1000 < x_m < 2000000) and (1000 < y_m < 10000000):
                    return (x_m, y_m)

            except:
                continue

        return None

    def _scan_objects_directly(self, data: bytes, endian: str) -> List[OCADControl]:
        """
        Alternative approach: scan for objects with valid coordinates
        and check if they use control symbols.
        """
        controls = []

        # First, let's find ALL large integer pairs that could be coordinates
        # and print them for debugging
        potential_coords = []

        # Look for large integer pairs that could be coordinates
        for i in range(0, min(len(data) - 16, 500000), 8):  # Limit scan for performance
            try:
                x, y = struct.unpack(f"{endian}ii", data[i : i + 8])

                # Convert to meters (OCAD uses 0.01mm units)
                x_m = x / 100000.0
                y_m = y / 100000.0

                # Check if these look like valid map coordinates
                if (1000 < x_m < 2000000) and (1000 < y_m < 10000000):
                    potential_coords.append((i, x, y, x_m, y_m))

            except:
                continue

        print(
            f"[DEBUG] Found {len(potential_coords)} potential coordinate pairs with {endian} endian"
        )

        # Show first few for debugging
        if potential_coords:
            print(f"[DEBUG] First 5 potential coords (offset, raw_x, raw_y, x_m, y_m):")
            for i, (offset, raw_x, raw_y, x_m, y_m) in enumerate(potential_coords[:5]):
                print(
                    f"  {i + 1}. offset={offset}, raw=({raw_x}, {raw_y}), meters=({x_m:.2f}, {y_m:.2f})"
                )

            # Use the first few valid coordinate pairs as controls
            # These could be control positions
            for idx, (offset, raw_x, raw_y, x_m, y_m) in enumerate(
                potential_coords[:20]
            ):
                # Try to determine control number from nearby data
                # Look for a symbol number nearby
                symbol_num = None
                for search_offset in range(max(0, offset - 50), offset):
                    try:
                        sym = struct.unpack(
                            f"{endian}i", data[search_offset : search_offset + 4]
                        )[0]
                        if 201000 <= sym <= 203999:
                            symbol_num = sym - 201000
                            break
                    except:
                        continue

                control = OCADControl(
                    number=idx + 1, x=x_m, y=y_m, code=f"201.{idx + 1}", control_type=0
                )
                controls.append(control)

        return controls

    def _create_control(
        self, sym_num: int, coord: Tuple[float, float]
    ) -> Optional[OCADControl]:
        """Create a control from symbol number and coordinates."""
        base_symbol = sym_num // 1000
        control_number = sym_num % 1000

        # Determine control type
        if base_symbol == 202:
            control_type = 1  # Start
        elif base_symbol == 203:
            control_type = 2  # Finish
        else:
            control_type = 0  # Regular control

        code = f"{base_symbol}.{control_number // 100}"

        return OCADControl(
            number=control_number,
            x=coord[0],
            y=coord[1],
            code=code,
            control_type=control_type,
        )

    def _organize_controls(self, controls: List[OCADControl]) -> None:
        """Organize controls into courses."""
        if not controls:
            return

        # Sort by control type then number
        controls.sort(key=lambda c: (c.control_type, c.number))

        starts = [c for c in controls if c.control_type == 1]
        finishes = [c for c in controls if c.control_type == 2]
        regular = [c for c in controls if c.control_type == 0]

        if starts and finishes:
            # Create course between start and finish
            start_num = starts[0].number
            finish_num = finishes[0].number

            course_controls = [
                c for c in controls if start_num <= c.number <= finish_num
            ]
            course_controls.sort(key=lambda c: c.number)

            if course_controls:
                course = OCADCourse(
                    name="Circuit importé",
                    category="Course",
                    controls=course_controls,
                    number_of_controls=len(course_controls),
                )
                self.data.courses.append(course)

        if regular:
            course = OCADCourse(
                name="Postes",
                controls=regular,
                number_of_controls=len(regular),
            )
            self.data.courses.append(course)

        # Calculate bounds from controls
        if controls:
            xs = [c.x for c in controls]
            ys = [c.y for c in controls]
            self.data.min_x = min(xs)
            self.data.max_x = max(xs)
            self.data.min_y = min(ys)
            self.data.max_y = max(ys)

    def get_bounds(self) -> Optional[Dict[str, float]]:
        if not self.data:
            return None
        return {
            "min_x": self.data.min_x,
            "min_y": self.data.min_y,
            "max_x": self.data.max_x,
            "max_y": self.data.max_y,
        }

    def get_courses(self) -> List[OCADCourse]:
        if not self.data:
            return []
        return self.data.courses


def validate_ocad_file(file_path: Path) -> Tuple[bool, Optional[str]]:
    if file_path.suffix.lower() not in [".ocd", ".ocs"]:
        return False, f"Extension '{file_path.suffix}' non reconnue. Utiliser .ocd"
    if file_path.stat().st_size == 0:
        return False, "Fichier vide"
    try:
        with open(file_path, "rb") as f:
            magic = struct.unpack("<h", f.read(2))[0]
            if magic != 0x0CAD:
                f.seek(0)
                magic_reversed = struct.unpack(">h", f.read(2))[0]
                if magic_reversed != 0x0CAD:
                    return False, "Ce fichier n'est pas un fichier OCAD valide"
    except Exception as e:
        return False, f"Erreur: {str(e)}"
    return True, None
