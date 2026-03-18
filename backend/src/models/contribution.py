# =============================================
# Modèles SQLAlchemy pour la collecte ML
# Apprentissage : contributions anonymisées
# =============================================

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
)

from src.core.database import Base


class Contribution(Base):
    """
    Métadonnées anonymisées d'un circuit contribué.
    Aucune coordonnée GPS ni identifiant personnel stocké.
    """

    __tablename__ = "contributions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Métadonnées circuit (anonymes)
    circuit_type = Column(String(20), nullable=True)    # sprint, middle, long
    map_type = Column(String(20), nullable=True)        # urban, forest
    ffco_category = Column(String(10), nullable=True)   # H21E, D16, H45, Open...
    td_grade = Column(Integer, nullable=True)           # 1-5
    pd_grade = Column(Integer, nullable=True)           # 1-5
    n_controls = Column(Integer, nullable=True)
    length_m = Column(Float, nullable=True)
    climb_m = Column(Float, nullable=True)

    # Déduplication — hash SHA256 du fichier source (anonyme, non réversible)
    xml_hash = Column(String(64), nullable=True, index=True)

    # Source du pipeline : xml_ocad | gpx_osm | kmz_osm
    source_format = Column(String(20), nullable=True, default="xml_ocad")

    # Consentement
    consent_educational = Column(Boolean, default=False)  # CC BY-NC partage éducatif



class ControlFeature(Base):
    """
    Vecteur de features ML anonymisé pour un poste individuel.
    Coordonnées recentrées sur (0,0) — distances relatives uniquement.
    """

    __tablename__ = "control_features"

    id = Column(Integer, primary_key=True, index=True)
    contribution_id = Column(Integer, nullable=False, index=True)

    # Features géométriques (distances relatives, angles — sans coordonnées absolues)
    leg_distance_m = Column(Float, nullable=True)        # Distance à ce poste depuis le précédent
    leg_bearing_change = Column(Float, nullable=True)    # Changement d'angle à ce poste (degrés)
    control_position_ratio = Column(Float, nullable=True)  # Position dans le circuit (0=départ, 1=arrivée)

    # Features IOF circuit
    td_grade = Column(Integer, nullable=True)
    pd_grade = Column(Integer, nullable=True)

    # Features terrain (depuis GeoJSON ocad2geojson, optionnel)
    terrain_symbol_density = Column(Float, nullable=True)   # Nb symboles ISOM dans 50m relatif
    nearest_path_dist_m = Column(Float, nullable=True)      # Distance relative au chemin le plus proche
    control_feature_type = Column(String(50), nullable=True)  # Type de détail (knoll, depression, junction…)
    attractiveness_score = Column(Float, nullable=True)     # Score ISOM 2017 (0.15–1.0)

    # Label ML (calculé par le scorer existant)
    quality_score = Column(Float, nullable=True)  # 0–100, normalisé en 0–1 à l'usage
