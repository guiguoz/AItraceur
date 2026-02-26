# =============================================
# Overlay Builder - Superposition OCAD + OSM + LIDAR
# Sprint 3: Intégration OSM & Overlay Forêt/Ville
# =============================================

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from .lidar_manager import BoundingBox, LIDARData
from .osm_fetcher import OSMFetcher, OSMData
from .terrain_analyzer import TerrainAnalyzer, RunnabilityMap


# =============================================
# Structures de données
# =============================================
@dataclass
class OverlayLayer:
    """Une couche de données dans l'overlay."""

    name: str
    data: Any
    visible: bool = True
    opacity: float = 1.0
    style: Dict = field(default_factory=dict)


@dataclass
class OverlayData:
    """Données combinées pour l'affichage."""

    bounding_box: BoundingBox

    # Couches
    ocad_data: Optional[Dict] = None  # Carte OCAD
    osm_data: Optional[OSMData] = None  # Données OSM
    lidar_data: Optional[LIDARData] = None  # Données LIDAR
    runnability_map: Optional[RunnabilityMap] = None  # Carte de runnabilité

    # Métadonnées
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"
    layers: List[OverlayLayer] = field(default_factory=list)

    # Stats
    total_roads: int = 0
    total_buildings: int = 0
    total_controls: int = 0
    runnability_score: float = 0.0


# =============================================
# Constructeur d'overlay
# =============================================
class OverlayBuilder:
    """
    Construit un overlay combinant:
    - Carte OCAD (symboles, postes, circuits)
    - Données OSM (routes, bâtiments, zones)
    - Données LIDAR (runnabilité, relief)

    Le résultat peut être affiché sur une carte interactive.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialise le constructeur d'overlay."""
        self.cache_dir = cache_dir or Path("/tmp/aitraceur_overlay")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.osm_fetcher = OSMFetcher(cache_dir)
        self.terrain_analyzer = TerrainAnalyzer()

        self.current_overlay: Optional[OverlayData] = None

    def build_overlay(
        self,
        bbox: BoundingBox,
        ocad_data: Optional[Dict] = None,
        osm_data: Optional[OSMData] = None,
        lidar_data: Optional[LIDARData] = None,
        include_osm: bool = True,
        include_lidar: bool = False,
        use_cache: bool = True,
    ) -> OverlayData:
        """
        Construit un overlay avec les données disponibles.

        Args:
            bbox: Emprise géographique
            ocad_data: Données OCAD (optionnel)
            osm_data: Données OSM (optionnel)
            lidar_data: Données LIDAR (optionnel)
            include_osm: Récupérer les données OSM si non fournies
            include_lidar: Récupérer les données LIDAR si non fournies
            use_cache: Utiliser le cache

        Returns:
            OverlayData avec toutes les couches
        """
        print(f"🗺️ Construction de l'overlay pour {bbox.width}m x {bbox.height}m...")

        overlay = OverlayData(bounding_box=bbox)

        # Ajouter les données OCAD
        if ocad_data:
            overlay.ocad_data = ocad_data
            overlay.layers.append(
                OverlayLayer(
                    name="ocad", data=ocad_data, style={"color": "#000000", "weight": 2}
                )
            )

        # Récupérer ou ajouter les données OSM
        if include_osm and not osm_data:
            print("  → Récupération OSM...")
            osm_data = self.osm_fetcher.fetch(bbox, use_cache=use_cache)

        if osm_data:
            overlay.osm_data = osm_data
            overlay.total_roads = len(osm_data.roads)
            overlay.total_buildings = len(osm_data.buildings)
            overlay.layers.extend(
                [
                    OverlayLayer(
                        name="osm_roads",
                        data=osm_data.roads,
                        style={"color": "#3388ff", "weight": 3},
                    ),
                    OverlayLayer(
                        name="osm_buildings",
                        data=osm_data.buildings,
                        style={"color": "#888888", "weight": 1},
                    ),
                    OverlayLayer(
                        name="osm_green",
                        data=osm_data.green_areas,
                        style={"color": "#22cc22", "weight": 1, "fillOpacity": 0.3},
                    ),
                ]
            )

        # Calculer la runnabilité si données LIDAR
        if lidar_data:
            overlay.lidar_data = lidar_data
            self.terrain_analyzer.load_lidar_data(lidar_data)
            runnability = self.terrain_analyzer.generate_runnability_map(bbox)
            overlay.runnability_map = runnability
            overlay.runnability_score = self._calculate_avg_runnability(runnability)
            overlay.layers.append(
                OverlayLayer(
                    name="runnability", data=runnability, style={"opacity": 0.5}
                )
            )

        # Calculer les stats
        overlay.status = "ready"
        self.current_overlay = overlay

        self._print_summary(overlay)

        return overlay

    def _calculate_avg_runnability(self, runnability: RunnabilityMap) -> float:
        """Calcule le score moyen de runnabilité."""
        if not runnability.grid:
            return 0.0

        total = 0
        count = 0
        for row in runnability.grid:
            for cell in row:
                total += cell
                count += 1

        if count == 0:
            return 0.0

        avg_speed = total / count

        # Convertir en score 0-1 (par rapport à la vitesse max)
        return avg_speed / runnability.max_speed

    def _print_summary(self, overlay: OverlayData):
        """Affiche un résumé de l'overlay."""
        print(f"\n  📊 Résumé de l'overlay:")
        print(f"     - Couches: {len(overlay.layers)}")
        print(f"     - Routes OSM: {overlay.total_roads}")
        print(f"     - Bâtiments OSM: {overlay.total_buildings}")
        print(f"     - Score runnabilité: {overlay.runnability_score:.2f}")

    def to_geojson(self, overlay: OverlayData) -> Dict:
        """
        Convertit l'overlay en GeoJSON pour affichage.

        Args:
            overlay: Données de l'overlay

        Returns:
            FeatureCollection GeoJSON
        """
        features = []

        # Ajouter les routes OSM
        if overlay.osm_data:
            for road in overlay.osm_data.roads:
                features.append(
                    {
                        "type": "Feature",
                        "properties": {**road.get("properties", {}), "layer": "roads"},
                        "geometry": road.get("geometry", {}),
                    }
                )

            # Ajouter les bâtiments
            for building in overlay.osm_data.buildings:
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            **building.get("properties", {}),
                            "layer": "buildings",
                        },
                        "geometry": building.get("geometry", {}),
                    }
                )

            # Ajouter les zones vertes
            for green in overlay.osm_data.green_areas:
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            **green.get("properties", {}),
                            "layer": "green_areas",
                        },
                        "geometry": green.get("geometry", {}),
                    }
                )

        # Ajouter les données OCAD (postes, etc.)
        if overlay.ocad_data:
            # Ajouter les circuits
            for circuit in overlay.ocad_data.get("circuits", []):
                for point in circuit.get("control_points", []):
                    features.append(
                        {
                            "type": "Feature",
                            "properties": {
                                "type": "control",
                                "number": point.get("control_number"),
                                "layer": "ocad",
                            },
                            "geometry": {
                                "type": "Point",
                                "coordinates": [point.get("x", 0), point.get("y", 0)],
                            },
                        }
                    )

        return {
            "type": "FeatureCollection",
            "features": features,
            "bbox": [
                overlay.bounding_box.min_x,
                overlay.bounding_box.min_y,
                overlay.bounding_box.max_x,
                overlay.bounding_box.max_y,
            ],
        }

    def to_mapbox_style(self, overlay: OverlayData) -> Dict:
        """
        Génère un style Mapbox pour l'overlay.

        Args:
            overlay: Données de l'overlay

        Returns:
            Style JSON pour Mapbox GL JS
        """
        style = {"version": 8, "sources": {}, "layers": []}

        # Source pour les routes
        if overlay.osm_data and overlay.osm_data.roads:
            style["sources"]["osm_roads"] = {
                "type": "geojson",
                "data": {
                    "type": "FeatureCollection",
                    "features": overlay.osm_data.roads,
                },
            }
            style["layers"].append(
                {
                    "id": "roads",
                    "type": "line",
                    "source": "osm_roads",
                    "paint": {"line-color": "#3388ff", "line-width": 3},
                }
            )

        # Source pour les bâtiments
        if overlay.osm_data and overlay.osm_data.buildings:
            style["sources"]["osm_buildings"] = {
                "type": "geojson",
                "data": {
                    "type": "FeatureCollection",
                    "features": overlay.osm_data.buildings,
                },
            }
            style["layers"].append(
                {
                    "id": "buildings",
                    "type": "fill",
                    "source": "osm_buildings",
                    "paint": {"fill-color": "#888888", "fill-opacity": 0.7},
                }
            )

        return style

    def get_layer_visibility(self, overlay: OverlayData) -> Dict[str, bool]:
        """
        Retourne la visibilité de chaque couche.

        Args:
            overlay: Données de l'overlay

        Returns:
            Dict nom_couche -> visible
        """
        return {layer.name: layer.visible for layer in overlay.layers}

    def set_layer_visibility(
        self, overlay: OverlayData, layer_name: str, visible: bool
    ) -> OverlayData:
        """
        Modifie la visibilité d'une couche.

        Args:
            overlay: Données de l'overlay
            layer_name: Nom de la couche
            visible: Visibilité

        Returns:
            OverlayData modifié
        """
        for layer in overlay.layers:
            if layer.name == layer_name:
                layer.visible = visible

        return overlay

    def get_statistics(self, overlay: OverlayData) -> Dict:
        """
        Calcule des statistiques sur l'overlay.

        Args:
            overlay: Données de l'overlay

        Returns:
            Dict avec les statistiques
        """
        stats = {
            "bounding_box": {
                "width_meters": overlay.bounding_box.width,
                "height_meters": overlay.bounding_box.height,
                "area_km2": (overlay.bounding_box.width * overlay.bounding_box.height)
                / 1_000_000,
            },
            "osm": {
                "total_roads": overlay.total_roads,
                "total_buildings": overlay.total_buildings,
                "total_green_areas": len(overlay.osm_data.green_areas)
                if overlay.osm_data
                else 0,
                "total_water": len(overlay.osm_data.water) if overlay.osm_data else 0,
            },
            "runnability": {
                "score": overlay.runnability_score,
                "max_speed": overlay.runnability_map.max_speed
                if overlay.runnability_map
                else None,
                "min_speed": overlay.runnability_map.min_speed
                if overlay.runnability_map
                else None,
            },
            "layers": len(overlay.layers),
        }

        return stats


# =============================================
# Fonctions utilitaires
# =============================================
def merge_bounds(bounds: List[BoundingBox]) -> BoundingBox:
    """
    Fusionne plusieurs bounding boxes en une seule.

    Args:
        bounds: Liste de bounding boxes

    Returns:
        Bounding box fusionnée
    """
    if not bounds:
        raise ValueError("Au moins une bounding box requise")

    min_x = min(b.min_x for b in bounds)
    min_y = min(b.min_y for b in bounds)
    max_x = max(b.max_x for b in bounds)
    max_y = max(b.max_y for b in bounds)

    return BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def buffer_bbox(bbox: BoundingBox, meters: float) -> BoundingBox:
    """
    Ajoute une marge (buffer) autour d'une bounding box.

    Args:
        bbox: Bounding box originale
        meters: Marge en mètres

    Returns:
        Bounding box agrandie
    """
    return BoundingBox(
        min_x=bbox.min_x - meters,
        min_y=bbox.min_y - meters,
        max_x=bbox.max_x + meters,
        max_y=bbox.max_y + meters,
    )
