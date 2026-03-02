"""
Configuration des tests - AItraceur
DB SQLite en mémoire, isolée de la DB de développement.
"""
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from httpx import AsyncClient, ASGITransport
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importer les modèles avant tout pour qu'ils s'enregistrent dans Base.metadata
import src.models.circuit  # noqa: F401
from src.core.database import Base, get_db
from src.main import app

# ---- DB de test en mémoire ----
# StaticPool : toutes les connexions partagent la MÊME DB en mémoire
# (sans ça, chaque connexion SQLite crée une DB vide séparée)
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Créer les tables immédiatement (pas dans un fixture)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    """Remplace la DB de dev par la DB de test en mémoire."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Appliquer l'override immédiatement
app.dependency_overrides[get_db] = override_get_db


# ---- Fixture client partagée par tous les tests ----
@pytest_asyncio.fixture
async def client():
    """Client HTTP pour tester l'API sans serveur réel, avec DB de test."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac
