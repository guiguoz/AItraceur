# =============================================
# OSM Fetcher - Récupération des données OpenStreetMap
# Sprint 3: Intégration OSM & Overlay Forêt/Ville
# =============================================

import json
import requests
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


# =============================================
# Constants
# =============================================

# Overpass API endpoint (public, gratuit)
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

# D'autres endpoints de backup:
# - https://lz4.overpass-api.de/api/interpreter
# - https://z.overpass-api.de/api/interpreter


# =============================================
# Types d'éléments OSM à récupérer
# =============================================
OSM_ELEMENT_TYPES = {
    # Routes et chemins
    "highways": {
        "tags": ["highway"],
        "values": [
            "motorway",
            "trunk",
            "primary",
            "secondary",
            "tertiary",
            "unclassified",
            "residential",
            "service",
            "track",
            "path",
            "footway",
            "cycleway",
            "steps",
            "bridleway",
            "busway",
        ],
        "description": "Routes et chemins",
    },
    # Bâtiments
    "buildings": {
        "tags": ["building"],
        "values": ["*"],  # Tous les bâtiments
        "description": "Bâtiments",
    },
    # Usage du sol
    "landuse": {
        "tags": ["landuse"],
        "values": [
            "forest",
            "residential",
            "commercial",
            "industrial",
            "grass",
            "farmland",
            "meadow",
            "orchard",
        ],
        "description": "Usage du sol",
    },
    # Eau
    "water": {
        "tags": ["natural", "water"],
        "values": ["water", "river", "lake", "pond", "stream"],
        "description": "Plans d'eau",
    },
    # Zones vertes
    "green_areas": {
        "tags": ["leisure", "landuse", "natural"],
        "values": ["park", "garden", "forest", "grass", "meadow"],
        "description": "Zones vertes",
    },
    # Mobilier urbain
    "amenities": {
        "tags": ["amenity"],
        "values": [
            "bench",
            "waste_basket",
            "street_lamp",
            "clock",
            "telephone",
            "post_box",
            " atm",
            "restaurant",
            "cafe",
            "parking",
            "school",
            "hospital",
        ],
        "description": "Mobilier et services",
    },
    # Clôtures et murs
    "barriers": {
        "tags": ["barrier"],
        "values": [
            "wall",
            "fence",
            "hedge",
            "gate",
            "bollard",
            "retaining_wall",
            "ditch",
        ],
        "description": "Barrières et clôtures",
    },
    # Zones interdite
    "restricted": {
        "tags": ["access", "landuse"],
        "values": ["military", "construction", "private"],
        "description": "Zones restreintes",
    },
}


# =============================================
# Structures de données
# =============================================
@dataclass
class OSMData:
    """Données OSM pour une zone."""

    bounding_box: "BoundingBox"  # Forward reference
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    # Données brutes (GeoJSON)
    roads: List[Dict] = field(default_factory=list)
    buildings: List[Dict] = field(default_factory=list)
    landuse: List[Dict] = field(default_factory=list)
    water: List[Dict] = field(default_factory=list)
    green_areas: List[Dict] = field(default_factory=list)
    amenities: List[Dict] = field(default_factory=list)
    barriers: List[Dict] = field(default_factory=list)
    restricted: List[Dict] = field(default_factory=list)

    # Métadonnées
    total_elements: int = 0
    status: str = "pending"
    error_message: Optional[str] = None


# Import forward reference
from .lidar_manager import BoundingBox


# =============================================
# Requêtes Overpass
# =============================================
class OSMFetcher:
    """
    Récupère les données OpenStreetMap pour une zone géographique.

    Utilise l'Overpass API pour interroguer OSM.
    Les données sont gratuites et ouvertes (ODbL).
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialise le fetcher OSM.

        Args:
            cache_dir: Dossier pour mettre en cache les données
        """
        self.cache_dir = cache_dir or Path("/tmp/aitraceur_osm")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_url = OVERPASS_API_URL

    def build_overpass_query(
        self, bbox: BoundingBox, element_types: List[str] = None
    ) -> str:
        """
        Construit une requête Overpass pour récupérer les données.

        Args:
            bbox: Emprise géographique
            element_types: Types d'éléments à récupérer

        Returns:
            Requête OverpassQL
        """
        if element_types is None:
            element_types = ["highways", "buildings", "landuse", "water", "green_areas"]

        # Format bbox pour Overpass: (sud, ouest, nord, est)
        b = f"{bbox.min_y},{bbox.min_x},{bbox.max_y},{bbox.max_x}"

        # Construire les filtres par type demandé
        filters = []

        if "highways" in element_types:
            filters.append(f'way["highway"]({b})')

        if "buildings" in element_types:
            filters.append(f'way["building"]({b})')

        if "landuse" in element_types:
            filters.append(f'way["landuse"]({b})')
            filters.append(f'relation["landuse"]({b})')

        if "water" in element_types:
            filters.append(f'way["natural"~"water|wetland|riverbank"]({b})')
            filters.append(f'way["water"]({b})')
            filters.append(f'relation["natural"~"water|wetland"]({b})')

        if "green_areas" in element_types:
            filters.append(f'way["natural"~"wood|forest|scrub|heath|grassland|fell"]({b})')
            filters.append(f'way["leisure"~"park|garden|pitch|golf_course"]({b})')

        if "barriers" in element_types:
            filters.append(f'way["barrier"~"wall|fence|hedge|ditch|retaining_wall"]({b})')

        if not filters:
            filters.append(f'way["highway"]({b})')

        # Chaque filtre doit se terminer par ";" dans le bloc union Overpass
        union = "\n  ".join(f + ";" for f in filters)
        # "out body geom" retourne les coordonnées des ways (indispensable)
        full_query = f"[out:json][timeout:90];\n(\n  {union}\n);\nout body geom;"

        return full_query

    def fetch_overpass(
        self, bbox: BoundingBox, element_types: List[str] = None, use_cache: bool = True
    ) -> Dict:
        """
        Exécute une requête Overpass et retourne les résultats.

        Args:
            bbox: Emprise géographique
            element_types: Types d'éléments à récupérer
            use_cache: Utiliser le cache si disponible

        Returns:
            Résultats bruts d'Overpass (JSON)
        """
        # Générer un nom de cache
        cache_key = (
            f"osm_{bbox.min_x:.0f}_{bbox.min_y:.0f}_{bbox.max_x:.0f}_{bbox.max_y:.0f}"
        )
        if element_types:
            cache_key += "_" + "_".join(sorted(element_types))
        cache_file = self.cache_dir / f"{cache_key}.json"

        # Vérifier le cache
        if use_cache and cache_file.exists():
            print(f"  [OK] Utilisation du cache OSM: {cache_key}")
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

        # Construire la requête
        query = self.build_overpass_query(bbox, element_types)

        print(f"  [REQ] Requête Overpass API...")

        try:
            response = requests.post(
                self.api_url,
                data={"data": query},
                timeout=180,  # 3 minutes timeout
            )

            # Debug: afficher le status et les premiers caractères de la réponse
            print(f"  Response status: {response.status_code}")
            if response.status_code != 200:
                print(f"  Response text: {response.text[:500]}")

            response.raise_for_status()

            data = response.json()

            # Sauvegarder en cache
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            print(
                f"  [OK] Données OSM récupérées: {len(data.get('elements', []))} éléments"
            )
            return data

        except requests.exceptions.RequestException as e:
            print(f"  [ERROR] Erreur Overpass: {e}")
            raise

    def process_osm_data(self, raw_data: Dict, bbox: BoundingBox) -> OSMData:
        """
        Traite les données brutes Overpass en données structurées.

        Args:
            raw_data: Données brutes d'Overpass
            bbox: Emprise géographique

        Returns:
            OSMData avec les données organisées
        """
        osm_data = OSMData(bounding_box=bbox)

        elements = raw_data.get("elements", [])
        osm_data.total_elements = len(elements)

        for elem in elements:
            elem_type = elem.get("type")
            tags = elem.get("tags", {})

            # Déterminer la catégorie
            category = self._categorize_element(elem, tags)

            if category:
                # Créer l'élément GeoJSON
                geojson_elem = self._to_geojson(elem, category)

                # Ajouter à la bonne catégorie
                if category == "roads":
                    osm_data.roads.append(geojson_elem)
                elif category == "buildings":
                    osm_data.buildings.append(geojson_elem)
                elif category == "landuse":
                    osm_data.landuse.append(geojson_elem)
                elif category == "water":
                    osm_data.water.append(geojson_elem)
                elif category == "green_areas":
                    osm_data.green_areas.append(geojson_elem)
                elif category == "amenities":
                    osm_data.amenities.append(geojson_elem)
                elif category == "barriers":
                    osm_data.barriers.append(geojson_elem)
                elif category == "restricted":
                    osm_data.restricted.append(geojson_elem)

        osm_data.status = "ready"

        print(f"  [OK] Données traitées:")
        print(f"      - Routes: {len(osm_data.roads)}")
        print(f"      - Bâtiments: {len(osm_data.buildings)}")
        print(f"      - Usage du sol: {len(osm_data.landuse)}")
        print(f"      - Eau: {len(osm_data.water)}")
        print(f"      - Zones vertes: {len(osm_data.green_areas)}")

        return osm_data

    def _categorize_element(self, elem: Dict, tags: Dict) -> Optional[str]:
        """Détermine la catégorie d'un élément."""

        # Routes
        if "highway" in tags:
            return "roads"

        # Bâtiments
        if "building" in tags:
            return "buildings"

        # Usage du sol
        if "landuse" in tags:
            if tags["landuse"] in ["forest", "grass", "meadow", "farmland", "orchard"]:
                return "green_areas"
            return "landuse"

        # Eau
        if "natural" in tags and tags["natural"] in ["water", "river", "lake", "pond"]:
            return "water"
        if "water" in tags:
            return "water"

        # Zones vertes
        if "leisure" in tags and tags["leisure"] in ["park", "garden"]:
            return "green_areas"
        if "natural" in tags and tags["natural"] in ["forest", "grass", "wood"]:
            return "green_areas"

        # Mobilier
        if "amenity" in tags:
            return "amenities"

        # Barrières
        if "barrier" in tags:
            return "barriers"

        # Accès restreint
        if tags.get("access") in ["private", "military", "no"]:
            return "restricted"

        return None

    def _to_geojson(self, elem: Dict, category: str) -> Dict:
        """Convertit un élément OSM en format GeoJSON."""

        elem_type = elem.get("type")
        osm_id = elem.get("id")
        tags = elem.get("tags", {})

        # Propriétés
        properties = {
            "osm_id": osm_id,
            "category": category,
            **tags,  # Ajouter tous les tags OSM
        }

        # Géométrie
        if elem_type == "node":
            # Point
            geometry = {
                "type": "Point",
                "coordinates": [elem.get("lon"), elem.get("lat")],
            }
        elif elem_type == "way":
            # Ligne ou polygone
            geometry_type = "LineString"
            if "area" in tags and tags["area"] == "yes":
                geometry_type = "Polygon"

            # Les coordonnées sont dans "geometry" pour les ways
            geom = elem.get("geometry", [])
            coordinates = [[g["lon"], g["lat"]] for g in geom]

            if geometry_type == "Polygon":
                coordinates = [coordinates]  # Les polygones ont un tableau de rings

            geometry = {"type": geometry_type, "coordinates": coordinates}
        elif elem_type == "relation":
            # Relations (complexes, à traiter séparément)
            geometry = {"type": "GeometryCollection", "geometries": []}
        else:
            geometry = {"type": "GeometryCollection", "geometries": []}

        return {"type": "Feature", "properties": properties, "geometry": geometry}

    def fetch(
        self, bbox: BoundingBox, element_types: List[str] = None, use_cache: bool = True
    ) -> OSMData:
        """
        Récupère et traite les données OSM pour une zone.

        Args:
            bbox: Emprise géographique
            element_types: Types d'éléments à récupérer
            use_cache: Utiliser le cache

        Returns:
            OSMData avec toutes les données
        """
        print(f"[INFO] Récupération des données OSM pour {bbox.width}m x {bbox.height}m...")

        try:
            # Requête Overpass
            raw_data = self.fetch_overpass(bbox, element_types, use_cache)

            # Traiter les données
            osm_data = self.process_osm_data(raw_data, bbox)

            return osm_data

        except Exception as e:
            osm_data = OSMData(bounding_box=bbox)
            osm_data.status = "error"
            osm_data.error_message = str(e)
            return osm_data

    def get_runability_factors(self, osm_data: OSMData) -> Dict[str, float]:
        """
        Calcule les facteurs de runnabilité basés sur les données OSM.

        Args:
            osm_data: Données OSM

        Returns:
            Dict avec les facteurs de runnabilité
        """
        factors = {
            "road_speed": 1.0,
            "path_speed": 1.0,
            "barrier_factor": 1.0,
            "green_factor": 1.0,
        }

        # Analyser les routes
        roads = osm_data.roads
        if roads:
            # Compter les types de routes
            road_types = {}
            for road in roads:
                highway = road.get("properties", {}).get("highway", "unknown")
                road_types[highway] = road_types.get(highway, 0) + 1

            # Ajuster les facteurs selon les routes disponibles
            if "motorway" in road_types or "trunk" in road_types:
                factors["road_speed"] = 1.2  # Routes = vitesse max
            if "path" in road_types or "footway" in road_types:
                factors["path_speed"] = 1.1  # Chemins = bonus

        # Analyser les barrières
        barriers = osm_data.barriers
        if barriers:
            # Présence de barrières = ralentissement
            factors["barrier_factor"] = 0.9

        # Analyser les zones vertes
        green = osm_data.green_areas
        if green:
            # Forêt = ralentissement
            factors["green_factor"] = 0.8

        return factors


# =============================================
# Sprint features — extraction Overpass sans dépendance externe
# =============================================
def extract_sprint_features(bbox_dict: dict) -> dict:
    """
    Extrait les candidats sprint (intersections de rues + coins de bâtiments)
    et les polygones OOB (bâtiments) depuis Overpass API.

    Approche inspirée de Streeto : les postes sprint se placent sur les
    intersections de rues piétonnes et les angles de bâtiments.

    Args:
        bbox_dict: {min_x, min_y, max_x, max_y} en WGS84

    Returns:
        {
          "candidates": [{x, y, type: "intersection"|"building_corner"|"amenity"}, ...],
          "oob_polygons": [[[lng, lat], ...], ...]  # polygones bâtiments = zones interdites
        }
    """
    import random
    from collections import defaultdict

    b = f"{bbox_dict['min_y']},{bbox_dict['min_x']},{bbox_dict['max_y']},{bbox_dict['max_x']}"

    # Requête Overpass : voies piétonnes + bâtiments
    # "out body geom" retourne la géométrie de chaque way (liste lat/lon)
    walk_tags = "residential|service|unclassified|tertiary|secondary|primary|pedestrian|path|footway|steps|living_street|alley"
    query = f"""[out:json][timeout:90];
(
  way["highway"~"^({walk_tags})$"]({b});
  way["building"]({b});
);
out body geom;"""

    try:
        resp = requests.post(OVERPASS_API_URL, data={"data": query}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[sprint_features] Overpass error: {e}")
        return {"candidates": [], "oob_polygons": []}

    # Séparer highways et bâtiments
    highway_coord_lists: List[List[tuple]] = []
    building_polygons: List[List[tuple]] = []

    for elem in data.get("elements", []):
        tags = elem.get("tags", {})
        geom = elem.get("geometry", [])
        coords = [(g["lon"], g["lat"]) for g in geom if "lon" in g and "lat" in g]
        if not coords:
            continue
        if "highway" in tags:
            highway_coord_lists.append(coords)
        elif "building" in tags:
            building_polygons.append(coords)

    # ── Intersections : noeuds partagés par ≥ 2 voies ──────────────────────
    # On arrondit à 5 décimales (~1m) pour regrouper les noeuds identiques
    node_count: dict = defaultdict(int)
    for way in highway_coord_lists:
        for lng, lat in way:
            key = (round(lng, 5), round(lat, 5))
            node_count[key] += 1

    candidates = []
    seen_coarse: set = set()

    for (lng, lat), count in node_count.items():
        if count >= 2:  # noeud partagé = intersection
            # Déduplication à ~100m (arrondi à 3 décimales ≈ 50-100m)
            coarse = (round(lng, 3), round(lat, 3))
            if coarse not in seen_coarse:
                seen_coarse.add(coarse)
                candidates.append({"x": lng, "y": lat, "type": "intersection"})

    # ── Coins de bâtiments (~ 4 coins par bâtiment) ─────────────────────────
    for poly in building_polygons:
        if len(poly) < 3:
            continue
        step = max(1, len(poly) // 4)
        for i in range(0, len(poly) - 1, step):
            lng, lat = poly[i]
            candidates.append({"x": lng, "y": lat, "type": "building_corner"})

    # ── Fontaines et mobilier urbain (Streeto : "street furniture") ──────────
    amenity_query = f"""[out:json][timeout:30];
node["amenity"~"^(fountain|clock|post_box)$"]({b});
out body;"""
    try:
        ar = requests.post(OVERPASS_API_URL, data={"data": amenity_query}, timeout=45)
        if ar.ok:
            for elem in ar.json().get("elements", []):
                lng, lat = elem.get("lon"), elem.get("lat")
                if lng and lat:
                    candidates.append({"x": lng, "y": lat, "type": "amenity"})
    except Exception:
        pass  # non bloquant

    # Mélanger et limiter à 600 candidats
    random.shuffle(candidates)
    candidates = candidates[:600]

    print(
        f"[sprint_features] {len(candidates)} candidats extraits "
        f"({sum(1 for c in candidates if c['type']=='intersection')} intersections, "
        f"{sum(1 for c in candidates if c['type']=='building_corner')} coins bât.), "
        f"{len(building_polygons)} OOB polygones"
    )

    return {"candidates": candidates, "oob_polygons": building_polygons}


# =============================================
# Fonction utilitaire
# =============================================
def bbox_to_osm_bounds(bbox: BoundingBox) -> str:
    """
    Convertit une bounding box en string pour Overpass.

    Args:
        bbox: Bounding box

    Returns:
        String au format "south,west,north,east"
    """
    return f"{bbox.min_y},{bbox.min_x},{bbox.max_y},{bbox.max_x}"
