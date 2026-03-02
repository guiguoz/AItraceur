"""
Tests automatiques des endpoints FastAPI - AItraceur
Lancer : cd backend && pytest tests/ -v

Note : le fixture 'client' et la DB de test sont dans conftest.py
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# Tests de santé (les plus basiques - doivent toujours passer)
# ============================================================

@pytest.mark.asyncio
async def test_health(client):
    """L'API doit répondre 200 sur /health."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") in ("ok", "healthy")


@pytest.mark.asyncio
async def test_root(client):
    """La racine doit répondre."""
    response = await client.get("/")
    assert response.status_code == 200


# ============================================================
# Tests des circuits (CRUD)
# ============================================================

@pytest.mark.asyncio
async def test_list_circuits(client):
    """Lister les circuits doit retourner un objet avec une clé 'circuits'."""
    response = await client.get("/api/v1/circuits")
    assert response.status_code == 200
    data = response.json()
    # L'API retourne {"circuits": [...], "total": n, "page": n, "page_size": n}
    assert "circuits" in data
    assert isinstance(data["circuits"], list)


@pytest.mark.asyncio
async def test_get_circuit_not_found(client):
    """Un circuit inexistant doit retourner 404."""
    response = await client.get("/api/v1/circuits/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_circuit_not_found(client):
    """Supprimer un circuit inexistant doit retourner 404."""
    response = await client.delete("/api/v1/circuits/99999")
    assert response.status_code == 404


# ============================================================
# Tests du scorer IOF
# ============================================================

def test_scorer_direct():
    """Tester CircuitScorer directement (test unitaire, plus fiable que HTTP).

    Note : l'endpoint /generation/score a un problème de design (controls: list
    sans annotation Body() est ambiguë pour FastAPI). On teste la logique métier
    directement.
    """
    from src.services.generation.scorer import CircuitScorer

    scorer = CircuitScorer()
    controls = [
        {"x": 5.500, "y": 49.190, "order": 0, "type": "start"},
        {"x": 5.506, "y": 49.194, "order": 1, "type": "control"},
        {"x": 5.512, "y": 49.198, "order": 2, "type": "control"},
        {"x": 5.508, "y": 49.202, "order": 3, "type": "control"},
        {"x": 5.501, "y": 49.199, "order": 4, "type": "finish"},
    ]
    result = scorer.score(controls, target_length=3000, category="H21")

    # Le score doit être entre 0 et 100
    assert 0 <= result.total_score <= 100, f"Score hors limites: {result.total_score}"
    assert result.grade is not None
    assert result.breakdown is not None


# ============================================================
# Tests des exports
# ============================================================

@pytest.mark.asyncio
async def test_export_iof_not_found(client):
    """Export d'un circuit inexistant doit retourner 404."""
    response = await client.get("/api/v1/circuits/99999/export/iof")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_gpx_not_found(client):
    """Export GPX d'un circuit inexistant doit retourner 404."""
    response = await client.get("/api/v1/circuits/99999/export/gpx")
    assert response.status_code == 404


# ============================================================
# Tests du calcul de distance Haversine (bug #2 corrigé)
# ============================================================

def test_haversine_distance():
    """Vérifier que _calculate_length retourne des mètres cohérents."""
    import math
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.services.generation.ai_generator import AIGenerator

    gen = AIGenerator.__new__(AIGenerator)  # Sans __init__

    # Deux postes à environ 600m
    controls = [(5.500, 49.190), (5.506, 49.194)]
    length = gen._calculate_length(controls)

    # Doit être entre 500m et 800m (pas 0.007 degrés!)
    assert 500 < length < 800, f"Distance attendue ~622m, obtenu {length:.1f}m"


def test_haversine_aller_retour():
    """Distance A→B doit être égale à B→A."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.services.generation.ai_generator import AIGenerator

    gen = AIGenerator.__new__(AIGenerator)
    p1, p2 = (5.500, 49.190), (5.506, 49.194)
    d1 = gen._calculate_length([p1, p2])
    d2 = gen._calculate_length([p2, p1])
    assert abs(d1 - d2) < 0.01, f"Distance A→B ({d1:.2f}) != B→A ({d2:.2f})"


# ============================================================
# Tests de l'OSM fetcher (bug #4 corrigé)
# ============================================================

def test_osm_query_includes_all_types():
    """La requête Overpass doit inclure forêts, eau, bâtiments."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.services.terrain.osm_fetcher import OSMFetcher
    from src.services.terrain.lidar_manager import BoundingBox

    fetcher = OSMFetcher()
    bbox = BoundingBox(min_x=5.5, min_y=49.1, max_x=5.6, max_y=49.2)
    query = fetcher.build_overpass_query(bbox, ["highways", "landuse", "water", "green_areas"])

    assert "highway" in query, "La requete doit contenir highway"
    assert "landuse" in query, "La requete doit contenir landuse"
    assert "water" in query, "La requete doit contenir water"
    assert "wood" in query or "forest" in query, "La requete doit contenir wood/forest"
    assert "out body geom" in query, "La requete doit utiliser 'out body geom' pour les coordonnees"


def test_osm_query_valid_overpass_syntax():
    """La requête Overpass doit avoir la syntaxe correcte (;-séparée)."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.services.terrain.osm_fetcher import OSMFetcher
    from src.services.terrain.lidar_manager import BoundingBox

    fetcher = OSMFetcher()
    bbox = BoundingBox(min_x=5.5, min_y=49.1, max_x=5.6, max_y=49.2)
    query = fetcher.build_overpass_query(bbox)

    # Chaque ligne de filtre doit se terminer par ";"
    lines = [l.strip() for l in query.split("\n") if l.strip().startswith("way[") or l.strip().startswith("relation[")]
    for line in lines:
        assert line.endswith(";"), f"Filtre sans ';': {line}"


# ============================================================
# Tests de la protection Ollama (bug #3 corrigé)
# ============================================================

def test_ollama_fallback_on_missing():
    """demander_ollama doit retourner None si Ollama absent, sans crasher."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from unittest.mock import patch
    from src.services.knowledge_base.local_rag import demander_ollama

    # Simuler Ollama absent (FileNotFoundError)
    with patch("subprocess.run", side_effect=FileNotFoundError("ollama not found")):
        result = demander_ollama("Quelle est la longueur d'un TD3 ?", [])
        assert result is None, f"Devrait retourner None si Ollama absent, obtenu: {result}"
