# =============================================
# Modèles SQLAlchemy pour les circuits CO
# Sprint 1: Upload OCAD & Affichage Carte
# =============================================

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Enum,
    JSON,
)
from sqlalchemy.orm import relationship

from src.core.database import Base


# =============================================
# Modèle: Circuit (un parcours)
# =============================================
class Circuit(Base):
    """
    Représente un circuit de course d'orientation.
    Un circuit appartient à un événement (course).
    """

    __tablename__ = "circuits"

    # --- Colonnes ---
    id = Column(Integer, primary_key=True, index=True)

    # Nom du circuit (ex: "H21E", "D35", "Circuit A")
    name = Column(String(100), nullable=False)

    # Catégorie (ex: "H21E", "D35", "H/D-14")
    category = Column(String(20), nullable=True)

    # Difficulté technique (1-5, TD1 à TD5)
    technical_level = Column(Integer, nullable=True)  # 1-5

    # Longueur estimée en mètres
    length_meters = Column(Float, nullable=True)

    # Dénivelé cumulé en mètres
    climb_meters = Column(Float, nullable=True)

    # Temps gagnant estimé en minutes
    winning_time_minutes = Column(Float, nullable=True)

    # Type de course: classic, middle, sprint, score, relay
    course_type = Column(String(20), default="classic")

    # Type d'environnement: forest, urban, park, mixed
    environment_type = Column(String(20), default="forest")

    # Nombre de postes
    number_of_controls = Column(Integer, nullable=True)

    # Nom du fichier OCAD source
    source_file = Column(String(255), nullable=True)

    # Emprise du circuit (bounds en JSON: {min_x, min_y, max_x, max_y})
    bounds = Column(JSON, nullable=True)

    # CRS (projection) - exemple: "EPSG:4326" ou "EPSG:2154" (Lambert-93)
    crs = Column(String(50), nullable=True)

    # Métadonnées additionnelles en JSON
    extra_data = Column(JSON, nullable=True)

    # Date de création
    created_at = Column(DateTime, default=datetime.utcnow)

    # Date de mise à jour
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- Relations ---
    # Un circuit a plusieurs postes
    control_points = relationship(
        "ControlPoint",
        back_populates="circuit",
        cascade="all, delete-orphan",  # Supprime les postes si on supprime le circuit
        order_by="ControlPoint.order",
    )

    def __repr__(self):
        return f"<Circuit(id={self.id}, name='{self.name}', controls={self.number_of_controls})>"


# =============================================
# Modèle: ControlPoint (un poste)
# =============================================
class ControlPoint(Base):
    """
    Représente un poste (point de contrôle) sur un circuit.
    """

    __tablename__ = "control_points"

    # --- Colonnes ---
    id = Column(Integer, primary_key=True, index=True)

    # Clé étrangère vers le circuit
    circuit_id = Column(
        Integer,
        ForeignKey("circuits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Ordre du poste dans le circuit (1 = départ, 2 = poste 1, etc.)
    order = Column(Integer, nullable=False)

    # Numéro du poste (ex: 31, 32, 33...)
    control_number = Column(Integer, nullable=True)

    # Coordonnées
    x = Column(Float, nullable=False)  # X (longitude ou est)
    y = Column(Float, nullable=False)  # Y (latitude ou nord)

    # Code du poste (symbole OCAD, ex: "201.1" pour un Poste obligatoire)
    symbol_code = Column(String(50), nullable=True)

    # Type de poste
    point_type = Column(
        Enum("start", "control", "finish", name="point_type_enum"), default="control"
    )

    # Description du poste (ex: "croisement de chemins", "rocher")
    description = Column(Text, nullable=True)

    # Métadonnées additionnelles
    extra_data = Column(JSON, nullable=True)

    # --- Relations ---
    circuit = relationship("Circuit", back_populates="control_points")

    def __repr__(self):
        return f"<ControlPoint(id={self.id}, order={self.order}, type='{self.point_type}')>"
