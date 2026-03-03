# =============================================
# Point d'entrée FastAPI
# Import KMZ/XML & Affichage Carte
# =============================================

from typing import List, Any, Dict, Optional
from pathlib import Path
import uuid
import tempfile
import math

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import get_db, engine, Base
from src.models.circuit import Circuit, ControlPoint
from src.schemas.circuit import (
    CircuitResponse,
    CircuitCreate,
    CircuitListResponse,
    ControlPointResponse,
)
from src.services.terrain.lidar_manager import LIDARManager, BoundingBox
from src.services.terrain.terrain_analyzer import TerrainAnalyzer, calculate_runnability_score
from src.services.terrain.osm_fetcher import OSMFetcher
from src.services.terrain.elevation_fetcher import fetch_elevations
from src.services.terrain.overlay_builder import OverlayBuilder
from src.services.terrain.urban_osm_processor import (
    UrbanOSMProcessor,
    UrbanControlDetector,
)
from src.services.optimization.detector import ProblemDetector
from src.services.optimization.route_calculator import (
    RouteCalculator,
    PositionOptimizer,
    estimate_circuit_time,
)

# Sprint 6: Base de connaissances RAG
from src.services.knowledge_base import (
    AIAssistant,
    RAGBuilder,
    DocumentLoader,
    LiveloxScraper,
    VikazimutScraper,
    OfficialDocuments,
    KnowledgeChunk,
    RouteGadgetScraper,
    RouteAnalyzer,
)

# Sprint 7: Génération de circuits
from src.services.generation import (
    AIGenerator,
    GenerationRequest,
    CircuitScorer,
    compare_circuits,
)

# RouteAI Integration
from src.services.generation import (
    MapProcessor,
    PathFinder,
    TSPSolver,
    GridNode,
)

# Sprint 9: Exports
from src.services.export import (
    export_circuit_to_iof,
    export_circuit_to_gpx,
    export_circuit_to_pdf,
    export_circuit_to_kml,
    export_circuit_to_kmz,
)

# Import: KMZ/KML and IOF XML
from src.services.importers.kml_importer import (
    KMLImporter,
    convert_kmz_to_circuits,
    import_kmz_file,
    import_kml_file,
)
from src.services.importers.iof_importer import (
    IOFImporter,
    convert_iof_to_circuits,
    import_iof_file,
)
from src.services.ocad.terrain_descriptor import (
    describe_course_terrain,
    describe_terrain_around_control,
)
from src.services.knowledge_base.local_rag import LocalRAG


# =============================================
# Création de l'application FastAPI
# =============================================
app = FastAPI(
    title="AItraceur API",
    description="API pour l'aide au traçage de parcours de course d'orientation",
    version="0.1.0",  # Sprint 1
    docs_url="/docs",
    redoc_url="/redoc",
)


# =============================================
# Configuration CORS
# =============================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, spécifier les origins autorisés
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================
# Événements de démarrage/arrêt
# =============================================
@app.on_event("startup")
def startup_event():
    """Code exécuté au démarrage de l'application."""
    # Créer les tables si elles n'existent pas
    Base.metadata.create_all(bind=engine)
    print("[OK] Base de donnees initialisee")

    # Créer le dossier d'upload s'il n'existe pas
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[OK] Dossier d'upload: {settings.UPLOAD_DIR}")


@app.on_event("shutdown")
def shutdown_event():
    """Code exécuté à l'arrêt de l'application."""
    print("[X] Application arretee")


# =============================================
# Route: Page d'accueil
# =============================================
@app.get("/")
def root():
    """Page d'accueil de l'API."""
    return {
        "name": "AItraceur API",
        "version": "0.1.0",
        "description": "Aide au traçage de parcours de CO",
        "docs": "/docs",
        "sprint": "Import KMZ/XML & Affichage Carte",
    }


# =============================================
# Route: Health check
# =============================================
@app.get("/health")
def health_check():
    """Vérifie que l'API fonctionne."""
    return {"status": "healthy"}


# =============================================
# Route: Upload de carte overlay KMZ/KML
# =============================================
@app.post(
    "/api/v1/maps/upload-overlay",
    summary="Upload une carte overlay KMZ/KML",
    description="""
    Upload un fichier KMZ ou KML contenant une carte overlay.
    
    Le fichier est analysé et les circuits sont extraits pour affichage sur la carte.
    """,
)
async def upload_overlay(
    file: UploadFile = File(..., description="Fichier KMZ ou KML"),
):
    """
    Upload et parse un fichier KMZ/KML pour obtenir les circuits overlay.

    Returns:
        Circuits extraits du fichier KML
    """
    # Valider l'extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".kmz", ".kml"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extension '{file_ext}' non supportée. Utiliser .kmz ou .kml",
        )

    # Sauvegarder le fichier temporairement
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = settings.UPLOAD_DIR / unique_filename

    try:
        content = await file.read()

        if len(content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE / 1024 / 1024} MB)",
            )

        with open(file_path, "wb") as f:
            f.write(content)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la sauvegarde: {str(e)}",
        )

    # Parser le fichier
    importer = KMLImporter()

    try:
        if file_ext == ".kmz":
            result = importer.import_kmz(str(file_path))
            print(
                f"[DEBUG] KMZ import - circuits: {len(result.circuits)}, map_image: {result.map_image is not None}, map_filename: {result.map_filename}"
            )
        else:
            result = importer.import_kml(str(file_path))
            print(
                f"[DEBUG] KML import - circuits: {len(result.circuits)}, map_image: {result.map_image is not None}"
            )

        if result.status != "ok":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.error or "Erreur lors du parsing KML",
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[DEBUG] Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erreur lors du parsing: {str(e)}",
        )

    # Convertir en format AItraceur
    circuits = convert_kmz_to_circuits(result)

    # Préparer l'image de la carte (en base64)
    map_image_base64 = None
    if result.map_image:
        import base64

        map_image_base64 = base64.b64encode(result.map_image).decode("utf-8")

    # Use the GroundOverlay bounds directly from the KML
    bounds = {}
    if result.bounds and result.bounds.get("min_lat"):
        bounds = result.bounds.copy()

        # Do NOT adjust bounds based on image aspect ratio - the KML LatLonBox
        # already defines the exact geographic extent where the image should be placed

    elif result.circuits:
        # Fallback: calculate from circuits
        all_lats = []
        all_lons = []
        for circuit in circuits:
            for control in circuit.get("controls", []):
                if "y" in control and "x" in control:
                    all_lats.append(control["y"])
                    all_lons.append(control["x"])
        if all_lats and all_lons:
            bounds = {
                "min_lat": min(all_lats),
                "max_lat": max(all_lats),
                "min_lon": min(all_lons),
                "max_lon": max(all_lons),
            }

    # Clean up temp file
    try:
        file_path.unlink()
    except:
        pass

    # Return circuits and image
    return {
        "success": True,
        "filename": file.filename,
        "file_size": len(content),
        "circuits_found": len(circuits),
        "circuits": circuits,
        "map_image": map_image_base64,
        "map_filename": result.map_filename,
        "bounds": bounds,
        "rotation": result.rotation if hasattr(result, "rotation") else 0.0,
        "image_width": result.image_width if hasattr(result, "image_width") else 0,
        "image_height": result.image_height if hasattr(result, "image_height") else 0,
        "corners": bounds.get("corners") if bounds else None,
    }


# =============================================
# Route: Liste des circuits
# =============================================
@app.get(
    "/api/v1/circuits",
    response_model=CircuitListResponse,
    summary="Liste tous les circuits",
    description="Retourne la liste de tous les circuits uploadés",
)
def list_circuits(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """Liste les circuits avec pagination."""
    # Compter le total
    total = db.query(Circuit).count()

    # Récupérer les circuits
    circuits = db.query(Circuit).offset(skip).limit(limit).all()

    return CircuitListResponse(
        circuits=[CircuitResponse.model_validate(c) for c in circuits],
        total=total,
        page=skip // limit + 1,
        page_size=limit,
    )


# =============================================
# Route: Détails d'un circuit
# =============================================
@app.get(
    "/api/v1/circuits/{circuit_id}",
    response_model=CircuitResponse,
    summary="Détails d'un circuit",
    description="Retourne les détails d'un circuit spécifique",
)
def get_circuit(circuit_id: int, db: Session = Depends(get_db)):
    """Retourne un circuit par son ID."""
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    return CircuitResponse.model_validate(circuit)


# =============================================
# Route: Supprimer un circuit
# =============================================
@app.delete(
    "/api/v1/circuits/{circuit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprime un circuit",
)
def delete_circuit(circuit_id: int, db: Session = Depends(get_db)):
    """Supprime un circuit et ses postes associés."""
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    db.delete(circuit)
    db.commit()

    return None


# =============================================
# Route: Analyse LIDAR d'un circuit
# =============================================
@app.get(
    "/api/v1/circuits/{circuit_id}/analyze",
    summary="Analyse le terrain avec LIDAR",
    description="Récupère les données LIDAR et calcule la runnabilité",
)
def analyze_circuit_terrain(
    circuit_id: int,
    zone: str = None,
    force_download: bool = False,
    db: Session = Depends(get_db),
):
    """
    Analyse le terrain d'un circuit en utilisant les données LIDAR.

    Args:
        circuit_id: ID du circuit à analyser
        zone: Code zone IGN (ex: "A33" pour Gironde, "A14" pour Calvados)
              Liste des zones: https://geoservices.ign.fr/lidarhd
        force_download: Forcer le téléchargement même si en cache

    Returns:
        Informations sur le terrain et la runnabilité
    """
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Vérifier qu'on a les bounds
    if not circuit.bounds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le circuit n'a pas d'emprise géographique définie",
        )

    bbox = BoundingBox(
        min_x=circuit.bounds.get("min_x", 0),
        min_y=circuit.bounds.get("min_y", 0),
        max_x=circuit.bounds.get("max_x", 0),
        max_y=circuit.bounds.get("max_y", 0),
    )

    # Vérifier la zone
    if not zone:
        # Retourner les zones disponibles si pas spécifiée
        lidar_manager = LIDARManager()
        available_zones = lidar_manager.list_available_zones()

        return {
            "circuit_id": circuit_id,
            "message": "Veuillez spécifier une zone IGN (ex: zone=A33)",
            "example": "/api/v1/circuits/1/analyze?zone=A33",
            "available_zones": list(available_zones.keys())[:20],
            "more_info": "https://geoservices.ign.fr/lidarhd",
        }

    # Initialiser le gestionnaire LIDAR
    lidar_manager = LIDARManager()

    # Vérifier la couverture
    coverage = lidar_manager.check_zone_coverage(bbox, zone)

    # Récupérer les données LIDAR
    try:
        lidar_data = lidar_manager.get_lidar_data(
            bbox, zone=zone, force_download=force_download
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du téléchargement LIDAR: {str(e)}",
        )

    # Initialiser l'analyseur de terrain
    analyzer = TerrainAnalyzer()
    analyzer.load_lidar_data(lidar_data)

    # Générer la carte de runnabilité
    runnability_map = analyzer.generate_runnability_map(bbox)

    return {
        "circuit_id": circuit_id,
        "zone": zone,
        "coverage": coverage,
        "terrain_analysis": {
            "status": lidar_data.status,
            "tiles_downloaded": len(lidar_data.tiles),
            "bounding_box": {
                "min_x": bbox.min_x,
                "min_y": bbox.min_y,
                "max_x": bbox.max_x,
                "max_y": bbox.max_y,
                "width_meters": bbox.width,
                "height_meters": bbox.height,
            },
            "runnability": {
                "resolution_meters": runnability_map.resolution,
                "max_speed_mpm": runnability_map.max_speed,
                "min_speed_mpm": runnability_map.min_speed,
                "grid_size": f"{len(runnability_map.grid)}x{len(runnability_map.grid[0]) if runnability_map.grid else 0}",
            },
            "dtm_available": lidar_data.dtm_path is not None,
            "dsm_available": lidar_data.dsm_path is not None,
            "vegetation_available": lidar_data.vegetation_height_path is not None,
            "slope_available": lidar_data.slope_path is not None,
        },
        "note": "Cette fonctionnalité nécessite un téléchargement réel des tuiles LIDAR depuis geoservices.ign.fr",
    }


# =============================================
# Route: Récupération des données OSM
# =============================================
@app.get(
    "/api/v1/terrain/osm",
    summary="Récupère les données OpenStreetMap",
    description="Récupère les données OSM (routes, bâtiments, zones) pour une zone géographique",
)
def get_osm_data(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    crs: str = "WGS84",
    element_types: str = "highways,buildings,landuse,water,green_areas",
    use_cache: bool = True,
):
    """
    Récupère les données OpenStreetMap pour une zone géographique.

    Args:
        min_x, min_y, max_x, max_y: Coordonnées de la bounding box (en degrés pour WGS84)
        crs: Système de coordonnées (WGS84=lat/lon en degrés, Lambert93=mètres)
        element_types: Types d'éléments à récupérer (séparés par des virgules)
        use_cache: Utiliser le cache si disponible

    Returns:
        Données OSM structurées
    """
    # Créer la bounding box
    try:
        bbox = BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y, crs=crs)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bounding box invalide: {str(e)}",
        )

    # Parser les types d'éléments
    elem_types = [e.strip() for e in element_types.split(",")]

    # Récupérer les données
    fetcher = OSMFetcher()
    osm_data = fetcher.fetch(bbox, element_types=elem_types, use_cache=use_cache)

    # Calculer les facteurs de runnabilité
    runnability_factors = fetcher.get_runability_factors(osm_data)

    return {
        "status": osm_data.status,
        "bounding_box": {
            "min_x": bbox.min_x,
            "min_y": bbox.min_y,
            "max_x": bbox.max_x,
            "max_y": bbox.max_y,
            "crs": bbox.crs,
            "width_degrees": bbox.width,
            "height_degrees": bbox.height,
            "estimated_width_meters": bbox.width_meters,
            "estimated_height_meters": bbox.height_meters,
        },
        "statistics": {
            "total_elements": osm_data.total_elements,
            "roads": len(osm_data.roads),
            "buildings": len(osm_data.buildings),
            "landuse": len(osm_data.landuse),
            "water": len(osm_data.water),
            "green_areas": len(osm_data.green_areas),
            "amenities": len(osm_data.amenities),
            "barriers": len(osm_data.barriers),
            "restricted": len(osm_data.restricted),
        },
        "runnability_factors": runnability_factors,
        "fetched_at": osm_data.fetched_at.isoformat(),
        "note": "Données © OpenStreetMap contributors (ODbL)",
    }


# =============================================
# Utilitaire: ray casting point-in-polygon
# =============================================
def _point_in_polygon(lat: float, lng: float, feature: dict) -> bool:
    """
    Teste si (lat, lng) est à l'intérieur d'un polygone GeoJSON Feature.
    Algorithme: ray casting. Aucune dépendance externe.
    """
    try:
        geom = feature.get("geometry", {})
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            return False
        rings = geom.get("coordinates", [[]])
        # Pour MultiPolygon, tester chaque polygone
        if geom.get("type") == "MultiPolygon":
            return any(
                _ray_cast(lat, lng, poly[0])
                for poly in rings
                if poly
            )
        return _ray_cast(lat, lng, rings[0])
    except Exception:
        return False


def _ray_cast(lat: float, lng: float, ring: list) -> bool:
    n, inside = len(ring), False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


# =============================================
# Route: Grille de runnabilité (SRTM + OSM)
# =============================================
@app.post(
    "/api/v1/terrain/runnability-grid",
    summary="Grille de runnabilité terrain",
    description=(
        "Génère une grille GeoJSON de runnabilité en combinant "
        "l'élévation SRTM (OpenTopoData) et le landuse OSM. "
        "Chaque cellule est un polygone avec un score de runnabilité (0-1), "
        "la pente estimée et la hauteur de végétation."
    ),
)
async def get_runnability_grid(request: Dict):
    """
    Paramètres body:
      bounding_box: {min_x (lng), min_y (lat), max_x (lng), max_y (lat)}
      resolution_m: résolution de la grille en mètres (défaut 100)

    Retourne un GeoJSON FeatureCollection.
    """
    bbox_raw = request.get("bounding_box", {})
    res_m = float(request.get("resolution_m", 100))
    res_m = max(50.0, min(500.0, res_m))  # clamp entre 50 et 500 m

    try:
        bbox = BoundingBox(
            min_x=float(bbox_raw["min_x"]),
            min_y=float(bbox_raw["min_y"]),
            max_x=float(bbox_raw["max_x"]),
            max_y=float(bbox_raw["max_y"]),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"bounding_box invalide: {e}")

    # 1. Générer la grille lat/lng
    METERS_PER_DEG_LAT = 111320.0
    deg_step_lat = res_m / METERS_PER_DEG_LAT
    mid_lat = (bbox.min_y + bbox.max_y) / 2.0
    cos_lat = abs(math.cos(math.radians(mid_lat))) or 1e-9
    deg_step_lng = res_m / (METERS_PER_DEG_LAT * cos_lat)

    lats, lat_cur = [], bbox.min_y
    while lat_cur <= bbox.max_y + deg_step_lat * 0.01:
        lats.append(lat_cur)
        lat_cur += deg_step_lat

    lngs, lng_cur = [], bbox.min_x
    while lng_cur <= bbox.max_x + deg_step_lng * 0.01:
        lngs.append(lng_cur)
        lng_cur += deg_step_lng

    if len(lats) < 2 or len(lngs) < 2:
        raise HTTPException(status_code=400, detail="Zone trop petite pour la résolution choisie")

    # 2. Récupérer les altitudes via OpenTopoData
    grid_points = [(lat, lng) for lat in lats for lng in lngs]
    elevations = fetch_elevations(grid_points)
    elev_grid = [
        [elevations[r * len(lngs) + c] for c in range(len(lngs))]
        for r in range(len(lats))
    ]

    # 3. Récupérer le landuse OSM
    landuse_features: List[Dict] = []
    try:
        fetcher = OSMFetcher()
        osm_data = fetcher.fetch(bbox, element_types=["landuse", "green_areas"])
        landuse_features = osm_data.landuse + osm_data.green_areas
    except Exception as e:
        print(f"[runnability-grid] OSM fetch failed: {e}")

    # Mapping landuse OSM → hauteur de végétation estimée (mètres)
    LANDUSE_VEG_HEIGHT: Dict[str, float] = {
        "forest": 12.0,
        "wood": 12.0,
        "scrub": 3.0,
        "heath": 1.0,
        "grassland": 0.1,
        "meadow": 0.3,
        "farmland": 0.5,
        "wetland": 1.5,
        "orchard": 4.0,
        "vineyard": 1.5,
        "park": 3.0,
        "garden": 1.0,
        "grass": 0.1,
    }

    # 4. Construire les cellules GeoJSON
    features = []
    for r in range(len(lats) - 1):
        for c in range(len(lngs) - 1):
            cell_lat = lats[r] + deg_step_lat / 2.0
            cell_lng = lngs[c] + deg_step_lng / 2.0

            # Pente en % (gradient à partir de l'élévation des voisins)
            dz_lat = elev_grid[r + 1][c] - elev_grid[r][c]
            dz_lng = elev_grid[r][c + 1] - elev_grid[r][c]
            slope = math.sqrt(dz_lat ** 2 + dz_lng ** 2) / res_m * 100.0

            # Hauteur végétation depuis landuse OSM
            veg_height = 0.0
            for lf in landuse_features:
                if _point_in_polygon(cell_lat, cell_lng, lf):
                    tags = lf.get("properties", {}).get("tags", {})
                    lu_type = (
                        tags.get("landuse")
                        or tags.get("natural")
                        or tags.get("leisure")
                        or ""
                    )
                    if lu_type in LANDUSE_VEG_HEIGHT:
                        veg_height = LANDUSE_VEG_HEIGHT[lu_type]
                    break

            score = calculate_runnability_score(slope, veg_height)

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [lngs[c], lats[r]],
                        [lngs[c + 1], lats[r]],
                        [lngs[c + 1], lats[r + 1]],
                        [lngs[c], lats[r + 1]],
                        [lngs[c], lats[r]],
                    ]],
                },
                "properties": {
                    "runnability": round(score, 2),
                    "slope_percent": round(slope, 1),
                    "vegetation_height": round(veg_height, 1),
                    "speed_mpm": round(140.0 * score),
                    "elevation": round(elev_grid[r][c], 1),
                },
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "grid_size": [len(lats) - 1, len(lngs) - 1],
        "resolution_m": res_m,
        "bbox": bbox_raw,
    }


# =============================================
# Route: Dénivelé du parcours (D+/D-)
# =============================================
@app.post(
    "/api/v1/terrain/course-elevation",
    summary="Dénivelé du parcours (D+/D-)",
    description=(
        "Calcule le dénivelé positif (D+) et négatif (D-) d'un parcours "
        "à partir des coordonnées des postes. Utilise OpenTopoData SRTM 90m. "
        "N postes ≤ 100 = 1 seul batch, réponse quasi-instantanée."
    ),
)
async def get_course_elevation(request: Dict):
    """
    Body:
      controls: [{lat, lng, order}]

    Retourne:
      total_climb_m, total_descent_m, elevations: [{order, lat, lng, elevation}]
    """
    controls_raw = request.get("controls", [])
    if len(controls_raw) < 2:
        raise HTTPException(
            status_code=400,
            detail="Au moins 2 postes sont nécessaires pour calculer le dénivelé",
        )

    # Trier par order
    sorted_controls = sorted(controls_raw, key=lambda c: c.get("order", 0))

    # Fetch élévations (1 seul batch si ≤ 100 postes)
    points = [(float(c["lat"]), float(c["lng"])) for c in sorted_controls]
    elevations = fetch_elevations(points)

    # Calculer D+ et D-
    total_climb = 0.0
    total_descent = 0.0
    for i in range(1, len(elevations)):
        diff = elevations[i] - elevations[i - 1]
        if diff > 0:
            total_climb += diff
        else:
            total_descent += abs(diff)

    return {
        "total_climb_m": round(total_climb),
        "total_descent_m": round(total_descent),
        "elevations": [
            {
                "order": sorted_controls[i].get("order", i + 1),
                "lat": sorted_controls[i]["lat"],
                "lng": sorted_controls[i]["lng"],
                "elevation": round(elevations[i], 1),
            }
            for i in range(len(sorted_controls))
        ],
    }


# =============================================
# Route: Overlay complet (OCAD + OSM + LIDAR)
# =============================================
@app.get(
    "/api/v1/terrain/overlay",
    summary="Construit un overlay combinant OCAD, OSM et LIDAR",
    description="Construit un overlay avec toutes les données disponibles pour affichage",
)
def get_overlay(
    circuit_id: int = None,
    min_x: float = None,
    min_y: float = None,
    max_x: float = None,
    max_y: float = None,
    include_osm: bool = True,
    include_lidar: bool = False,
    db: Session = Depends(get_db),
):
    """
    Construit un overlay avec les données OCAD, OSM et LIDAR.

    Peut utiliser soit:
    - circuit_id: pour récupérer l'emprise depuis un circuit en base
    - min_x, min_y, max_x, max_y: pour spécifier l'emprise directement

    Args:
        circuit_id: ID du circuit (optionnel)
        min_x, min_y, max_x, max_y: Emprise géographique (optionnel)
        include_osm: Inclure les données OSM
        include_lidar: Inclure les données LIDAR (si zone spécifiée)

    Returns:
        Overlay avec toutes les données
    """
    # Déterminer l'emprise
    if circuit_id:
        # Récupérer depuis la base
        circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()
        if not circuit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Circuit {circuit_id} non trouvé",
            )
        if not circuit.bounds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le circuit n'a pas d'emprise géographique",
            )
        bbox = BoundingBox(
            min_x=circuit.bounds.get("min_x", 0),
            min_y=circuit.bounds.get("min_y", 0),
            max_x=circuit.bounds.get("max_x", 0),
            max_y=circuit.bounds.get("max_y", 0),
        )
    elif min_x is not None:
        # Utiliser les coordonnées fournies
        try:
            bbox = BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bounding box invalide: {str(e)}",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Veuillez fournir circuit_id ou les coordonnées min_x, min_y, max_x, max_y",
        )

    # Construire l'overlay
    builder = OverlayBuilder()
    overlay = builder.build_overlay(
        bbox=bbox, include_osm=include_osm, include_lidar=include_lidar
    )

    # Obtenir les statistiques
    stats = builder.get_statistics(overlay)

    return {
        "status": overlay.status,
        "bounding_box": stats["bounding_box"],
        "statistics": stats,
        "layers": [layer.name for layer in overlay.layers],
        "runnability_score": overlay.runnability_score,
        "geojson_available": True,
        "note": "Pour récupérer le GeoJSON, ajoutez /geojson à l'endpoint",
    }


# =============================================
# Route: Analyse des problèmes d'un circuit
# =============================================
@app.get(
    "/api/v1/circuits/{circuit_id}/analyze-problems",
    summary="Analyse les problèmes d'un circuit",
    description="Détecte automatiquement les problèmes de sécurité, techniques et de visibilité",
)
def analyze_circuit_problems(
    circuit_id: int, include_osm: bool = False, db: Session = Depends(get_db)
):
    """
    Analyse un circuit et détecte les problèmes.

    Types de problèmes détectés:
    - Sécurité: traversées de routes, zones privées
    - Technique: postes trop proches, interpostes linéaires
    - Visibilité: spoils (postes visibles l'un de l'autre)

    Args:
        circuit_id: ID du circuit à analyser
        include_osm: Inclure les données OSM pour une analyse plus complète

    Returns:
        Rapport d'analyse avec les problèmes détectés
    """
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les postes
    controls = (
        db.query(ControlPoint).filter(ControlPoint.circuit_id == circuit_id).all()
    )

    if not controls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le circuit n'a pas de postes",
        )

    # Préparer les données des contrôles
    controls_data = [
        {
            "id": c.id,
            "order": c.order,
            "control_number": c.control_number,
            "x": c.x,
            "y": c.y,
            "type": c.point_type,
            "description": c.description,
        }
        for c in controls
    ]

    # Charger les données OSM si demandé
    detector = ProblemDetector()

    if include_osm and circuit.bounds:
        try:
            bbox = BoundingBox(
                min_x=circuit.bounds.get("min_x", 0),
                min_y=circuit.bounds.get("min_y", 0),
                max_x=circuit.bounds.get("max_x", 0),
                max_y=circuit.bounds.get("max_y", 0),
            )
            fetcher = OSMFetcher()
            osm_data = fetcher.fetch(bbox)
            detector.load_osm_data(osm_data)
        except Exception as e:
            print(f"Erreur chargement OSM: {e}")

    # Analyser le circuit
    result = detector.analyze_circuit(
        circuit_id=circuit_id, controls=controls_data, bounds=circuit.bounds
    )

    # Générer le rapport
    report = detector.generate_report(result)

    return report


# =============================================
# Route: Estimation du temps d'un circuit
# =============================================
@app.get(
    "/api/v1/circuits/{circuit_id}/estimate-time",
    summary="Estime le temps de parcours d'un circuit",
    description="Calcule une estimation réaliste du temps de parcours basée sur le terrain",
)
def estimate_circuit_time_endpoint(
    circuit_id: int,
    terrain_type: str = "flat_grass",
    has_paths: bool = True,
    db: Session = Depends(get_db),
):
    """
    Estime le temps de parcours d'un circuit.

    Args:
        circuit_id: ID du circuit
        terrain_type: Type de terrain (flat_grass, light_forest, dense_forest, etc.)
        has_paths: Y a-t-il des chemins practicables ?

    Returns:
        Estimation du temps total et par interposte
    """
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les postes
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    if not controls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le circuit n'a pas de postes",
        )

    # Préparer les données
    controls_data = [
        {
            "order": c.order,
            "x": c.x,
            "y": c.y,
        }
        for c in controls
    ]

    # Calculer l'estimation
    result = estimate_circuit_time(controls_data, terrain_type, has_paths)

    return {
        "circuit_id": circuit_id,
        "terrain_type": terrain_type,
        "has_paths": has_paths,
        "estimation": result,
    }


# =============================================
# Route: Analyse d'un interposte spécifique
# =============================================
@app.get(
    "/api/v1/circuits/{circuit_id}/interpost/{from_order}/{to_order}",
    summary="Analyse un interposte spécifique",
    description="Calcule la route et évalue la qualité d'un interposte",
)
def analyze_interpost(
    circuit_id: int,
    from_order: int,
    to_order: int,
    db: Session = Depends(get_db),
):
    """
    Analyse un interposte spécifique.

    Args:
        circuit_id: ID du circuit
        from_order: Numéro du poste de départ
        to_order: Numéro du poste d'arrivée

    Returns:
        Analyse de l'interposte avec route et qualité
    """
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les postes
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    # Trouver les postes concernés
    from_control = None
    to_control = None

    for c in controls:
        if c.order == from_order:
            from_control = c
        if c.order == to_order:
            to_control = c

    if not from_control:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Poste de départ {from_order} non trouvé",
        )

    if not to_control:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Poste d'arrivée {to_order} non trouvé",
        )

    # Analyser l'interposte
    calculator = RouteCalculator()

    from_data = {
        "order": from_control.order,
        "x": from_control.x,
        "y": from_control.y,
    }
    to_data = {
        "order": to_control.order,
        "x": to_control.x,
        "y": to_control.y,
    }

    analysis = calculator.analyze_interpost(from_data, to_data)

    return {
        "circuit_id": circuit_id,
        "interpost": {
            "from_order": from_order,
            "to_order": to_order,
        },
        "direct_distance": analysis.direct_distance,
        "route_distance": analysis.route_distance,
        "route_time": analysis.route_time,
        "route_quality": analysis.route_quality,
        "choices_available": analysis.choices_available,
        "navigation_difficulty": analysis.navigation_difficulty,
    }


# =============================================
# Sprint 6: Base de connaissances RAG
# =============================================

# Instance globale de l'assistant (à améliorer avec injection de dépendances)
_assistant: AIAssistant = None
_rag_builder: RAGBuilder = None


def get_assistant() -> AIAssistant:
    """Récupère ou crée l'assistant IA."""
    global _assistant, _rag_builder

    if _assistant is None:
        _rag_builder = RAGBuilder(persist_directory="./data/vector_store")
        _assistant = AIAssistant(rag_builder=_rag_builder)

    return _assistant


@app.get(
    "/api/v1/knowledge/stats",
    summary="Statistiques de la base de connaissances",
    description="Retourne les statistiques de l'index vectoriel",
)
def get_knowledge_stats():
    """Retourne les statistiques de la base."""
    assistant = get_assistant()
    stats = assistant.rag.get_stats() if assistant.rag else {}

    return {
        "status": "ok",
        "rag_stats": stats,
    }


@app.post(
    "/api/v1/knowledge/index-document",
    summary="Indexe un document",
    description="Ajoute un document à la base de connaissances",
)
def index_document(
    content: str,
    source: str,
    source_type: str = "document",
):
    """Indexe un document dans le RAG."""
    assistant = get_assistant()

    if not assistant.rag:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG non initialisé",
        )

    # Ajouter le document
    from src.services.knowledge_base import KnowledgeChunk
    import uuid

    chunk = KnowledgeChunk(
        chunk_id=str(uuid.uuid4()),
        content=content,
        source=source,
        source_type=source_type,
    )

    success = assistant.rag.add_chunk(chunk)

    return {
        "success": success,
        "chunk_id": chunk.chunk_id,
        "source": source,
    }


@app.get(
    "/api/v1/knowledge/search",
    summary="Recherche dans la base",
    description="Recherche des informations dans la base de connaissances",
)
def search_knowledge(
    query: str,
    n_results: int = 5,
):
    """Recherche dans la base."""
    assistant = get_assistant()

    if not assistant.rag:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG non initialisé",
        )

    results = assistant.rag.search(query, n_results=n_results)

    return {
        "query": query,
        "results": [
            {
                "content": r.content[:500],  # Limiter la taille
                "source": r.source,
                "source_type": r.source_type,
                "score": r.score,
            }
            for r in results
        ],
    }


@app.post(
    "/api/v1/knowledge/ask",
    summary="Pose une question à l'assistant",
    description="Pose une question à l'assistant IA sur le traçage",
)
def ask_assistant(
    question: str,
    context: dict = None,
):
    """Pose une question à l'assistant."""
    assistant = get_assistant()

    response = assistant.ask(question, context=context)

    return {
        "question": question,
        "answer": response.answer,
        "sources": response.sources,
        "model": response.model,
    }


@app.post(
    "/api/v1/knowledge/analyze-circuit",
    summary="Analyse un circuit avec l'IA",
    description="Demande à l'assistant d'analyser un circuit existant",
)
def analyze_circuit_with_ai(
    circuit_id: int,
    question: str = None,
    db: Session = Depends(get_db),
):
    """Analyse un circuit avec l'IA."""
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les problèmes si disponibles
    detector = ProblemDetector()
    controls = (
        db.query(ControlPoint).filter(ControlPoint.circuit_id == circuit_id).all()
    )

    controls_data = [
        {
            "id": c.id,
            "order": c.order,
            "x": c.x,
            "y": c.y,
        }
        for c in controls
    ]

    analysis_result = detector.analyze_circuit(
        circuit_id=circuit_id,
        controls=controls_data,
        bounds=circuit.bounds,
    )

    # Préparer le contexte
    circuit_context = {
        "name": circuit.name,
        "category": circuit.category,
        "length_meters": circuit.length_meters,
        "climb_meters": circuit.climb_meters,
        "number_of_controls": circuit.number_of_controls,
        "technical_level": circuit.technical_level,
        "winning_time_minutes": circuit.winning_time_minutes,
        "problems": [
            {
                "type": p.type,
                "description": p.description,
                "severity": p.severity,
            }
            for p in analysis_result.problems
        ],
    }

    # Poser la question à l'assistant
    assistant = get_assistant()
    response = assistant.analyze_circuit(circuit_context, question)

    return {
        "circuit_id": circuit_id,
        "circuit_name": circuit.name,
        "answer": response.answer,
        "sources": response.sources,
        "problems_count": len(analysis_result.problems),
    }


@app.get(
    "/api/v1/knowledge/official-documents",
    summary="Liste les documents officiels",
    description="Liste les documents officiels IOF et FFCO disponibles",
)
def get_official_documents():
    """Liste les documents officiels."""
    docs = OfficialDocuments.get_all_documents()

    return {
        "iof": docs.get("IOF_DOCUMENTS", {}),
        "ffco": docs.get("FFCO_DOCUMENTS", {}),
    }


@app.post(
    "/api/v1/knowledge/load-livelox",
    summary="Charge un événement Livelox",
    description="Récupère et indexe un événement Livelox",
)
def load_livelox_event(
    event_id: str,
    index: bool = True,
):
    """Charge un événement Livelox."""
    scraper = LiveloxScraper()
    event = scraper.get_event(event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Événement {event_id} non trouvé",
        )

    # Indexer si demandé
    if index:
        assistant = get_assistant()
        if assistant.rag:
            # Exporter en texte
            from src.services.knowledge_base.scrapers.livelox import (
                export_event_to_text,
            )

            text = export_event_to_text(event)

            chunk = KnowledgeChunk(
                chunk_id=f"livelox_{event_id}",
                content=text,
                source=event.url or f"livelox:{event_id}",
                source_type="livelox",
                metadata={"event_id": event_id},
            )
            assistant.rag.add_chunk(chunk)

    return {
        "event_id": event.livelox_id,
        "name": event.name,
        "date": event.date,
        "club": event.club,
        "courses": event.courses,
        "indexed": index,
    }


@app.post(
    "/api/v1/knowledge/reset-chat",
    summary="Reset la conversation",
    description="Reset l'historique de conversation avec l'assistant",
)
def reset_chat():
    """Reset la conversation."""
    assistant = get_assistant()
    assistant.reset_conversation()

    return {"status": "ok", "message": "Conversation resetée"}


# =============================================
# RouteGadget - Traces GPS
# =============================================


@app.get(
    "/api/v1/knowledge/routegadget/event/{event_id}",
    summary="Récupère un événement RouteGadget",
    description="Récupère les détails d'un événement RouteGadget",
)
def get_routegadget_event(event_id: str):
    """Récupère un événement RouteGadget."""
    scraper = RouteGadgetScraper()
    event = scraper.get_event(event_id)

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Événement {event_id} non trouvé",
        )

    return {
        "event_id": event.event_id,
        "name": event.name,
        "date": event.date,
        "url": event.url,
        "courses": event.courses,
    }


@app.get(
    "/api/v1/knowledge/routegadget/tracks/{event_id}",
    summary="Récupère les traces d'un événement",
    description="Récupère toutes les traces GPS d'un événement RouteGadget",
)
def get_routegadget_tracks(event_id: str, course: str = None):
    """Récupère les traces d'un événement."""
    scraper = RouteGadgetScraper()
    tracks = scraper.get_tracks(event_id, course)

    return {
        "event_id": event_id,
        "course": course,
        "total_tracks": len(tracks),
        "tracks": [
            {
                "runner": t.runner_name,
                "club": t.club,
                "course": t.course,
                "time": t.time,
            }
            for t in tracks
        ],
    }


@app.get(
    "/api/v1/knowledge/routegadget/routes/{event_id}/{course}",
    summary="Récupère les routes complètes",
    description="Récupère les routes GPS complètes d'un circuit",
)
def get_routegadget_routes(event_id: str, course: str):
    """Récupère toutes les routes d'un circuit."""
    scraper = RouteGadgetScraper()
    tracks = scraper.get_all_routes(event_id, course)

    return {
        "event_id": event_id,
        "course": course,
        "total_routes": len(tracks),
        "routes": [
            {
                "runner": t.runner_name,
                "club": t.club,
                "time": t.time,
                "route_points": len(t.route),
            }
            for t in tracks
        ],
    }


@app.get(
    "/api/v1/knowledge/routegadget/analyze/{event_id}/{course}",
    summary="Analyse les routes d'un circuit",
    description="Analyse les routes populaires d'un circuit",
)
def analyze_routegadget_routes(event_id: str, course: str):
    """Analyse les routes d'un circuit."""
    analyzer = RouteAnalyzer()
    analysis = analyzer.analyze_popular_routes(event_id, course)

    return analysis


@app.post(
    "/api/v1/knowledge/routegadget/index-routes",
    summary="Indexe les routes dans le RAG",
    description="Indexe les traces GPS dans la base de connaissances",
)
def index_routegadget_routes(
    event_id: str,
    course: str = None,
    index_full_routes: bool = False,
):
    """Indexe les routes dans le RAG."""
    scraper = RouteGadgetScraper()
    tracks = scraper.get_tracks(event_id, course)

    # Indexer dans le RAG
    assistant = get_assistant()

    if not assistant.rag:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG non initialisé",
        )

    indexed_count = 0
    for track in tracks:
        from src.services.knowledge_base.scrapers.routegadget import (
            export_track_to_text,
        )

        text = export_track_to_text(track)

        chunk = KnowledgeChunk(
            chunk_id=f"rg_{event_id}_{track.runner_name}_{track.course}",
            content=text,
            source=f"routegadget:{event_id}/{track.course}",
            source_type="routegadget",
            metadata={
                "event_id": event_id,
                "runner": track.runner_name,
                "course": track.course,
                "time": track.time,
            },
        )

        if assistant.rag.add_chunk(chunk):
            indexed_count += 1

    return {
        "event_id": event_id,
        "total_tracks": len(tracks),
        "indexed": indexed_count,
    }


# =============================================
# Étape 5d: Analyse multi-GPX consensus
# =============================================


@app.post(
    "/api/v1/analysis/multi-gpx-consensus",
    summary="Analyse multi-GPX consensus",
    description=(
        "Analyse 2-20 fichiers GPX d'une même course CO. "
        "Calcule vitesse/jambe, difficulté, consensus de tracé. "
        "Calibre OCAD_TERRAIN_MULTIPLIERS si le GeoJSON OCAD est fourni."
    ),
)
async def multi_gpx_consensus(
    gpx_files: List[UploadFile] = File(..., description="Fichiers GPX (2-30)"),
    controls_json: Optional[str] = Form(None, description="JSON [{x: lng, y: lat, order: int}, ...]. Si omis, extrait des waypoints <wpt> du premier GPX."),
    ocad_geojson: Optional[str] = Form(None, description="GeoJSON OCAD optionnel (calibration terrain)"),
    snap_radius_m: float = Form(50.0, description="Rayon de snap GPS→poste en mètres"),
    save_calibration: bool = Form(False, description="Persister la calibration dans terrain_calibration.json"),
):
    """Analyse consensus de tracés GPX pour calibration terrain et scoring difficulté.

    Si controls_json est omis, les postes sont extraits automatiquement des waypoints <wpt>
    présents dans le premier fichier GPX (format standard Livelox/OCAD/Garmin).
    """
    import json as _json
    from src.services.analysis.gpx_parser import parse_gpx, extract_waypoints
    from src.services.analysis.multi_gpx_analyzer import analyze_multi_gpx, save_terrain_calibration

    if len(gpx_files) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimum 2 fichiers GPX requis pour l'analyse consensus",
        )
    if len(gpx_files) > 30:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 30 fichiers GPX acceptés",
        )

    # Parser le GeoJSON OCAD optionnel
    geojson_data = None
    if ocad_geojson:
        try:
            geojson_data = _json.loads(ocad_geojson)
        except _json.JSONDecodeError:
            pass

    # Lire et parser chaque GPX (conserver les contenus bruts pour extraction waypoints)
    gpx_tracks = []
    raw_contents = []
    for gpx_file in gpx_files:
        try:
            content = (await gpx_file.read()).decode("utf-8", errors="replace")
            raw_contents.append(content)
            track = parse_gpx(content)
            if track:
                gpx_tracks.append(track)
        except Exception:
            pass

    # Résoudre les contrôles
    controls = []
    if controls_json:
        try:
            controls = _json.loads(controls_json)
            if not isinstance(controls, list) or len(controls) < 2:
                raise ValueError()
        except (ValueError, _json.JSONDecodeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="controls_json invalide : liste d'au moins 2 postes [{x, y, order}] requise",
            )
    else:
        # Auto-extraction depuis les waypoints du premier GPX
        for raw in raw_contents:
            wpts = extract_waypoints(raw)
            if len(wpts) >= 2:
                controls = [
                    {"x": w["lon"], "y": w["lat"], "order": i}
                    for i, w in enumerate(wpts)
                ]
                break

    if len(gpx_tracks) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Moins de 2 fichiers GPX valides ont pu être parsés",
        )

    result = analyze_multi_gpx(
        gpx_tracks=gpx_tracks,
        controls=controls,
        ocad_geojson=geojson_data,
        snap_radius_m=snap_radius_m,
    )
    result["controls_source"] = "manual" if controls_json else ("waypoints" if controls else "none")
    result["controls_count"] = len(controls)

    if save_calibration and result.get("terrain_calibration"):
        saved = save_terrain_calibration(
            result["terrain_calibration"],
            result["runners_analyzed"],
            source="multi-gpx",
        )
        result["calibration_saved"] = saved

    return result


@app.post(
    "/api/v1/analysis/routegadget-consensus",
    summary="Analyse consensus depuis RouteGadget",
    description=(
        "Récupère les traces GPS d'un événement RouteGadget et lance l'analyse consensus. "
        "Équivalent de multi-gpx-consensus mais les GPX viennent directement de RouteGadget."
    ),
)
async def routegadget_consensus(
    event_id: str = Form(..., description="ID de l'événement RouteGadget"),
    course_name: str = Form(..., description="Nom du circuit (ex: H21E)"),
    controls_json: str = Form(..., description="JSON [{x: lng, y: lat, order: int}, ...]"),
    snap_radius_m: float = Form(50.0, description="Rayon de snap GPS→poste en mètres"),
    save_calibration: bool = Form(False, description="Persister la calibration terrain"),
):
    """Analyse consensus depuis les traces RouteGadget (GPS inclus)."""
    import json as _json
    from src.services.knowledge_base.scrapers.routegadget import RouteGadgetScraper
    from src.services.analysis.multi_gpx_analyzer import (
        analyze_multi_gpx,
        routegadget_to_trackpoints,
        save_terrain_calibration,
    )

    try:
        controls = _json.loads(controls_json)
        if not isinstance(controls, list) or len(controls) < 2:
            raise ValueError()
    except (ValueError, _json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="controls_json invalide : liste d'au moins 2 postes requise",
        )

    scraper = RouteGadgetScraper()
    try:
        rg_tracks = scraper.get_all_routes(event_id, course_name)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Impossible de récupérer les traces RouteGadget : {e}",
        )

    if len(rg_tracks) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Seulement {len(rg_tracks)} trace(s) récupérée(s) — minimum 2 requis",
        )

    gpx_tracks = [routegadget_to_trackpoints(t.route) for t in rg_tracks]
    gpx_tracks = [t for t in gpx_tracks if len(t) >= 2]

    result = analyze_multi_gpx(
        gpx_tracks=gpx_tracks,
        controls=controls,
        snap_radius_m=snap_radius_m,
    )
    result["source"] = "routegadget"
    result["event_id"] = event_id
    result["course"] = course_name
    result["total_tracks_fetched"] = len(rg_tracks)

    if save_calibration and result.get("terrain_calibration"):
        saved = save_terrain_calibration(
            result["terrain_calibration"],
            result["runners_analyzed"],
            source=f"routegadget:{event_id}/{course_name}",
        )
        result["calibration_saved"] = saved

    return result


# =============================================
# Sprint 7: Génération de circuits
# =============================================


@app.post(
    "/api/v1/generation/generate",
    summary="Génère des circuits",
    description="Génère des circuits automatiquement avec GA et/ou IA",
)
def generate_circuits(body: dict = Body(...)):
    """
    Génère des circuits automatiquement.
    Accepte un corps JSON unique pour éviter l'ambiguïté FastAPI body/query.

    Corps attendu :
        bounding_box: {min_x, min_y, max_x, max_y}
        category: Catégorie (H21E, D21E, etc.)
        technical_level: Niveau technique (TD1-TD5)
        target_length_m, target_climb_m, target_controls, winning_time_minutes
        method: genetic | ai | hybrid
        num_variants: int
        map_context: str (optionnel)
        start_position: [lng, lat] (optionnel)
        forbidden_zones_polygons: [[[lat, lng], ...]] (optionnel)
        required_controls: [{lat, lng}] (optionnel)
    """
    # Extraire tous les paramètres du corps JSON
    bounding_box = body.get("bounding_box", {})
    category = body.get("category", "H21E")
    technical_level = body.get("technical_level", "TD3")
    target_length_m = float(body.get("target_length_m", 4000))
    target_climb_m = float(body.get("target_climb_m", 200))
    target_controls = int(body.get("target_controls", 10))
    winning_time_minutes = float(body.get("winning_time_minutes", 30))
    method = body.get("method", "hybrid")
    num_variants = int(body.get("num_variants", 3))
    map_context = body.get("map_context")
    start_position_raw = body.get("start_position")
    forbidden_zones_polygons = body.get("forbidden_zones_polygons") or []
    required_controls_raw = body.get("required_controls") or []
    candidate_points = body.get("candidate_points") or []

    # Convertir les polygones en format zones interdites pour le GA
    forbidden_zones = []
    for polygon in forbidden_zones_polygons:
        if isinstance(polygon, list) and len(polygon) >= 3:
            forbidden_zones.append({"coordinates": polygon})

    # Créer la requête
    request = GenerationRequest(
        bounding_box=bounding_box,
        category=category,
        technical_level=technical_level,
        target_length_m=target_length_m,
        target_climb_m=target_climb_m,
        target_controls=target_controls,
        winning_time_minutes=winning_time_minutes,
        map_context=map_context,
        forbidden_zones=forbidden_zones,
        required_controls=required_controls_raw,
        candidate_points=candidate_points,
        start_position=tuple(start_position_raw) if start_position_raw and len(start_position_raw) >= 2 else None,
    )

    # Générer
    generator = AIGenerator()
    circuits = generator.generate(request, method=method, num_variants=num_variants)

    return {
        "request": {
            "category": category,
            "technical_level": technical_level,
            "target_length_m": target_length_m,
            "target_controls": target_controls,
            "method": method,
        },
        "circuits_generated": len(circuits),
        "circuits": [
            {
                "id": c.id,
                "controls": c.controls,
                "total_length_m": c.total_length_m,
                "total_climb_m": c.total_climb_m,
                "estimated_time_minutes": c.estimated_time_minutes,
                "score": c.score,
                "generation_method": c.generation_method,
                "description": c.description,
            }
            for c in circuits
        ],
    }


@app.post(
    "/api/v1/generation/score",
    summary="Score un circuit",
    description="Évalue la qualité d'un circuit existant",
)
def score_circuit(
    controls: list,
    target_length: float = None,
    target_climb: float = None,
    category: str = None,
):
    """
    Score un circuit.

    Args:
        controls: Liste des postes [{x, y, order, ...}]
        target_length: Longueur cible
        target_climb: D+ cible
        category: Catégorie

    Returns:
        Score détaillé
    """
    scorer = CircuitScorer()
    result = scorer.score(controls, target_length, target_climb, category)

    return {
        "total_score": result.total_score,
        "grade": result.grade,
        "breakdown": {
            "length_score": result.breakdown.length_score,
            "climb_score": result.breakdown.climb_score,
            "control_distance_score": result.breakdown.control_distance_score,
            "variety_score": result.breakdown.variety_score,
            "balance_score": result.breakdown.balance_score,
            "safety_score": result.breakdown.safety_score,
        },
        "iof": {
            "td_grade": result.iof.td_grade,
            "td_label": result.iof.td_label,
            "pd_grade": result.iof.pd_grade,
            "pd_label": result.iof.pd_label,
            "climb_ratio": round(result.iof.climb_ratio, 4),
            "dog_legs": result.iof.dog_legs,
            "too_close_controls": result.iof.too_close_controls,
            "iof_valid": result.iof.iof_valid,
            "compliance_score": round(result.iof.compliance_score, 1),
        },
        "strengths": result.strengths,
        "suggestions": result.suggestions,
    }


@app.post(
    "/api/v1/generation/terrain-analyze",
    summary="Analyse terrain + évaluation ffco-iof-v7",
    description=(
        "Génère la description terrain structurée d'un parcours à partir des "
        "features OCAD/GeoJSON, puis l'envoie au modèle local ffco-iof-v7 pour "
        "une évaluation IOF experte."
    ),
)
def terrain_analyze(
    controls: list,
    ocad_features: list,
    category: str = None,
    target_length_m: float = None,
):
    """
    Analyse terrain d'un circuit via ffco-iof-v7.

    Args:
        controls: [{x, y, number, order}, ...]
        ocad_features: GeoJSON features de la carte OCAD
        category: catégorie (ex: 'M21E', 'HM', 'Blanc')
        target_length_m: longueur cible en mètres

    Returns:
        terrain_description (str) + expert_evaluation (str)
    """
    # 1. Description terrain structurée (ontologie ISOM 2017)
    terrain_desc = describe_course_terrain(
        controls=controls,
        ocad_features=ocad_features,
        category=category,
        target_length_m=target_length_m,
    )

    # 2. Évaluation par ffco-iof-v7 (modèle local Ollama)
    expert_eval = None
    model_used = None
    try:
        local_rag = LocalRAG()
        question = (
            f"Évalue ce parcours selon les règles IOF ISOM 2017 et donne "
            f"des suggestions concrètes d'amélioration :\n\n{terrain_desc}"
        )
        answer, sources = local_rag.query(question)
        expert_eval = answer
        model_used = "ffco-iof-v7 (local)"
    except Exception as e:
        expert_eval = f"Modèle local indisponible : {str(e)}"
        model_used = "unavailable"

    return {
        "terrain_description": terrain_desc,
        "expert_evaluation": expert_eval,
        "model": model_used,
    }


@app.post(
    "/api/v1/generation/compare",
    summary="Compare plusieurs circuits",
    description="Compare plusieurs circuits et les classe",
)
def compare_circuits_endpoint(circuits: list):
    """
    Compare plusieurs circuits.

    Args:
        circuits: Liste de circuits à comparer

    Returns:
        Comparaison
    """
    result = compare_circuits(circuits)

    return result


# =============================================
# RouteAI - Path Finding & Map Processing
# =============================================


@app.post(
    "/api/v1/routeai/create-grid",
    summary="Crée une grille depuis OSM",
    description="Crée une grille de navigation depuis les données OSM",
)
def create_grid_from_osm(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    resolution: float = 10.0,
):
    """
    Crée une grille de navigation depuis OSM.
    """
    # Charger OSM data (simulation)
    # Dans la réalité, récupérer depuis /api/v1/terrain/osm
    osm_data = {
        "roads": [],
        "buildings": [],
    }

    bounding_box = {
        "min_x": min_x,
        "min_y": min_y,
        "max_x": max_x,
        "max_y": max_y,
    }

    processor = MapProcessor()
    success = processor.load_from_osm(osm_data, bounding_box, resolution)

    return {
        "success": success,
        "width": processor.width,
        "height": processor.height,
        "resolution": resolution,
    }


@app.post(
    "/api/v1/routeai/find-path",
    summary="Trouve un chemin optimal",
    description="Calcule le chemin optimal entre deux points avec Dijkstra/A*",
)
def find_path(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    method: str = "a_star",
):
    """
    Trouve le chemin optimal entre deux points.
    """
    # Créer un pathfinder
    # Note: Dans la réalité, utiliser la grille créée précédemment
    processor = MapProcessor()
    pathfinder = PathFinder(processor)

    # Créer une grille vide pour la démo
    processor.width = 100
    processor.height = 100
    processor.grid = []
    for y in range(100):
        row = []
        for x in range(100):
            node = GridNode(x=x, y=y, cost=0.5, terrain_type="forest", walkable=True)
            row.append(node)
        processor.grid.append(row)

    pathfinder.grid = processor

    result = pathfinder.find_path(
        (start_x, start_y),
        (end_x, end_y),
        method=method,
    )

    if not result:
        return {
            "success": False,
            "message": "Aucun chemin trouvé",
        }

    return {
        "success": True,
        "method": method,
        "path_length": len(result.path),
        "distance": result.distance,
        "time_estimate": result.time_estimate,
        "path": [
            {"x": p[0], "y": p[1]}
            for p in result.path[:100]  # Limiter à 100 points
        ],
    }


@app.post(
    "/api/v1/routeai/solve-tsp",
    summary="Résout le TSP",
    description="Ordonne les postes en utilisant le solveur TSP",
)
def solve_tsp(
    controls: List[Dict[str, Any]],
    start_x: float = None,
    start_y: float = None,
    method: str = "nearest",
):
    """
    Résout le problème du voyageur de commerce.
    """
    # Convertir en points
    points = [(c["x"], c["y"]) for c in controls]

    if start_x is not None and start_y is not None:
        start = (start_x, start_y)
    else:
        start = None

    solver = TSPSolver()
    ordered = solver.solve(points, start=start, method=method)

    # Calculer la distance totale
    total_dist = 0
    for i in range(len(ordered) - 1):
        dx = ordered[i + 1][0] - ordered[i][0]
        dy = ordered[i + 1][1] - ordered[i][1]
        total_dist += math.sqrt(dx * dx + dy * dy)

    return {
        "success": True,
        "method": method,
        "total_controls": len(ordered),
        "total_distance": total_dist,
        "ordered_controls": [
            {"order": i + 1, "x": p[0], "y": p[1]} for i, p in enumerate(ordered)
        ],
    }


@app.post(
    "/api/v1/routeai/route-through-controls",
    summary="Route à travers plusieurs postes",
    description="Calcule la route complète à travers tous les postes",
)
def route_through_controls(
    controls: List[Dict[str, Any]],
    method: str = "a_star",
):
    """
    Calcule la route à travers plusieurs postes.
    """
    # Extraire les points
    points = [(c["x"], c["y"]) for c in controls]

    if not points:
        return {"success": False, "message": "Aucun contrôle"}

    # Créer la grille
    processor = MapProcessor()
    processor.width = 200
    processor.height = 200
    processor.grid = []
    for y in range(200):
        row = []
        for x in range(200):
            node = GridNode(x=x, y=y, cost=0.5, terrain_type="forest", walkable=True)
            row.append(node)
        processor.grid.append(row)

    pathfinder = PathFinder(processor)

    # Trouver le chemin à travers tous les points
    result = pathfinder.find_path_with_waypoints(points, method=method)

    if not result:
        return {"success": False, "message": "Aucun chemin trouvé"}

    return {
        "success": True,
        "method": method,
        "total_distance": result.distance,
        "time_estimate": result.time_estimate,
        "path_points": len(result.path),
    }


# =============================================
# Sprint 8: Support Urbain/Sprint
# =============================================


@app.get(
    "/api/v1/terrain/urban-runnability",
    summary="Calcule la runnability urbaine",
    description="Calcule la runnability pour un environnement urbain/sprint",
)
def get_urban_runnability(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    resolution: float = 5.0,
):
    """
    Calcule la runnability pour un environnement urbain.
    """
    # Créer la bounding box
    bbox = BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)

    # Récupérer les données OSM
    fetcher = OSMFetcher()
    osm_data = fetcher.fetch(bbox)

    # Calculer la runnability urbaine
    processor = UrbanOSMProcessor()
    processor.load_osm_data(
        {
            "roads": osm_data.roads,
            "buildings": osm_data.buildings,
            "barriers": osm_data.barriers,
            "green_areas": osm_data.green_areas,
        }
    )

    runnability = processor.calculate_runnability(
        bounding_box={"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
        resolution=resolution,
    )

    return {
        "bounding_box": {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
        },
        "resolution": resolution,
        "paved_percentage": runnability.paved_percentage,
        "obstacle_count": runnability.obstacle_count,
        "avg_speed_mpm": runnability.avg_speed_mpm,
    }


@app.get(
    "/api/v1/terrain/urban-valid-positions",
    summary="Trouve les positions valides pour postes",
    description="Trouve les positions valides pour les postes en environnement urbain",
)
def get_valid_positions(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    num_positions: int = 20,
):
    """
    Trouve les positions valides pour les postes en sprint.
    """
    # Récupérer OSM
    bbox = BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
    fetcher = OSMFetcher()
    osm_data = fetcher.fetch(bbox)

    # Trouver les positions
    detector = UrbanControlDetector()
    detector.load_osm_data(
        {
            "roads": osm_data.roads,
            "buildings": osm_data.buildings,
            "barriers": osm_data.barriers,
            "restricted": osm_data.restricted,
        }
    )

    positions = detector.find_valid_positions(
        bounding_box={"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
        num_positions=num_positions,
    )

    return {
        "bounding_box": {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
        },
        "valid_positions": positions,
        "total": len(positions),
    }


@app.get(
    "/api/v1/terrain/safety-zones",
    summary="Zones de sécurité urbaines",
    description="Retourne les zones de sécurité à éviter en sprint",
)
def get_safety_zones(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
):
    """
    Retourne les zones de sécurité à éviter en sprint.
    """
    bbox = BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)
    fetcher = OSMFetcher()
    osm_data = fetcher.fetch(bbox)

    processor = UrbanOSMProcessor()
    processor.load_osm_data(
        {
            "roads": osm_data.roads,
            "restricted": osm_data.restricted,
        }
    )

    zones = processor.get_safety_zones()

    return {
        "safety_zones": zones,
        "total": len(zones),
    }


@app.post(
    "/api/v1/circuits/{circuit_id}/analyze-sprint",
    summary="Analyse un circuit sprint",
    description="Analyse un circuit sprint selon les règles ISSprOM",
)
def analyze_sprint_circuit(
    circuit_id: int,
    db: Session = Depends(get_db),
):
    """
    Analyse un circuit sprint selon les règles ISSprOM 2019.
    """
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les postes
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    # Préparer les données
    controls_data = [
        {
            "id": c.id,
            "order": c.order,
            "x": c.x,
            "y": c.y,
        }
        for c in controls
    ]

    # Analyser avec le détecteur urbain
    fetcher = OSMFetcher()
    bbox = BoundingBox(
        min_x=circuit.bounds.get("min_x", 0),
        min_y=circuit.bounds.get("min_y", 0),
        max_x=circuit.bounds.get("max_x", 0),
        max_y=circuit.bounds.get("max_y", 0),
    )
    osm_data = fetcher.fetch(bbox)

    detector = UrbanControlDetector()
    detector.load_osm_data(
        {
            "roads": osm_data.roads,
            "buildings": osm_data.buildings,
            "barriers": osm_data.barriers,
            "restricted": osm_data.restricted,
        }
    )

    issues = detector.check_sprint_rules(controls_data, category="sprint")

    return {
        "circuit_id": circuit_id,
        "circuit_name": circuit.name,
        "environment": "sprint",
        "standard": "ISSprOM 2019",
        "issues": issues,
        "total_issues": len(issues),
    }


# =============================================
# Sprint 9: Exports (IOF, GPX, PDF)
# =============================================


@app.get(
    "/api/v1/circuits/{circuit_id}/export/iof",
    summary="Exporte en IOF XML",
    description="Exporte le circuit au format IOF XML 3.0",
)
def export_circuit_iof(circuit_id: int, db: Session = Depends(get_db)):
    """Exporte un circuit en format IOF XML."""
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les contrôles
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    # Préparer les données
    circuit_data = {
        "id": circuit.id,
        "name": circuit.name,
        "length_meters": circuit.length_meters,
        "climb_meters": circuit.climb_meters,
    }

    controls_data = [
        {
            "order": c.order,
            "x": c.x,
            "y": c.y,
            "code": c.symbol_code,
            "description": c.description,
        }
        for c in controls
    ]

    # Exporter
    xml_content = export_circuit_to_iof(circuit_data, controls_data)

    return {
        "format": "IOF XML 3.0",
        "circuit_id": circuit_id,
        "circuit_name": circuit.name,
        "xml": xml_content,
    }


@app.get(
    "/api/v1/circuits/{circuit_id}/export/gpx",
    summary="Exporte en GPX",
    description="Exporte le circuit au format GPX",
)
def export_circuit_gpx(circuit_id: int, db: Session = Depends(get_db)):
    """Exporte un circuit en format GPX."""
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les contrôles
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    # Préparer les données
    circuit_data = {
        "id": circuit.id,
        "name": circuit.name,
        "category": circuit.category,
    }

    controls_data = [
        {
            "order": c.order,
            "x": c.x,
            "y": c.y,
            "description": c.description or f"Contrôle {c.order}",
        }
        for c in controls
    ]

    # Exporter
    gpx_content = export_circuit_to_gpx(circuit_data, controls_data)

    return {
        "format": "GPX 1.1",
        "circuit_id": circuit_id,
        "circuit_name": circuit.name,
        "gpx": gpx_content,
    }


@app.get(
    "/api/v1/circuits/{circuit_id}/export/pdf",
    summary="Exporte en PDF",
    description="Exporte le circuit en PDF",
)
def export_circuit_pdf(circuit_id: int, db: Session = Depends(get_db)):
    """Exporte un circuit en format PDF."""
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les contrôles
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    # Préparer les données
    circuit_data = {
        "id": circuit.id,
        "name": circuit.name,
        "category": circuit.category,
        "technical_level": circuit.technical_level,
        "length_meters": circuit.length_meters,
        "climb_meters": circuit.climb_meters,
        "winning_time_minutes": circuit.winning_time_minutes,
    }

    controls_data = [
        {
            "order": c.order,
            "description": c.description or f"Contrôle {c.order}",
        }
        for c in controls
    ]

    # Exporter
    pdf_content = export_circuit_to_pdf(circuit_data, controls_data)

    return {
        "format": "PDF",
        "circuit_id": circuit_id,
        "circuit_name": circuit.name,
        "note": "PDF content returned as base64",
        "content_length": len(pdf_content),
    }


@app.get(
    "/api/v1/circuits/{circuit_id}/export/all",
    summary="Exporte en tous formats",
    description="Exporte le circuit en IOF, GPX et PDF",
)
def export_circuit_all(circuit_id: int, db: Session = Depends(get_db)):
    """Exporte un circuit dans tous les formats."""
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les contrôles
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    # Préparer les données
    circuit_data = {
        "id": circuit.id,
        "name": circuit.name,
        "category": circuit.category,
        "technical_level": circuit.technical_level,
        "length_meters": circuit.length_meters,
        "climb_meters": circuit.climb_meters,
        "winning_time_minutes": circuit.winning_time_minutes,
    }

    controls_data = [
        {
            "order": c.order,
            "x": c.x,
            "y": c.y,
            "code": c.symbol_code,
            "description": c.description or f"Contrôle {c.order}",
        }
        for c in controls
    ]

    # Exporter dans tous les formats
    iof_xml = export_circuit_to_iof(circuit_data, controls_data)
    gpx = export_circuit_to_gpx(circuit_data, controls_data)
    pdf = export_circuit_to_pdf(circuit_data, controls_data)

    return {
        "circuit_id": circuit_id,
        "circuit_name": circuit.name,
        "formats": {
            "iof": {
                "format": "IOF XML 3.0",
                "content": iof_xml,
            },
            "gpx": {
                "format": "GPX 1.1",
                "content": gpx,
            },
            "pdf": {
                "format": "PDF",
                "content_length": len(pdf),
            },
        },
    }


# =============================================
# Sprint 9b: Import KMZ/KML et IOF XML
# =============================================


@app.post(
    "/api/v1/circuits/upload-kmz",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Upload un fichier KMZ/KML",
    description="""
    Upload un fichier KMZ ou KML et le parse pour extraire les circuits.
    
    KMZ est le format Google Earth compressé.
    KML est le format Google Earth XML.
    """,
)
async def upload_kmz(
    file: UploadFile = File(..., description="Fichier KMZ ou KML"),
    db: Session = Depends(get_db),
):
    """
    Upload et parse un fichier KMZ ou KML.
    """
    # Valider l'extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".kmz", ".kml"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extension '{file_ext}' non supportée. Utiliser .kmz ou .kml",
        )

    # Sauvegarder le fichier
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = settings.UPLOAD_DIR / unique_filename

    try:
        content = await file.read()

        if len(content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE / 1024 / 1024} MB)",
            )

        with open(file_path, "wb") as f:
            f.write(content)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la sauvegarde: {str(e)}",
        )

    # Importer selon le type
    importer = KMLImporter()

    try:
        if file_ext == ".kmz":
            result = importer.import_kmz(str(file_path))
        else:
            result = importer.import_kml(str(file_path))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erreur lors de l'import: {str(e)}",
        )

    if result.status != "ok":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error or "Erreur lors de l'import",
        )

    # Convertir en circuits AItraceur
    circuits_data = convert_kmz_to_circuits(result)

    # Sauvegarder en base
    saved_circuits = []
    total_controls = 0

    for circuit_data in circuits_data:
        # Calculer les bounds
        x_coords = [c["x"] for c in circuit_data.get("controls", [])]
        y_coords = [c["y"] for c in circuit_data.get("controls", [])]

        bounds = {}
        if x_coords and y_coords:
            bounds = {
                "min_x": min(x_coords),
                "min_y": min(y_coords),
                "max_x": max(x_coords),
                "max_y": max(y_coords),
            }

        # Créer le circuit
        db_circuit = Circuit(
            name=circuit_data.get("name", "Circuit import"),
            category="imported",
            technical_level="TD3",
            length_meters=0,  # À calculer
            climb_meters=0,
            winning_time_minutes=0,
            number_of_controls=len(circuit_data.get("controls", [])),
            source_file=file.filename,
            bounds=bounds,
            crs="WGS84",
        )
        db.add(db_circuit)
        db.flush()

        # Créer les contrôles
        for ctrl in circuit_data.get("controls", []):
            db_control = ControlPoint(
                circuit_id=db_circuit.id,
                order=ctrl.get("order", 1),
                control_number=ctrl.get("order", 1),
                x=ctrl.get("x", 0),
                y=ctrl.get("y", 0),
                symbol_code=ctrl.get("code", ""),
                point_type="control",
                description=ctrl.get("description", ""),
            )
            db.add(db_control)
            total_controls += 1

        saved_circuits.append(db_circuit)

    db.commit()

    return {
        "success": True,
        "message": f"{len(circuits_data)} circuit(s) importé(s) avec succès",
        "filename": file.filename,
        "file_size": len(content),
        "format": "KMZ" if file_ext == ".kmz" else "KML",
        "circuits_found": len(circuits_data),
        "total_controls": total_controls,
        "has_map_image": result.map_image is not None,
        "map_image": None,  # Base64 encoded image - could be returned if requested
        "circuits": [
            {
                "id": c.id,
                "name": c.name,
                "number_of_controls": c.number_of_controls,
            }
            for c in saved_circuits
        ],
    }





@app.post(
    "/api/v1/circuits/upload-iof",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Upload un fichier IOF XML",
    description="""
    Upload un fichier IOF XML et le parse pour extraire les circuits.
    
    IOF XML est le standard international pour les données de CO.
    """,
)
async def upload_iof(
    file: UploadFile = File(..., description="Fichier IOF XML"),
    db: Session = Depends(get_db),
):
    """
    Upload et parse un fichier IOF XML.
    """
    # Valider l'extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".xml", ".iofx"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extension '{file_ext}' non supportée. Utiliser .xml",
        )

    # Sauvegarder le fichier
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = settings.UPLOAD_DIR / unique_filename

    try:
        content = await file.read()

        if len(content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE / 1024 / 1024} MB)",
            )

        with open(file_path, "wb") as f:
            f.write(content)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la sauvegarde: {str(e)}",
        )

    # Importer
    importer = IOFImporter()

    try:
        result = importer.import_file(str(file_path))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erreur lors de l'import: {str(e)}",
        )

    if result.status != "ok":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error or "Erreur lors de l'import",
        )

    # Convertir en circuits AItraceur
    circuits_data = convert_iof_to_circuits(result)

    # Sauvegarder en base
    saved_circuits = []
    total_controls = 0

    for circuit_data in circuits_data:
        # Calculer les bounds
        x_coords = [c["x"] for c in circuit_data.get("controls", [])]
        y_coords = [c["y"] for c in circuit_data.get("controls", [])]

        bounds = {}
        if x_coords and y_coords:
            bounds = {
                "min_x": min(x_coords),
                "min_y": min(y_coords),
                "max_x": max(x_coords),
                "max_y": max(y_coords),
            }

        # Créer le circuit
        db_circuit = Circuit(
            name=circuit_data.get("name", "Circuit import"),
            category="imported",
            technical_level="TD3",
            length_meters=circuit_data.get("length_meters", 0),
            climb_meters=circuit_data.get("climb_meters", 0),
            winning_time_minutes=0,
            number_of_controls=len(circuit_data.get("controls", [])),
            source_file=file.filename,
            bounds=bounds,
            crs="WGS84",  # ou Lambert93 selon les données
        )
        db.add(db_circuit)
        db.flush()

        # Créer les contrôles
        for ctrl in circuit_data.get("controls", []):
            db_control = ControlPoint(
                circuit_id=db_circuit.id,
                order=ctrl.get("order", 1),
                control_number=ctrl.get("order", 1),
                x=ctrl.get("x", 0),
                y=ctrl.get("y", 0),
                symbol_code=ctrl.get("code", ""),
                point_type="control",
                description=ctrl.get("description", ""),
            )
            db.add(db_control)
            total_controls += 1

        saved_circuits.append(db_circuit)

    db.commit()

    event_name = result.event.name if result.event else "Import IOF"

    return {
        "success": True,
        "message": f"{len(circuits_data)} circuit(s) importé(s) avec succès",
        "filename": file.filename,
        "file_size": len(content),
        "format": "IOF XML 3.0",
        "event_name": event_name,
        "circuits_found": len(circuits_data),
        "total_controls": total_controls,
        "circuits": [
            {
                "id": c.id,
                "name": c.name,
                "length_meters": c.length_meters,
                "climb_meters": c.climb_meters,
                "number_of_controls": c.number_of_controls,
            }
            for c in saved_circuits
        ],
    }


# =============================================
# Import IOF Course Data XML (OCAD export)
# =============================================


@app.post(
    "/api/v1/circuits/upload-xml",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Upload un fichier XML Course Data",
    description="""
    Upload un fichier XML exporté par OCAD (Course Data).
    Ce fichier contient les circuits avec coordonnées GPS.
    """,
)
async def upload_xml_course_data(
    file: UploadFile = File(..., description="Fichier XML OCAD"),
    db: Session = Depends(get_db),
):
    """
    Upload et parse un fichier XML Course Data (OCAD export).
    """
    # Valider l'extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".xml", ".courses.xml"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extension '{file_ext}' non supportée. Utiliser .xml",
        )

    # Sauvegarder le fichier
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = settings.UPLOAD_DIR / unique_filename

    try:
        content = await file.read()

        if len(content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE / 1024 / 1024} MB)",
            )

        with open(file_path, "wb") as f:
            f.write(content)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la sauvegarde: {str(e)}",
        )

    # Importer avec le nouveau parser
    from src.services.importers.iof_xml_importer import IOFXMLImporter

    try:
        importer = IOFXMLImporter()
        race_data = importer.parse(file_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erreur lors du parsing XML: {str(e)}",
        )

    # Convertir en circuits AItraceur
    saved_circuits = []
    total_controls = 0

    for course in race_data.courses:
        # Construire la liste des contrôles dans l'ordre
        controls_data = []
        for ctrl_id in course.controls:
            if ctrl_id in race_data.controls:
                ctrl = race_data.controls[ctrl_id]
                # Déterminer le type
                if ctrl.control_type == "Start":
                    point_type = "start"
                elif ctrl.control_type == "Finish":
                    point_type = "finish"
                else:
                    point_type = "control"

                controls_data.append(
                    {
                        "lat": ctrl.lat,
                        "lng": ctrl.lng,
                        "point_type": point_type,
                    }
                )

        # Calculer les bounds
        lats = [c["lat"] for c in controls_data]
        lngs = [c["lng"] for c in controls_data]

        bounds = {}
        if lats and lngs:
            bounds = {
                "min_x": min(lngs),
                "min_y": min(lats),
                "max_x": max(lngs),
                "max_y": max(lats),
            }

        # Créer le circuit
        db_circuit = Circuit(
            name=course.name,
            category="imported",
            technical_level="TD3",
            length_meters=course.length_meters,
            climb_meters=course.climb_meters,
            winning_time_minutes=0,
            number_of_controls=len(controls_data),
            source_file=file.filename,
            bounds=bounds,
            crs="WGS84",
        )
        db.add(db_circuit)
        db.flush()

        # Créer les contrôles
        for i, ctrl_data in enumerate(controls_data):
            db_control = ControlPoint(
                circuit_id=db_circuit.id,
                order=i + 1,
                control_number=i + 1,
                x=ctrl_data["lng"],  # Longitude = x
                y=ctrl_data["lat"],  # Latitude = y
                symbol_code="201.1",
                point_type=ctrl_data["point_type"],
            )
            db.add(db_control)
            total_controls += 1

        saved_circuits.append(db_circuit)

    db.commit()

    # Retrieve circuits with control points from database
    circuits_response = []
    for c in saved_circuits:
        # Query control points for this circuit
        controls = (
            db.query(ControlPoint)
            .filter(ControlPoint.circuit_id == c.id)
            .order_by(ControlPoint.order)
            .all()
        )

        circuits_response.append(
            {
                "id": c.id,
                "name": c.name,
                "category": c.category,
                "length_meters": c.length_meters,
                "climb_meters": c.climb_meters,
                "number_of_controls": c.number_of_controls,
                "control_points": [
                    {
                        "id": ctrl.id,
                        "order": ctrl.order,
                        "control_number": ctrl.control_number,
                        "x": ctrl.x,
                        "y": ctrl.y,
                        "lat": ctrl.y,  # Latitude from database
                        "lng": ctrl.x,  # Longitude from database
                        "symbol_code": ctrl.symbol_code,
                        "point_type": ctrl.point_type,
                    }
                    for ctrl in controls
                ],
            }
        )

    return {
        "success": True,
        "message": f"{len(race_data.courses)} circuit(s) importé(s) avec succès",
        "filename": file.filename,
        "file_size": len(content),
        "format": "IOF XML Course Data",
        "circuits_found": len(race_data.courses),
        "total_controls": total_controls,
        "circuits": circuits_response,
    }


# =============================================
# Export KMZ (Google Earth)
# =============================================


@app.get(
    "/api/v1/circuits/{circuit_id}/export/kml",
    summary="Exporte en KML",
    description="Exporte le circuit au format KML (Google Earth)",
)
def export_circuit_kml(circuit_id: int, db: Session = Depends(get_db)):
    """Exporte un circuit en format KML."""
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les contrôles
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    # Préparer les données
    circuit_data = {
        "id": circuit.id,
        "name": circuit.name,
        "category": circuit.category,
    }

    controls_data = [
        {
            "order": c.order,
            "x": c.x,
            "y": c.y,
            "description": c.description or f"Contrôle {c.order}",
        }
        for c in controls
    ]

    # Exporter
    kml_content = export_circuit_to_kml(circuit_data, controls_data)

    return {
        "format": "KML",
        "circuit_id": circuit_id,
        "circuit_name": circuit.name,
        "kml": kml_content,
    }


@app.get(
    "/api/v1/circuits/{circuit_id}/export/kmz",
    summary="Exporte en KMZ",
    description="Exporte le circuit au format KMZ (Google Earth compressé)",
)
def export_circuit_kmz(
    circuit_id: int, color: str = "blue", db: Session = Depends(get_db)
):
    """Exporte un circuit en format KMZ."""
    # Récupérer le circuit
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()

    if not circuit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit {circuit_id} non trouvé",
        )

    # Récupérer les contrôles
    controls = (
        db.query(ControlPoint)
        .filter(ControlPoint.circuit_id == circuit_id)
        .order_by(ControlPoint.order)
        .all()
    )

    # Préparer les données
    circuit_data = {
        "id": circuit.id,
        "name": circuit.name,
        "category": circuit.category,
    }

    controls_data = [
        {
            "order": c.order,
            "x": c.x,
            "y": c.y,
            "description": c.description or f"Contrôle {c.order}",
        }
        for c in controls
    ]

    # Exporter
    kmz_content = export_circuit_to_kmz(circuit_data, controls_data, color=color)

    # Retourner en base64 pour éviter les problèmes de caractères
    import base64

    kmz_b64 = base64.b64encode(kmz_content).decode("utf-8")

    return {
        "format": "KMZ",
        "circuit_id": circuit_id,
        "circuit_name": circuit.name,
        "color": color,
        "kmz_base64": kmz_b64,
        "note": "Contenu encodé en base64 - télécharger et décompresser pour utiliser dans Google Earth",
    }
