"""
Fixtures de test pour le package aitraceur.

Les fixtures construisent des mini-cartes synthétiques sans fichier OCAD réel,
permettant de tester toutes les couches de manière isolée.
"""
from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon

from src.aitraceur.controls.candidate import ControlCandidate, DetailType
from src.aitraceur.controls.ocad_parser import SemanticFeature
from src.aitraceur.controls.symbol_map import SemanticCategory, SemanticInfo, TerrainType
from src.aitraceur.profiles import (
    CourseEnvironment,
    PROFILE_FOREST_MIDDLE_ORANGE,
    PROFILE_SPRINT_URBAN,
)


# ---------------------------------------------------------------------------
# Profils
# ---------------------------------------------------------------------------

@pytest.fixture
def forest_profile():
    return PROFILE_FOREST_MIDDLE_ORANGE


@pytest.fixture
def sprint_profile():
    return PROFILE_SPRINT_URBAN


# ---------------------------------------------------------------------------
# Mini-carte synthétique (10 candidats dans un carré 1km × 1km)
# ---------------------------------------------------------------------------

def _make_candidate(
    cid: str,
    x: float,
    y: float,
    detail: DetailType = DetailType.BOULDER,
    attr: float = 0.80,
    read: float = 0.85,
    td: int = 2,
    profile_ids: frozenset[str] | None = None,
) -> ControlCandidate:
    pids = profile_ids or frozenset({
        PROFILE_FOREST_MIDDLE_ORANGE.id,
        PROFILE_SPRINT_URBAN.id,
    })
    return ControlCandidate(
        id=cid,
        geom=Point(x, y),
        detail_type=detail,
        attractiveness_score=attr,
        readability_score=read,
        isolation_score=0.8,
        technical_level=td,
        allowed_profiles=pids,
        source_sym=204,
        description_fr="Test candidat",
    )


@pytest.fixture
def ten_candidates():
    """10 candidats répartis dans un carré 0–1000 m × 0–1000 m."""
    positions = [
        (100, 100, DetailType.KNOLL, 0.75),
        (200, 800, DetailType.BOULDER, 0.90),
        (400, 200, DetailType.DEPRESSION, 0.85),
        (500, 600, DetailType.STREAM_JUNCTION, 0.70),
        (600, 300, DetailType.BOULDER, 0.88),
        (700, 700, DetailType.WALL_CORNER, 0.72),
        (800, 100, DetailType.PATH_JUNCTION, 0.65),
        (300, 500, DetailType.CLIFF_FOOT, 0.78),
        (650, 450, DetailType.POND_EDGE, 0.60),
        (150, 650, DetailType.EARTHWALL_END, 0.68),
    ]
    return [
        _make_candidate(f"c{i}", x, y, dt, attr, attr * 0.95)
        for i, (x, y, dt, attr) in enumerate(positions)
    ]


@pytest.fixture
def simple_geojson():
    """GeoJSON minimal avec 3 boulders + 1 chemin + 1 zone interdite."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "b1",
                "geometry": {"type": "Point", "coordinates": [2.3, 48.8]},
                "properties": {"sym": 204},
            },
            {
                "type": "Feature",
                "id": "b2",
                "geometry": {"type": "Point", "coordinates": [2.31, 48.81]},
                "properties": {"sym": 204},
            },
            {
                "type": "Feature",
                "id": "b3",
                "geometry": {"type": "Point", "coordinates": [2.32, 48.79]},
                "properties": {"sym": 111},  # knoll
            },
            {
                "type": "Feature",
                "id": "path1",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[2.29, 48.79], [2.33, 48.82]],
                },
                "properties": {"sym": 504},  # path
            },
            {
                "type": "Feature",
                "id": "oob1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2.305, 48.805], [2.315, 48.805],
                                     [2.315, 48.815], [2.305, 48.815],
                                     [2.305, 48.805]]],
                },
                "properties": {"sym": 707},  # out of bounds
            },
        ],
    }


@pytest.fixture
def simple_semantic_features(ten_candidates):
    """
    Simule des SemanticFeature correspondant aux 10 candidats.
    Utilisé pour tester le MovementModel sans parsing OCAD réel.
    """
    from src.aitraceur.controls.symbol_map import get_semantic_info

    features = []
    for cand in ten_candidates:
        info = get_semantic_info(204)  # boulder
        features.append(SemanticFeature(
            fid=cand.id,
            geom=cand.geom,
            geom_type="Point",
            info=info,
            sym=204,
        ))

    # Ajout d'un chemin linéaire
    path_info = get_semantic_info(504)
    features.append(SemanticFeature(
        fid="path_main",
        geom=LineString([(100, 100), (500, 600), (800, 100)]),
        geom_type="LineString",
        info=path_info,
        sym=504,
    ))

    # Zone de végétation surfacique
    veg_info = get_semantic_info(306)  # slow forest
    features.append(SemanticFeature(
        fid="veg_zone",
        geom=Polygon([(300, 200), (700, 200), (700, 500), (300, 500), (300, 200)]),
        geom_type="Polygon",
        info=veg_info,
        sym=306,
    ))

    return features
