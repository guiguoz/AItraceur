# =============================================
# LIDAR Manager - Gestion des données LIDAR IGN
# Sprint 2: Intégration LIDAR & Terrain Forêt
# =============================================

import math
import os
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime


# =============================================
# URLs officielles IGN pour LIDAR HD
# =============================================

# URLs de téléchargement LIDAR HD IGN
# Source: https://geoservices.ign.fr/lidarhd
IGN_LIDAR_URLS = {
    # URL principale - données classifiées (recommandées)
    "classifiees": "https://tiles.geoservices.ign.fr/diffusion/ortho/lidar-hd/CLASSIFIED/{zone}/{tile_name}.laz",
    # URL données brutes
    "brutes": "https://tiles.geoservices.ign.fr/diffusion/ortho/lidar-hd/RAW/{zone}/{tile_name}.laz",
    # Grille de référence (GeoJSON avec les tuiles disponibles)
    "grid_url": "https://www.geoportal.developpement-durable.gouv.fr/ressources/concours/ign/lidar-hd-grid.geojson",
}

# Départements disponibles pour LIDAR HD (au 2025)
# La France n'est pas encore couverte à 100%
IGN_LIDAR_ZONES = {
    # Exemples de zones couvertes (à vérifier sur geoservices.ign.fr)
    "A01": {"dept": "Alpes-Maritimes", "covered": True},
    "A04": {"dept": "Alpes-de-Haute-Provence", "covered": True},
    "A06": {"dept": "Alpes-Maritimes", "covered": True},
    "A09": {"dept": "Ariège", "covered": True},
    "A10": {"dept": "Charente-Maritime", "covered": True},
    "A11": {"dept": "Cher", "covered": True},
    "A14": {"dept": "Calvados", "covered": True},
    "A15": {"dept": "Cantal", "covered": True},
    "A29": {"dept": "Eure", "covered": True},
    "A2A": {"dept": "Corse-du-Sud", "covered": True},
    "A2B": {"dept": "Haute-Corse", "covered": True},
    "A30": {"dept": "Gard", "covered": True},
    "A33": {"dept": "Gironde", "covered": True},
    "A34": {"dept": "Hérault", "covered": True},
    "A35": {"dept": "Ille-et-Vilaine", "covered": True},
    "A37": {"dept": "Indre-et-Loire", "covered": True},
    "A38": {"dept": "Isère", "covered": True},
    "A40": {"dept": "Jura", "covered": True},
    "A42": {"dept": "Loire", "covered": True},
    "A43": {"dept": "Haute-Loire", "covered": True},
    "A44": {"dept": "Loire-Atlantique", "covered": True},
    "A45": {"dept": "Loiret", "covered": True},
    "A46": {"dept": "Lot", "covered": True},
    "A47": {"dept": "Lot-et-Garonne", "covered": True},
    "A48": {"dept": "Lozère", "covered": True},
    "A49": {"dept": "Maine-et-Loire", "covered": True},
    "A50": {"dept": "Manche", "covered": True},
    "A51": {"dept": "Marne", "covered": True},
    "A52": {"dept": "Haute-Marne", "covered": True},
    "A53": {"dept": "Mayenne", "covered": True},
    "A54": {"dept": "Meurthe-et-Moselle", "covered": True},
    "A55": {"dept": "Meuse", "covered": True},
    "A56": {"dept": "Morbihan", "covered": True},
    "A57": {"dept": "Moselle", "covered": True},
    "A58": {"dept": "Nièvre", "covered": True},
    "A59": {"dept": "Nord", "covered": True},
    "A60": {"dept": "Oise", "covered": True},
    "A61": {"dept": "Orne", "covered": True},
    "A62": {"dept": "Pas-de-Calais", "covered": True},
    "A63": {"dept": "Puy-de-Dôme", "covered": True},
    "A64": {"dept": "Pyrénées-Atlantiques", "covered": True},
    "A65": {"dept": "Hautes-Pyrénées", "covered": True},
    "A66": {"dept": "Pyrénées-Orientales", "covered": True},
    "A67": {"dept": "Bas-Rhin", "covered": True},
    "A68": {"dept": "Haut-Rhin", "covered": True},
    "A69": {"dept": "Rhône", "covered": True},
    "A70": {"dept": "Haute-Saône", "covered": True},
    "A71": {"dept": "Saône-et-Loire", "covered": True},
    "A72": {"dept": "Sarthe", "covered": True},
    "A73": {"dept": "Savoie", "covered": True},
    "A74": {"dept": "Haute-Savoie", "covered": True},
    "A75": {"dept": "Paris", "covered": True},
    "A76": {"dept": "Seine-Maritime", "covered": True},
    "A77": {"dept": "Seine-et-Marne", "covered": True},
    "A78": {"dept": "Yvelines", "covered": True},
    "A79": {"dept": "Deux-Sèvres", "covered": True},
    "A80": {"dept": "Somme", "covered": True},
    "A81": {"dept": "Tarn", "covered": True},
    "A82": {"dept": "Tarn-et-Garonne", "covered": True},
    "A83": {"dept": "Var", "covered": True},
    "A84": {"dept": "Vaucluse", "covered": True},
    "A85": {"dept": "Vendée", "covered": True},
    "A86": {"dept": "Vienne", "covered": True},
    "A87": {"dept": "Haute-Vienne", "covered": True},
    "A89": {"dept": "Yonne", "covered": True},
    "A91": {"dept": "Essonne", "covered": True},
    "A92": {"dept": "Hauts-de-Seine", "covered": True},
    "A93": {"dept": "Seine-Saint-Denis", "covered": True},
    "A94": {"dept": "Val-de-Marne", "covered": True},
    "A95": {"dept": "Val-d'Oise", "covered": True},
}


# =============================================
# Structures de données
# =============================================
@dataclass
class BoundingBox:
    """Emprise géographique (bounds).

    Attributes:
        min_x: Coordonnée X minimale (longitude Est ou longitude)
        min_y: Coordonnée Y minimale (latitude Nord ou latitude)
        max_x: Coordonnée X maximale
        max_y: Coordonnée Y maximale
        crs: Système de coordonnées (WGS84, Lambert-93, etc.)
    """

    min_x: float
    min_y: float
    max_x: float
    max_y: float
    crs: str = "WGS84"  # Par défaut WGS84 (lat/lon en degrés)

    def __post_init__(self):
        """Valide la bbox."""
        if self.min_x >= self.max_x:
            raise ValueError("min_x doit être < max_x")
        if self.min_y >= self.max_y:
            raise ValueError("min_y doit être < max_y")

    @property
    def center_x(self) -> float:
        return (self.min_x + self.max_x) / 2

    @property
    def center_y(self) -> float:
        return (self.min_y + self.max_y) / 2

    @property
    def width(self) -> float:
        """Largeur. En degrés si WGS84, en mètres sinon."""
        if self.crs == "WGS84":
            # Approximation: 1 degré ≈ 111km * cos(latitude)
            # Pour simplifier, on retourne juste la différence
            return self.max_x - self.min_x
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        """Hauteur. En degrés si WGS84, en mètres sinon."""
        return self.max_y - self.min_y

    @property
    def width_meters(self) -> float:
        """Largeur approximative en mètres."""
        if self.crs == "WGS84":
            # 1 degré de latitude ≈ 111 km
            # 1 degré de longitude ≈ 111 km * cos(latitude)
            lat = self.center_y
            meters_per_degree = 111320  # à l'équateur
            return (
                (self.max_x - self.min_x)
                * meters_per_degree
                * abs(math.cos(math.radians(lat)))
            )
        return self.max_x - self.min_x

    @property
    def height_meters(self) -> float:
        """Hauteur approximative en mètres."""
        if self.crs == "WGS84":
            # 1 degré de latitude ≈ 111 km
            return (self.max_y - self.min_y) * 111320
        return self.max_y - self.min_y


@dataclass
class LIDARTile:
    """Une tuile LIDAR IGN."""

    name: str  # Ex: "4878_6855" (Est_Nord à l'échelle 1/1000)
    x: int  # Index X dans la grille
    y: int  # Index Y dans la grille
    zip_url: str = ""
    status: str = "pending"  # pending, downloading, downloaded, error

    @property
    def filename(self) -> str:
        return f"{self.name}.laz"


@dataclass
class LIDARData:
    """Données LIDAR pour une zone."""

    bounding_box: BoundingBox
    tiles: List[LIDARTile] = field(default_factory=list)
    dtm_path: Optional[Path] = None  # Digital Terrain Model (sol nu)
    dsm_path: Optional[Path] = None  # Digital Surface Model (sol + végétation)
    vegetation_height_path: Optional[Path] = None  # Hauteur de végétation
    slope_path: Optional[Path] = None  # Pente
    processed_at: Optional[datetime] = None
    status: str = "pending"  # pending, downloading, processing, ready, error
    error_message: Optional[str] = None


# =============================================
# Gestionnaire LIDAR
# =============================================
class LIDARManager:
    """
    Gestionnaire pour télécharger et traiter les données LIDAR IGN.

    IGN France propose le RGE ALTI® avec des tuiles de 1km x 1km.
    Format: .laz (compressed LAS)

    Source: https://geoservices.ign.fr/lidarhd
    """

    # Grille des tuiles IGN (1km x 1km en Lambert-93)
    # Une tuile = un carré de 1000m x 1000m
    TILE_SIZE = 1000  # mètres

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialise le gestionnaire LIDAR.

        Args:
            cache_dir: Dossier pour mettre en cache les tuiles téléchargées
        """
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "aitraceur_lidar"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_zone_from_coords(self, x: float, y: float) -> Optional[str]:
        """
        Détermine la zone (département) IGN à partir des coordonnées.

        En Lambert-93, les coordonnées couvrent:
        - X: de ~0 (Ouest) à ~1,200,000 (Est)
        - Y: de ~6,000,000 (Sud) à ~7,200,000 (Nord)

        Args:
            x: Coordonnée X (Lambert-93)
            y: Coordonnée Y (Lambert-93)

        Returns:
            Code zone (ex: "A33") ou None si non couvert
        """
        # Tableau des zones par département (approximatif)
        # En réalité, il faudrait une table de correspondance plus précise
        # ou utiliser l'API IGN

        # Cette fonction est une approximation
        # Pour un fonctionnement correct, il faudrait:
        # 1. Télécharger la grille GeoJSON des tuiles disponibles
        # 2. Vérifier intersects avec notre emprise

        # France métropolitaine approx en Lambert-93
        if not (0 <= x <= 1200000 and 6000000 <= y <= 7200000):
            return None

        # Mapping simplifié - à affiner avec les vraies données
        # Les zones sont numérotées par département
        # Pour la version complète, voir la documentation IGN

        # Par défaut, retourne None (zone non déterminée)
        # L'utilisateur devra spécifier la zone manuellement
        return None

    def get_required_tiles(
        self, bbox: BoundingBox, zone: str = None
    ) -> List[LIDARTile]:
        """
        Calcule quelles tuiles LIDAR sont nécessaires pour couvrir une emprise.

        Args:
            bbox: Emprise géographique
            zone: Code zone IGN (ex: "A33" pour Gironde)

        Returns:
            Liste des tuiles nécessaires
        """
        tiles = []

        # Calculer les index de tuiles
        # En Lambert-93, les coordonnées sont en mètres
        # x commence à 0 environ (pour la France)
        # y peut aller jusqu'à plusieurs millions

        # Trouver les tuiles qui intersectent la bbox
        min_tile_x = int(bbox.min_x // self.TILE_SIZE)
        max_tile_x = int(bbox.max_x // self.TILE_SIZE)
        min_tile_y = int(bbox.min_y // self.TILE_SIZE)
        max_tile_y = int(bbox.max_y // self.TILE_SIZE)

        for tile_x in range(min_tile_x, max_tile_x + 1):
            for tile_y in range(min_tile_y, max_tile_y + 1):
                tile_name = f"{tile_x}_{tile_y}"

                # Construire l'URL de téléchargement
                # Format IGN: {zone}/{tile_x}_{tile_y}.laz
                if zone:
                    laz_url = f"https://tiles.geoservices.ign.fr/diffusion/ortho/lidar-hd/CLASSIFIED/{zone}/{tile_name}.laz"
                else:
                    # Si pas de zone spécifiée, URL générique (ne fonctionnera pas)
                    laz_url = ""

                tiles.append(
                    LIDARTile(name=tile_name, x=tile_x, y=tile_y, zip_url=laz_url)
                )

        return tiles

    def download_tile(self, tile: LIDARTile, force: bool = False) -> Path:
        """
        Télécharge une tuile LIDAR.

        Args:
            tile: Tuile à télécharger
            force: Forcer le téléchargement même si déjà en cache

        Returns:
            Chemin vers le fichier .laz téléchargé
        """
        tile_dir = self.cache_dir / tile.name
        tile_dir.mkdir(parents=True, exist_ok=True)

        laz_path = tile_dir / tile.filename

        # Si déjà téléchargé et pas de force, utiliser le cache
        if laz_path.exists() and not force:
            print(f"  ✓ Utilisation du cache: {tile.name}")
            return laz_path

        # Télécharger le fichier
        print(f"  ↓ Téléchargement: {tile.zip_url}")

        try:
            # NOTE: En réalité, il faudrait gérer l'authentification IGN
            # et vérifier que l'URL existe avant de télécharger
            # Pour la démo, on simule le téléchargement

            # Création d'un fichier vide pour la démo
            # En production, décommenter:
            # urllib.request.urlretrieve(tile.zip_url, zip_path)
            # with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            #     zip_ref.extractall(tile_dir)

            # Pour la démo, créer un fichier placeholder
            laz_path.write_text(f"Démo tuile {tile.name}")

            tile.status = "downloaded"
            print(f"  ✓ Téléchargé: {tile.name}")

        except Exception as e:
            tile.status = "error"
            print(f"  ✗ Erreur téléchargement {tile.name}: {e}")
            raise

        return laz_path

    def download_tiles(
        self, bbox: BoundingBox, zone: str = None, force: bool = False
    ) -> List[Path]:
        """
        Télécharge toutes les tuiles nécessaires pour une emprise.

        Args:
            bbox: Emprise géographique
            zone: Code zone IGN (ex: "A33" pour Gironde)
            force: Forcer le téléchargement

        Returns:
            Liste des chemins vers les fichiers .laz
        """
        if not zone:
            print("⚠️ ATTENTION: Aucune zone spécifiée!")
            print("   Les données LIDAR IGN sont organisées par département/zone.")
            print("   Veuillez spécifier une zone (ex: zone='A33' pour Gironde)")
            print(f"   Zones disponibles: {list(IGN_LIDAR_ZONES.keys())[:10]}...")
            # Retourne une liste vide au lieu de lever une erreur
            return []

        tiles = self.get_required_tiles(bbox, zone)

        if not tiles:
            print(f"⚠️ Aucune tuile à télécharger pour la zone {zone}")
            return []

        print(f"📥 Téléchargement de {len(tiles)} tuile(s) LIDAR pour zone {zone}...")

        downloaded = []
        for tile in tiles:
            try:
                path = self.download_tile(tile, force=force)
                downloaded.append(path)
            except Exception as e:
                print(f"  ⚠️ Tuile {tile.name} non disponible: {e}")
                # Continuer avec les tuiles disponibles

        return downloaded

    def process_to_rasters(self, lidar_data: LIDARData) -> LIDARData:
        """
        Transforme les tuiles LAS/LAZ en rasters (DTM, DSM, pente).

        NOTE: Nécessite PDAL ou des bibliothèques comme rasterio.
        Pour ce Sprint 2, on expose l'interface.

        Args:
            lidar_data: Données LIDAR avec les tuiles

        Returns:
            Données LIDAR avec les chemins vers les rasters
        """
        # En production, ceci utiliserait:
        # - PDAL pour lire les .laz
        # - rasterio pour créer les rasters
        # - numpy pour les calculs de hauteur et pente

        # Simulation du traitement
        lidar_data.status = "processing"

        # Créer des fichiers raster factices pour la démo
        output_dir = self.cache_dir / "rasters"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Ces fichiers seraient en réalité des GeoTIFF
        lidar_data.dtm_path = output_dir / "dtm.tif"
        lidar_data.dsm_path = output_dir / "dsm.tif"
        lidar_data.vegetation_height_path = output_dir / "vegetation_height.tif"
        lidar_data.slope_path = output_dir / "slope.tif"

        # Créer des fichiers placeholders
        for path in [
            lidar_data.dtm_path,
            lidar_data.dsm_path,
            lidar_data.vegetation_height_path,
            lidar_data.slope_path,
        ]:
            if not path.exists():
                path.write_text(f"Démo raster: {path.name}")

        lidar_data.status = "ready"
        lidar_data.processed_at = datetime.utcnow()

        return lidar_data

    def get_lidar_data(
        self, bbox: BoundingBox, zone: str = None, force_download: bool = False
    ) -> LIDARData:
        """
        Récupère les données LIDAR pour une emprise donnée.

        Args:
            bbox: Emprise géographique
            zone: Code zone IGN (ex: "A33" pour Gironde) - OBLIGATOIRE
            force_download: Forcer le téléchargement même si en cache

        Returns:
            Données LIDAR avec tous les rasters
        """
        # Créer l'objet de données
        lidar_data = LIDARData(
            bounding_box=bbox,
            tiles=self.get_required_tiles(bbox, zone),
            status="pending",
        )

        # Télécharger les tuiles
        downloaded_tiles = self.download_tiles(bbox, zone=zone, force=force_download)
        lidar_data.tiles = [t for t in lidar_data.tiles if t.status == "downloaded"]

        if not lidar_data.tiles:
            lidar_data.status = "error"
            lidar_data.error_message = (
                "Aucune tuile disponible. "
                "Vérifiez que la zone est correcte et que les données LIDAR "
                "sont disponibles pour cette zone."
            )
            return lidar_data

        # Traiter en rasters
        lidar_data = self.process_to_rasters(lidar_data)

        return lidar_data

    def list_available_zones(self) -> Dict[str, Dict]:
        """
        Liste toutes les zones LIDAR disponibles.

        Returns:
            Dict avec les codes zones et informations
        """
        return IGN_LIDAR_ZONES

    def check_zone_coverage(self, bbox: BoundingBox, zone: str) -> Dict:
        """
        Vérifie si une zone est couverte par les données LIDAR IGN.

        Args:
            bbox: Emprise géographique
            zone: Code zone IGN

        Returns:
            Dict avec les informations de couverture
        """
        if zone not in IGN_LIDAR_ZONES:
            return {
                "zone": zone,
                "covered": False,
                "message": f"Zone {zone} non reconnue",
            }

        zone_info = IGN_LIDAR_ZONES[zone]

        return {
            "zone": zone,
            "department": zone_info.get("dept"),
            "covered": zone_info.get("covered", False),
            "tiles_needed": len(self.get_required_tiles(bbox, zone)),
            "message": f"Zone {zone} ({zone_info.get('dept')})",
        }


# =============================================
# Fonctions utilitaires
# =============================================
def bbox_from_coordinates(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> BoundingBox:
    """
    Crée une bounding box à partir de coordonnées lat/lon.

    NOTE: En réalité, il faudrait transformer les coordonnées
    (lat/lon) dans le système de projection des tuiles (Lambert-93).
    """
    return BoundingBox(
        min_x=min_lon,  # En réalité: conversion Lambert-93
        min_y=min_lat,
        max_x=max_lon,
        max_y=max_lat,
    )
