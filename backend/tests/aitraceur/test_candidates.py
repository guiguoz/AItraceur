"""
Tests — Couche 1 : génération des candidats postes.

Couvre :
  - symbol_map : résolution des codes OCAD
  - ocad_parser : parsing GeoJSON
  - generator : generate_control_candidates()
"""
from __future__ import annotations

import pytest

from src.aitraceur.controls.symbol_map import (
    SemanticCategory,
    TerrainType,
    get_semantic_info,
    is_forbidden,
    is_layout,
)
from src.aitraceur.controls.ocad_parser import (
    parse_geojson,
    extract_forbidden_zones,
    extract_linear_features,
)
from src.aitraceur.controls.generator import generate_control_candidates
from src.aitraceur.controls.candidate import DetailType


class TestSymbolMap:
    def test_boulder_is_rock(self):
        info = get_semantic_info(204)
        assert info.category == SemanticCategory.ROCK
        assert info.terrain_type == TerrainType.BOULDER

    def test_boulder_high_attractiveness(self):
        info = get_semantic_info(204)
        assert info.attractiveness >= 0.85
        assert info.base_td >= 1

    def test_north_line_is_layout(self):
        assert is_layout(601) is True
        assert is_layout(602) is True

    def test_out_of_bounds_is_forbidden(self):
        assert is_forbidden(707) is True

    def test_impassable_cliff_is_forbidden(self):
        assert is_forbidden(201) is True

    def test_unknown_code_returns_unknown_category(self):
        info = get_semantic_info(9999)
        assert info.category == SemanticCategory.UNKNOWN

    def test_float_code_accepted(self):
        info = get_semantic_info(204.0)
        assert info.terrain_type == TerrainType.BOULDER

    def test_course_elements_are_layout(self):
        for code in [701, 702, 703, 704, 705]:
            assert is_layout(code), f"Code {code} devrait être layout"

    def test_knoll_td_reasonable(self):
        info = get_semantic_info(111)
        assert 1 <= info.base_td <= 3

    def test_building_is_forbidden_area(self):
        # Bâtiment = zone interdite (infranchissable)
        assert is_forbidden(521) is True


class TestGeoJSONParser:
    def test_basic_parse(self, simple_geojson):
        features = parse_geojson(simple_geojson)
        # On attend boulders + knoll + path. OOB n'est pas layout mais forbidden.
        assert len(features) >= 3

    def test_layout_skipped_by_default(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [2.3, 48.8]},
                    "properties": {"sym": 601},   # north line = layout
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [2.3, 48.8]},
                    "properties": {"sym": 204},   # boulder = pas layout
                },
            ],
        }
        features = parse_geojson(geojson, skip_layout=True)
        assert all(not f.is_layout for f in features)
        assert len(features) == 1

    def test_forbidden_zones_extracted(self, simple_geojson):
        features = parse_geojson(simple_geojson)
        zones = extract_forbidden_zones(features)
        assert len(zones) >= 1

    def test_linear_features_extracted(self, simple_geojson):
        features = parse_geojson(simple_geojson)
        lines = extract_linear_features(features)
        assert len(lines) >= 1
        assert all(f.is_linear for f in lines)

    def test_empty_geojson(self):
        features = parse_geojson({"type": "FeatureCollection", "features": []})
        assert features == []

    def test_missing_sym_skipped(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [2.3, 48.8]},
                    "properties": {},   # pas de sym
                },
            ],
        }
        features = parse_geojson(geojson)
        assert len(features) == 0


class TestGenerateCandidates:
    def test_basic_generation(self, simple_geojson, forest_profile):
        features = parse_geojson(simple_geojson)
        # Les coordonnées sont en WGS84 (degrés), on réduit le buffer interdit
        # pour éviter qu'il couvre toute la carte (5m ≈ 0.00005° en latitude)
        candidates = generate_control_candidates(
            features, forest_profile, forbidden_buffer_m=0.00005
        )
        # Boulder + knoll doivent générer des candidats
        assert len(candidates) >= 1

    def test_all_candidates_have_geom(self, simple_geojson, forest_profile):
        features = parse_geojson(simple_geojson)
        candidates = generate_control_candidates(features, forest_profile)
        for c in candidates:
            assert c.geom is not None
            assert c.geom.geom_type == "Point"

    def test_candidates_sorted_by_score(self, simple_geojson, forest_profile):
        features = parse_geojson(simple_geojson)
        candidates = generate_control_candidates(features, forest_profile)
        scores = [c.composite_score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_no_candidates_in_forbidden_zone(self, simple_geojson, forest_profile):
        """Aucun candidat ne doit tomber dans la zone hors-limites du GeoJSON."""
        features = parse_geojson(simple_geojson)
        forbidden_zones = extract_forbidden_zones(features)
        candidates = generate_control_candidates(
            features, forest_profile, forbidden_buffer_m=0.00005
        )
        from shapely.ops import unary_union
        if forbidden_zones:
            # En WGS84 : 0.00005° ≈ 5m de buffer
            forbidden_geom = unary_union([z.buffer(0.00005) for z in forbidden_zones])
            for c in candidates:
                assert not forbidden_geom.contains(c.geom), (
                    f"Candidat {c.id} dans une zone interdite"
                )

    def test_minimum_separation(self, simple_geojson, forest_profile):
        """Deux candidats ne doivent pas être à moins de min_separation."""
        features = parse_geojson(simple_geojson)
        # En WGS84 : 0.0001° ≈ 11m
        min_sep = 0.0001
        candidates = generate_control_candidates(
            features, forest_profile,
            min_separation_m=min_sep, forbidden_buffer_m=0.00005,
        )
        for i, c1 in enumerate(candidates):
            for j, c2 in enumerate(candidates):
                if i < j:
                    d = c1.geom.distance(c2.geom)
                    assert d >= min_sep * 0.95, (
                        f"Candidats {c1.id} et {c2.id} trop proches : {d:.1f}m"
                    )

    def test_profile_filtering(self, simple_geojson, sprint_profile):
        """En sprint, les boulders ne sont pas autorisés (pas dans les catégories sprint)."""
        features = parse_geojson(simple_geojson)
        candidates = generate_control_candidates(
            features, sprint_profile, forbidden_buffer_m=0.00005
        )
        # Boulder est ROCK, sprint n'autorise pas ROCK
        # → devrait avoir moins de candidats ou 0
        boulder_candidates = [
            c for c in candidates if c.detail_type == DetailType.BOULDER
        ]
        # Boulder (ROCK) non autorisé en sprint
        assert len(boulder_candidates) == 0
