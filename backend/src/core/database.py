# =============================================
# Configuration de la base de données
# Sprint 1: Setup PostgreSQL + SQLAlchemy
# =============================================

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

from .config import settings


# =============================================
# Moteur SQLAlchemy
# =============================================
# create_engine crée la connexion à la DB
# NullPool est utile pour les tests ou Serverless
# Pour du développement normal, enlève NullPool
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Affiche les requêtes SQL en mode debug
    pool_pre_ping=True,  # Vérifie que la connexion est encore vivante
)


# =============================================
# Session Factory
# =============================================
# SessionLocal est utilisé pour créer des sessions de DB
# Usage: db = SessionLocal()
SessionLocal = sessionmaker(
    autocommit=False,  # Il faut explicitement valider (commit)
    autoflush=False,  # Il faut explicitement envoyer en DB
    bind=engine,
)


# =============================================
# Classe de base pour les modèles
# =============================================
Base = declarative_base()


# =============================================
# Dépendance FastAPI pour avoir une session DB
# =============================================
def get_db():
    """
    Générateur de session de base de données.
    Usage dans une route FastAPI:

    @app.get("/items")
    def read_items(db: Session = Depends(get_db)):
        ...

    La session est automatiquement fermée après la requête.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
