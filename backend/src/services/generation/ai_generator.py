# =============================================
# Générateur IA de circuits
# Sprint 7: Génération de circuits (Forêt)
# =============================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from ..learning.ocad_patch_scorer import HeatmapCache

from .graph_builder import GraphBuilder
from .genetic_algo import GeneticAlgorithm, GenerationConfig


# =============================================
# Types de données
# =============================================
@dataclass
class GenerationRequest:
    """Requête de génération de circuit."""

    bounding_box: Dict  # {min_x, min_y, max_x, max_y}
    category: str  # "H21E", "D21E", etc.
    technical_level: str  # "TD1" à "TD5"
    target_length_m: float = 4000
    target_climb_m: float = 200
    target_controls: int = 10
    winning_time_minutes: float = 30
    circuit_type: str = "md"  # "sprint", "md", "ld", "couleur"
    start_position: Optional[Tuple[float, float]] = None
    end_position: Optional[Tuple[float, float]] = None
    forbidden_zones: List[Dict] = field(default_factory=list)
    required_controls: List[Dict] = field(default_factory=list)
    candidate_points: List[Dict] = field(default_factory=list)  # [{x, y, isom}, ...]
    map_context: Optional[str] = None  # ISOM terrain summary from OCAD GeoJSON
    heatmap_cache: Optional[HeatmapCache] = field(default=None, repr=False)
    elevation_cache: Optional[object] = field(default=None, repr=False)
    # ElevationCache — grille SRTM/IGN pour estimer D+ pendant la fitness GA.
    route_analyzer: Optional[object] = field(default=None, repr=False)
    # RouteAnalyzer OSM — si fourni, active le re-ranker choix d'itinéraire sprint.
    rules_engine: Optional[object] = field(default=None, repr=False)
    # FFCORulesEngine — source de vérité des seuils IOF/FFCO (injecté dans GenerationConfig).


@dataclass
class GeneratedCircuit:
    """Un circuit généré."""

    id: str
    controls: List[Dict]  # [{x, y, type, description}, ...]
    total_length_m: float
    total_climb_m: float
    estimated_time_minutes: float
    score: float
    generation_method: str  # "genetic"
    description: str = ""
    leg_route_choices: list = field(default_factory=list)
    # [{leg_idx, n_routes, distances_m, choice_score, similarity_ratio}, ...]


# French descriptions for ISOM 2017 codes — displayed to the traceur for each suggested control
ISOM_DESCRIPTIONS: Dict[int, str] = {
    # Terrain forms
    101: "sommet de butte",
    102: "extrémité d'épaulement",
    103: "selle / col",
    104: "crête",
    105: "sommet de colline",
    106: "pied de talus / remblai",
    107: "tertre",
    108: "butte rocheuse",
    109: "fond de dépression",
    110: "petite dépression",
    111: "trou / fosse",
    112: "creux allongé",
    113: "terrasse / plateforme",
    114: "ravin",
    115: "petite fosse",
    116: "sol creusé / excavation",
    118: "rocher isolé",
    119: "groupe de rochers",
    120: "falaise / paroi",
    # Hydrography
    201: "bord de lac / étang",
    202: "bord de marécage",
    203: "bord de marécage traversable",
    204: "zone humide",
    209: "fontaine / source",
    210: "coude de cours d'eau",
    211: "coude de petit cours d'eau",
    212: "extrémité de fossé",
    215: "bord de rivière",
    # Vegetation
    301: "angle de limite de végétation",
    302: "limite de végétation",
    303: "angle de clairière",
    304: "lisière de forêt",
    305: "angle de végétation ouverte",
    306: "extrémité de broussaille",
    308: "arbre remarquable",
    # Path network
    401: "carrefour de chemins",
    402: "croisement de chemins",
    403: "embranchement de piste",
    404: "coude de sentier",
    405: "extrémité de chemin",
    406: "extrémité d'ancien chemin",
    # Man-made features
    501: "angle de bâtiment",
    502: "ruine",
    516: "angle de clôture / haie",
    521: "angle de zone construite",
    522: "angle de zone pavée",
    529: "carrefour de chemins pavés",
}

ISOM_TERM_MAP = {
    "depression": [109, 110, 111, 112], "dépression": [109, 110, 111, 112],
    "fosse": [111], "trou": [111], "cuvette": [110],
    "rocher": [107, 108, 118, 119], "boulder": [118, 119], "bloc": [118],
    "talus": [106, 108], "ravin": [109], "erosion": [109],
    "confluent": [209, 210, 211], "ruisseau": [210, 211], "cours_eau": [210],
    "mare": [201, 202], "étang": [201, 202], "lac": [201],
    "chemin": [401, 402, 403, 404, 405, 406], "sentier": [404], "piste": [403],
    "limite_vegetation": [301, 303, 304, 306], "lisière": [301, 306],
    "crête": [102, 104, 105], "éperon": [102], "colline": [101, 102],
    "selle": [103], "col": [103], "passage": [103],
    "bâtiment": [521, 522], "mur": [516], "clôture": [516],
}


# =============================================
# Générateur IA
# =============================================
class AIGenerator:
    """Génère des circuits via l'algorithme génétique."""

    def __init__(self):
        pass

    def generate(
        self,
        request: GenerationRequest,
        num_variants: int = 3,
        method: Optional[str] = None,
    ) -> List[GeneratedCircuit]:
        """Génère des circuits via l'algorithme génétique.

        Args:
            method: Méthode de génération ("sa", "ga", ou None → défaut GA).
                    Toute autre valeur déclenche un avertissement et tombe sur GA.
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        # Aliases frontend → méthode interne
        _METHOD_ALIASES: dict = {"genetic": None, "hybrid": None}
        if method in _METHOD_ALIASES:
            method = _METHOD_ALIASES[method]

        _VALID_METHODS = {"sa", "ga", None}
        if method not in _VALID_METHODS:
            _log.warning(
                "AIGenerator.generate() : méthode '%s' inconnue, retour sur GA par défaut.", method
            )
            method = None

        if method:
            _log.debug("AIGenerator.generate() : méthode demandée = %s", method)

        return self._generate_genetic(request, num_variants)

    def _generate_genetic(
        self,
        request: GenerationRequest,
        num_variants: int,
    ) -> List[GeneratedCircuit]:
        """Génère avec l'algorithme génétique."""
        # Mode sprint : circuit de type sprint OU TD1/TD2 (débutants)
        sprint_mode = request.circuit_type == "sprint" or request.technical_level in ("TD1", "TD2")
        min_dist = 30 if sprint_mode else 60

        config = GenerationConfig(
            target_length_m=request.target_length_m,
            target_climb_m=request.target_climb_m,
            target_controls=request.target_controls,
            circuit_type=request.circuit_type or "forest",
            technical_level=int(str(request.technical_level).replace("TD", "")) if request.technical_level else 3,
            winning_time_min=request.winning_time_minutes,
            population_size=max(30, request.target_controls * 3),
            generations=max(50, request.target_controls * 7),
            bounding_box=request.bounding_box,
            min_control_distance=min_dist,
            sprint_mode=sprint_mode,
            candidate_points=request.candidate_points,
            heatmap_cache=request.heatmap_cache,
            elevation_cache=request.elevation_cache,
            rules_engine=request.rules_engine,
        )

        # Initialiser le GA
        ga = GeneticAlgorithm(config=config)

        # Graphe (simplifié)
        graph = GraphBuilder()
        graph.build_graph(request.bounding_box, include_paths=True)
        ga.set_graph(graph)

        # Positions de départ/arrivée
        start = request.start_position or (
            (request.bounding_box["min_x"] + request.bounding_box["max_x"]) / 2,
            (request.bounding_box["min_y"] + request.bounding_box["max_y"]) / 2,
        )
        end = request.end_position or start

        # Générer
        result = ga.generate(start, end, request.forbidden_zones)

        # ── Re-ranker choix d'itinéraire (post-GA, sprint uniquement) ──────────
        import time as _time_mod
        _route_choices_by_idx: list = [None] * len(result.circuits)
        if request.route_analyzer is not None and sprint_mode and result.circuits:
            _best_idx = 0
            _best_total = -1.0
            _reranker_t0 = _time_mod.time()
            for _ci, _ckt in enumerate(result.circuits[:3]):  # Top-3 max
                if _time_mod.time() - _reranker_t0 > 15.0:   # cap 15s total
                    break
                try:
                    _rc = request.route_analyzer.score_circuit_choices(
                        _ckt.controls, k=2,
                        t_deadline=_reranker_t0 + 15.0,  # deadline partagée entre tous les circuits
                    )
                    _route_choices_by_idx[_ci] = _rc
                    if _rc["total_choice_score"] > _best_total:
                        _best_total = _rc["total_choice_score"]
                        _best_idx = _ci
                except Exception:
                    pass
            if _best_idx > 0:
                result.circuits.insert(0, result.circuits.pop(_best_idx))
                _route_choices_by_idx.insert(0, _route_choices_by_idx.pop(_best_idx))
        # ────────────────────────────────────────────────────────────────────────

        # Convertir en circuits générés
        circuits = []

        for i, circuit in enumerate(result.circuits[:num_variants]):
            controls = []
            for j, pos in enumerate(circuit.controls):
                ctrl_type = (
                    "start" if j == 0
                    else "finish" if j == len(circuit.controls) - 1
                    else "control"
                )
                desc = self._describe_control(
                    pos[0], pos[1], request.candidate_points
                )
                controls.append(
                    {
                        "order": j + 1,
                        "x": pos[0],
                        "y": pos[1],
                        "type": ctrl_type,
                        "description": desc,
                    }
                )

            # Distance réelle via RouteAnalyzer pour le circuit gagnant (Mission 3)
            if request.route_analyzer is not None and i == 0:
                real_dist = 0.0
                for _li in range(len(circuit.controls) - 1):
                    _ra, _rb = circuit.controls[_li], circuit.controls[_li + 1]
                    try:
                        _route = request.route_analyzer.find_optimal_route(
                            _ra[0], _ra[1], _rb[0], _rb[1]
                        )
                        real_dist += (
                            request.route_analyzer.route_length_m(_route)
                            if _route
                            else self._calculate_length([_ra, _rb])
                        )
                    except Exception:
                        real_dist += self._calculate_length([_ra, _rb])
                total_length = real_dist
            else:
                total_length = self._calculate_length(circuit.controls)

            _leg_choices = (
                _route_choices_by_idx[i]["leg_details"]
                if i < len(_route_choices_by_idx) and _route_choices_by_idx[i]
                else []
            )

            generated = GeneratedCircuit(
                id=f"genetic_{i + 1}",
                controls=controls,
                total_length_m=total_length,
                total_climb_m=request.target_climb_m,  # Simplifié
                estimated_time_minutes=request.winning_time_minutes,
                score=circuit.fitness,
                generation_method="genetic",
                description=f"Circuit généré par algorithme génétique (génération {circuit.generation})",
                leg_route_choices=_leg_choices,
            )
            circuits.append(generated)

        return circuits

    # Cache du mapping IOF chargé une fois
    _iof_desc_map: Dict = {}
    _iof_desc_loaded: bool = False

    def _load_iof_descriptions(self) -> Dict:
        """Charge control_descriptions.json une fois et le met en cache."""
        if self.__class__._iof_desc_loaded:
            return self.__class__._iof_desc_map
        try:
            import json as _json
            from pathlib import Path
            p = Path(__file__).parent.parent.parent / "data" / "control_descriptions.json"
            data = _json.loads(p.read_text(encoding="utf-8"))
            self.__class__._iof_desc_map = data.get("isom_to_description", {})
        except Exception:
            self.__class__._iof_desc_map = {}
        self.__class__._iof_desc_loaded = True
        return self.__class__._iof_desc_map

    def _describe_control(
        self,
        x: float,
        y: float,
        candidate_points: List[Dict],
        radius_m: float = 80.0,
    ) -> str:
        """Retourne la description IOF colonne D du feature le plus proche (FFCO 2018)."""
        import math

        iof_map = self._load_iof_descriptions()
        R = 6371000.0
        best: Optional[Dict] = None
        best_d = radius_m

        for cp in candidate_points:
            dlat = math.radians(cp["y"] - y)
            dlng = math.radians(cp["x"] - x)
            lat1, lat2 = math.radians(y), math.radians(cp["y"])
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2
            d = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            if d < best_d:
                best_d = d
                best = cp

        if best is None:
            return "Position libre"

        isom = best.get("isom")
        # Feature spéciale intersection (marquée dans extractCandidatePoints)
        if best.get("_intersection"):
            return "jonction de chemins (10.2)"

        desc_info = iof_map.get(str(isom), {}) if isom else {}
        if not desc_info:
            # Fallback legacy
            return ISOM_DESCRIPTIONS.get(isom, f"ISOM {isom}") if isom else "Position libre"

        col_d = desc_info.get("col_d", "")
        name_fr = desc_info.get("name_fr", "")
        col_g = desc_info.get("col_g_hints", [])
        g_hint = f" — {col_g[0]}" if col_g else ""
        return f"{name_fr} ({col_d}){g_hint}"

    def _calculate_length(self, controls: List[Tuple[float, float]]) -> float:
        """Calcule la longueur totale en mètres (formule Haversine, coordonnées WGS84)."""
        import math

        R = 6371000.0
        total = 0.0
        for i in range(len(controls) - 1):
            p1, p2 = controls[i], controls[i + 1]
            # p = (x=lng, y=lat)
            lat1, lat2 = math.radians(p1[1]), math.radians(p2[1])
            dlat = math.radians(p2[1] - p1[1])
            dlng = math.radians(p2[0] - p1[0])
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
            total += R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return total


# =============================================
# Factory
# =============================================
def create_generator() -> AIGenerator:
    """Crée un générateur configuré."""
    return AIGenerator()
