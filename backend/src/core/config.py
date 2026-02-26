# =============================================
# Configuration de l'application
# Sprint 1: Setup minimal
# =============================================

from functools import lru_cache
from typing import Optional
from pathlib import Path

from pydantic_settings import BaseSettings


# =============================================
# Classe de configuration principale
# =============================================
class Settings(BaseSettings):
    """
    Configuration de l'application.
    Les valeurs sont lues depuis les variables d'environnement.
    """

    # --- Base de données ---
    # Use SQLite for local testing, PostgreSQL for production
    DATABASE_URL: str = "sqlite:///./aitraceur.db"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- FastAPI ---
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # --- Upload de fichiers ---
    UPLOAD_DIR: Path = Path("/app/uploads")
    MAX_UPLOAD_SIZE: int = 200 * 1024 * 1024  # 200 MB (OCAD files can be large)

    # --- OCAD ---
    OCAD_SUPPORTED_VERSION: int = 12

    # --- Class Config pour Pydantic ---
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True  # Les variables d'environnement sont en majuscules


# =============================================
# Instance globale des settings
# =============================================
@lru_cache()  # Cache pour éviter de relire les vars à chaque fois
def get_settings() -> Settings:
    """
    Retourne l'instance des settings.
    Utilise @lru_cache pour ne créer l'objet qu'une seule fois.
    """
    return Settings()


# Instance globale (la plus utilisée)
settings = get_settings()
