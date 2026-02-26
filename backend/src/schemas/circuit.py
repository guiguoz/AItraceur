# =============================================
# Schémas Pydantic pour les circuits CO
# Sprint 1: Upload OCAD & Affichage Carte
# =============================================

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# =============================================
# Schéma: Point de contrôle (réponse)
# =============================================
class ControlPointResponse(BaseModel):
    """
    Schéma d'un point de contrôle (poste) pour les réponses API.
    """

    id: int
    circuit_id: int
    order: int
    control_number: Optional[int] = None
    x: float = Field(..., description="Coordonnée X (longitude ou est)")
    y: float = Field(..., description="Coordonnée Y (latitude ou nord)")
    symbol_code: Optional[str] = None
    point_type: str = Field(..., description="Type: start, control, finish")
    description: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None

    # Configuration du modèle
    model_config = ConfigDict(from_attributes=True)

    # Exemple pour la documentation
    model_config["json_schema_extra"] = {
        "example": {
            "id": 1,
            "circuit_id": 1,
            "order": 1,
            "control_number": 31,
            "x": 6.123456,
            "y": 48.123456,
            "symbol_code": "201.1",
            "point_type": "control",
            "description": "Croisement de chemins",
            "extra_data": {},
        }
    }


# =============================================
# Schéma: Circuit (réponse complète)
# =============================================
class CircuitResponse(BaseModel):
    """
    Schéma complet d'un circuit pour les réponses API.
    """

    id: int
    name: str
    category: Optional[str] = None
    technical_level: Optional[int] = Field(None, ge=1, le=5, description="TD1 à TD5")
    length_meters: Optional[float] = None
    climb_meters: Optional[float] = None
    winning_time_minutes: Optional[float] = None
    course_type: str = "classic"
    environment_type: str = "forest"
    number_of_controls: Optional[int] = None
    source_file: Optional[str] = None
    bounds: Optional[Dict[str, float]] = None
    crs: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    # Inclure les postes liés
    control_points: List[ControlPointResponse] = []

    # Configuration du modèle
    model_config = ConfigDict(from_attributes=True)


# =============================================
# Schéma: Circuit (création)
# =============================================
class CircuitCreate(BaseModel):
    """
    Schéma pour créer un nouveau circuit.
    """

    name: str = Field(..., min_length=1, max_length=100)
    category: Optional[str] = None
    technical_level: Optional[int] = Field(None, ge=1, le=5)
    length_meters: Optional[float] = None
    climb_meters: Optional[float] = None
    winning_time_minutes: Optional[float] = None
    course_type: str = "classic"
    environment_type: str = "forest"
    number_of_controls: Optional[int] = None
    source_file: Optional[str] = None
    bounds: Optional[Dict[str, float]] = None
    crs: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


# =============================================
# Schéma: Circuit (mise à jour)
# =============================================
class CircuitUpdate(BaseModel):
    """
    Schéma pour mettre à jour un circuit existant.
    Tous les champs sont optionnels.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    category: Optional[str] = None
    technical_level: Optional[int] = Field(None, ge=1, le=5)
    length_meters: Optional[float] = None
    climb_meters: Optional[float] = None
    winning_time_minutes: Optional[float] = None
    course_type: Optional[str] = None
    environment_type: Optional[str] = None
    number_of_controls: Optional[int] = None
    crs: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


# =============================================
# Schéma: Liste de circuits (réponse paginée)
# =============================================
class CircuitListResponse(BaseModel):
    """
    Schéma pour une liste de circuits avec pagination.
    """

    circuits: List[CircuitResponse]
    total: int = Field(..., description="Nombre total de circuits")
    page: int = Field(1, description="Numéro de page")
    page_size: int = Field(50, description="Taille de page")


# =============================================
# Schéma: Réponse d'upload OCAD
# =============================================
class OCADUploadResponse(BaseModel):
    """
    Schéma de réponse après l'upload d'un fichier OCAD.
    """

    success: bool = Field(..., description="True si l'upload a réussi")
    message: str = Field(..., description="Message descriptif")
    filename: str = Field(..., description="Nom du fichier uploadé")
    file_size: int = Field(..., description="Taille du fichier en bytes")
    circuits_found: int = Field(..., description="Nombre de circuits trouvés")
    total_controls: int = Field(..., description="Nombre total de postes")
    bounds: Optional[Dict[str, float]] = Field(None, description="Emprise du fichier")
    crs: Optional[str] = Field(None, description="Système de projection détecté")
    environment_type: Optional[str] = Field(
        None, description="Type détecté: forest/urban/park/mixed"
    )

    # Les circuits parsés
    circuits: List[CircuitResponse] = Field(default_factory=list)
