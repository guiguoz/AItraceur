"""
Parsing des données cartographiques OCAD → features sémantiques internes.

Deux formats d'entrée supportés :
  1. GeoJSON (dict ou fichier) — sortie de ocad2geojson (Node.js)
     Propriété-clé : ``sym`` (code symbole OCAD, int ou float).
  2. OCAD XML interchange format — export OCAD 9-12.
     Élément racine ``<map>`` ou ``<Map>``.

Sortie : liste de SemanticFeature, chacune portant sa géométrie shapely
et son SemanticInfo dérivée du symbole.

Exemple :
    features = parse_geojson_file("calvaire.geojson")
    forbidden = [f for f in features if f.info.is_forbidden]
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Union

try:
    import pyproj
    from shapely.geometry import (
        LineString, MultiPolygon, Point, Polygon, shape
    )
    from shapely.ops import transform as shp_transform
    _SHAPELY_OK = True
except ImportError:
    _SHAPELY_OK = False

from .symbol_map import SemanticInfo, TerrainType, get_semantic_info, is_layout


# ---------------------------------------------------------------------------
# SemanticFeature — feature enrichie
# ---------------------------------------------------------------------------

@dataclass
class SemanticFeature:
    """
    Objet cartographique après résolution sémantique.

    Attributes:
        fid:        Identifiant de feature (index ou valeur de propriété).
        geom:       Géométrie shapely (en coordonnées SOURCES — voir note CRS).
        geom_type:  ``"Point"``, ``"LineString"``, ``"Polygon"``, etc.
        info:       Informations sémantiques (category, terrain_type, scores…).
        sym:        Code symbole OCAD original.
        raw_props:  Propriétés brutes de la feature source.
    """
    fid: str
    geom: Any          # shapely geometry (Point/LineString/Polygon/…)
    geom_type: str
    info: SemanticInfo
    sym: int
    raw_props: dict = field(default_factory=dict)

    @property
    def is_layout(self) -> bool:
        return self.info.is_layout

    @property
    def is_forbidden(self) -> bool:
        return self.info.is_forbidden

    @property
    def is_linear(self) -> bool:
        return self.geom_type in ("LineString", "MultiLineString")

    @property
    def is_area(self) -> bool:
        return self.geom_type in ("Polygon", "MultiPolygon")

    @property
    def is_point(self) -> bool:
        return self.geom_type == "Point"


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

def _make_projector(
    source_epsg: Optional[int],
    target_epsg: Optional[int],
) -> Optional[Any]:
    """Crée un transformateur pyproj source→target, ou None si non disponible."""
    if not _SHAPELY_OK:
        return None
    if source_epsg is None or target_epsg is None:
        return None
    if source_epsg == target_epsg:
        return None
    try:
        src = pyproj.CRS.from_epsg(source_epsg)
        tgt = pyproj.CRS.from_epsg(target_epsg)
        return pyproj.Transformer.from_crs(src, tgt, always_xy=True).transform
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Parsing GeoJSON
# ---------------------------------------------------------------------------

def parse_geojson(
    data: Union[dict, list],
    *,
    source_epsg: Optional[int] = 4326,
    target_epsg: Optional[int] = None,
    skip_layout: bool = True,
) -> list[SemanticFeature]:
    """
    Parse un GeoJSON FeatureCollection (dict Python) en SemanticFeatures.

    Args:
        data:         GeoJSON dict (FeatureCollection ou liste de features).
        source_epsg:  EPSG des coordonnées sources (défaut : 4326 = WGS84).
        target_epsg:  EPSG cible pour projection. Si None → pas de projection.
        skip_layout:  Si True, filtre les symboles de mise en page.

    Returns:
        Liste de SemanticFeature (geometry en shapely, unité cible).
    """
    if not _SHAPELY_OK:
        raise ImportError("shapely et pyproj sont requis pour le parsing géospatial.")

    projector = _make_projector(source_epsg, target_epsg)

    features_raw: list[dict]
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features_raw = data.get("features", [])
    elif isinstance(data, list):
        features_raw = data
    else:
        raise ValueError("Format GeoJSON non reconnu (attendu FeatureCollection ou liste).")

    results: list[SemanticFeature] = []
    for idx, feat in enumerate(features_raw):
        props = feat.get("properties") or {}
        geom_dict = feat.get("geometry")
        if geom_dict is None:
            continue

        # Résolution du code symbole
        sym_raw = props.get("sym") or props.get("ocd8sym") or props.get("symNum")
        if sym_raw is None:
            continue
        sym = int(float(sym_raw))

        info = get_semantic_info(sym)
        if skip_layout and info.is_layout:
            continue

        # Construction de la géométrie shapely
        try:
            geom = shape(geom_dict)
        except Exception:
            continue

        if projector is not None:
            try:
                geom = shp_transform(projector, geom)
            except Exception:
                pass

        fid = str(feat.get("id", idx))
        results.append(SemanticFeature(
            fid=fid,
            geom=geom,
            geom_type=geom.geom_type,
            info=info,
            sym=sym,
            raw_props=dict(props),
        ))

    return results


def parse_geojson_file(
    path: Union[str, Path],
    *,
    source_epsg: Optional[int] = 4326,
    target_epsg: Optional[int] = None,
    skip_layout: bool = True,
) -> list[SemanticFeature]:
    """Charge un fichier GeoJSON et appelle parse_geojson()."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return parse_geojson(
        data,
        source_epsg=source_epsg,
        target_epsg=target_epsg,
        skip_layout=skip_layout,
    )


# ---------------------------------------------------------------------------
# Parsing OCAD XML (format interchange OCAD 9-12)
# ---------------------------------------------------------------------------
#
# Format attendu (simplifié) :
#   <map version="12">
#     <objects>
#       <object type="point" sym="204.0">
#         <coords count="1">x;y</coords>
#       </object>
#       <object type="line" sym="504.0">
#         <coords count="N">x1;y1 x2;y2 …</coords>
#       </object>
#     </objects>
#   </map>
#
# Les coordonnées sont en unités OCAD (1/100 mm en unités papier).
# La conversion en mètres nécessite l'échelle de la carte.

_OCAD_COORD_SCALE = 1e-5   # 1/100 mm × 100 000 = 10 m (ordre de grandeur)
# Plus précisément : unité OCAD = 1/100 mm papier.
# À l'échelle 1:10000 → 1 mm papier = 10 m terrain → 1 OCAD unit = 0.1 m
# On expose un paramètre map_scale pour calibrer.


def _ocad_units_to_m(val: float, map_scale: int) -> float:
    """Convertit des unités OCAD en mètres terrain.

    1 unité OCAD = 1/100 mm papier = map_scale / 100 000 mètres terrain.
    """
    return val * map_scale / 100_000.0


def _parse_ocad_coords(
    coord_str: str, map_scale: int
) -> list[tuple[float, float]]:
    """Parse une chaîne de coordonnées OCAD 'x1;y1 x2;y2 …' en liste de tuples (m)."""
    points = []
    for token in coord_str.strip().split():
        parts = token.split(";")
        if len(parts) >= 2:
            try:
                x = _ocad_units_to_m(float(parts[0]), map_scale)
                y = _ocad_units_to_m(float(parts[1]), map_scale)
                points.append((x, y))
            except ValueError:
                continue
    return points


def parse_ocad_xml(
    source: Union[str, Path, bytes],
    *,
    map_scale: int = 10000,
    skip_layout: bool = True,
) -> list[SemanticFeature]:
    """
    Parse un fichier OCAD XML interchange en SemanticFeatures.

    Les coordonnées de sortie sont en mètres terrain.

    Args:
        source:      Chemin de fichier, string XML ou bytes.
        map_scale:   Échelle de la carte (ex : 10000 pour 1:10000).
        skip_layout: Si True, filtre les symboles de mise en page.

    Returns:
        Liste de SemanticFeature.
    """
    if not _SHAPELY_OK:
        raise ImportError("shapely est requis.")

    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source):
        tree = ET.parse(str(source))
        root = tree.getroot()
    else:
        xml_bytes = source if isinstance(source, bytes) else source.encode()
        root = ET.fromstring(xml_bytes)

    # Namespace optionnel
    ns = ""
    tag = root.tag
    if tag.startswith("{"):
        ns = tag[: tag.index("}") + 1]

    # Chercher le bloc <objects>
    objects_el = root.find(f"{ns}objects")
    if objects_el is None:
        objects_el = root  # fallback si la structure est plate

    results: list[SemanticFeature] = []
    for idx, obj_el in enumerate(objects_el.iter(f"{ns}object")):
        sym_str = obj_el.get("sym", "0")
        try:
            sym = int(float(sym_str))
        except ValueError:
            continue

        info = get_semantic_info(sym)
        if skip_layout and info.is_layout:
            continue

        obj_type = obj_el.get("type", "point").lower()
        coords_el = obj_el.find(f"{ns}coords")
        if coords_el is None or not coords_el.text:
            continue

        pts = _parse_ocad_coords(coords_el.text, map_scale)
        if not pts:
            continue

        # Construction géométrie shapely
        try:
            if obj_type == "point" or len(pts) == 1:
                geom = Point(pts[0])
                geom_type = "Point"
            elif obj_type == "line":
                geom = LineString(pts)
                geom_type = "LineString"
            elif obj_type in ("area", "polygon"):
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                geom = Polygon(pts)
                geom_type = "Polygon"
            else:
                geom = LineString(pts)
                geom_type = "LineString"
        except Exception:
            continue

        fid = obj_el.get("id", str(idx))
        results.append(SemanticFeature(
            fid=fid,
            geom=geom,
            geom_type=geom_type,
            info=info,
            sym=sym,
        ))

    return results


# ---------------------------------------------------------------------------
# Helpers sur les features
# ---------------------------------------------------------------------------

def extract_forbidden_zones(features: list[SemanticFeature]) -> list[Any]:
    """Retourne les géométries (Polygon/LineString) des zones interdites."""
    zones = []
    for f in features:
        if f.is_forbidden and f.geom is not None:
            zones.append(f.geom)
    return zones


def extract_linear_features(
    features: list[SemanticFeature],
    *,
    categories: Optional[set[str]] = None,
) -> list[SemanticFeature]:
    """Filtre les features linéaires (chemins, murs, cours d'eau, etc.).

    Args:
        categories: Si fourni, ne garde que les features de ces SemanticCategory.
    """
    result = []
    for f in features:
        if not f.is_linear:
            continue
        if categories is not None and f.info.category.value not in categories:
            continue
        result.append(f)
    return result


def extract_area_features(
    features: list[SemanticFeature],
    *,
    categories: Optional[set[str]] = None,
) -> list[SemanticFeature]:
    """Filtre les features surfaciques (végétation, eau, bâtiments, etc.)."""
    result = []
    for f in features:
        if not f.is_area:
            continue
        if categories is not None and f.info.category.value not in categories:
            continue
        result.append(f)
    return result
