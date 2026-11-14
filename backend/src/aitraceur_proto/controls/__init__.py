"""
Couche 1 — Génération des candidats postes.

Sous-modules :
    symbol_map  — Correspondance codes OCAD → types sémantiques internes
    candidate   — Classe ControlCandidate
    ocad_parser — Parsing OCAD GeoJSON / XML → liste de features sémantiques
    generator   — generate_control_candidates()
"""
from .candidate import ControlCandidate, DetailType
from .generator import generate_control_candidates
from .symbol_map import SemanticCategory, TerrainType, get_semantic_info

__all__ = [
    "ControlCandidate",
    "DetailType",
    "generate_control_candidates",
    "SemanticCategory",
    "TerrainType",
    "get_semantic_info",
]
