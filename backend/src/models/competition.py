# =============================================
# Modèle SQLAlchemy — Compétition CO
# Phase 4: Mode Compétition (multi-circuits)
# =============================================

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON, String

from src.core.database import Base


class Competition(Base):
    """
    Représente une compétition CO : plusieurs circuits partageant une même carte.
    L'intégralité de l'état frontend (circuits, balises, carte OCAD) est stockée
    dans le blob JSON `data` pour simplifier save/load sans migration relationnelle.
    """

    __tablename__ = "competitions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Blob JSON : { circuits[], activeCircuitId, ocadMapId, ocadBounds }
    data = Column(JSON, nullable=False, default=dict)

    def __repr__(self):
        return f"<Competition(id={self.id!r}, name={self.name!r})>"
