# =============================================
# Générateur IA de circuits
# Sprint 7: Génération de circuits (Forêt)
# =============================================

from __future__ import annotations

from dataclasses import dataclass, field, replace as _dc_replace
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import json
import logging
import pathlib
import numpy as np

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..learning.ocad_patch_scorer import HeatmapCache

from .graph_builder import GraphBuilder
from .genetic_algo import GeneticAlgorithm, GenerationConfig, scale_min_separation, _haversine_batch
from .profiling.course_profile import compute_course_profile
from .profiling.profile_distance import cosine_distance, course_profile_vector, select_diverse_circuits

# ── Seuils Couche 1 (chargés une fois au démarrage) ───────────────────────────
_THRESHOLDS_PATH = pathlib.Path(__file__).parent / "profiling" / "label_thresholds.json"
try:
    LABEL_THRESHOLDS: dict = json.loads(_THRESHOLDS_PATH.read_text(encoding="utf-8"))
except Exception:
    LABEL_THRESHOLDS = {}

# ── Constantes diversification inter-runs ──────────────────────────────────────
DIVERSITY_FITNESS_RATIO = 0.95       # filtre qualité : fitness >= ratio × best
DIVERSITY_DUPLICATE_THRESHOLD = 0.0002  # seuil dédoublonnage cosinus (intra-run ≈0.0001, inter-run ≈0.001+)


def _spatial_cluster_candidates(
    candidates: list[tuple[float, float]],
    n_clusters: int,
) -> list[list[tuple[float, float]]]:
    """Partition spatiale selon l'axe de plus grande variance (lng ou lat).

    Chaque run GA reçoit une zone géographique distincte pour le seeding,
    forçant la diversité spatiale sans toucher à la fitness.
    Fallback : si pas assez de candidats, tous les runs reçoivent la liste complète.
    """
    if len(candidates) < n_clusters * 3:
        return [candidates] * n_clusters
    lngs = [c[0] for c in candidates]
    lats = [c[1] for c in candidates]
    lng_range = max(lngs) - min(lngs)
    lat_range = max(lats) - min(lats)
    axis = 0 if lng_range >= lat_range else 1  # 0=lng, 1=lat
    sorted_c = sorted(candidates, key=lambda c: c[axis])
    size = max(1, len(sorted_c) // n_clusters)
    return [
        sorted_c[i * size:(i + 1) * size if i < n_clusters - 1 else len(sorted_c)]
        for i in range(n_clusters)
    ]


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
    map_scale: Optional[int] = None  # échelle OCAD (ex: 4000 pour 1:4000)
    ocad_line_segments: List[Dict] = field(default_factory=list)
    # Segments LineString OCAD [{p0, p1, isom_code}] — termes N/O/P forêt.
    segment_index: Optional[object] = field(default=None, repr=False)
    # SegmentSpatialIndex pré-construit (depuis preprocess-ocad) — évite la reconstruction en GA.
    w_dist_override: Optional[float] = None  # override W_DIST pour expériences de calibration
    ga_seed: Optional[int] = None            # seed déterministe pour reproductibilité inter-runs
    w_diversity_mult: float = 1.0            # multiplicateur W_LEG_DIVERSITY pour expériences
    latent_regime: Optional[str] = None     # régime latent cible (post-sélection LRI)
    n_runs: int = 3                          # nombre de runs GA pour le pool inter-runs
    top_k_per_run: int = 10                  # circuits retenus par run dans le pool
    diversity_fitness_ratio: float = DIVERSITY_FITNESS_RATIO  # filtre qualité pool


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
    nav_scores: list = field(default_factory=list)
    # [{attack, catch, handrail}] par jambe — rempli une seule fois sur le circuit final
    label: list = field(default_factory=list)  # Couche 1 : ["Exploratoire", "A choix", ...]
    profile_title: str = ""                     # Couche 1 : "Exploratoire, Rythme"
    scenario: str = ""                          # Couche 2 : "concentré"|"traversée"|"traversée_contrastée"|"standard"


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
    # Vegetation ponctuels ISOM 2017
    415: "bouquet d'arbres",
    416: "arbre remarquable",
    417: "souche",
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
        """Génère avec l'algorithme génétique — N runs, pool inter-runs, sélection cosinus."""
        import time as _time_mod

        sprint_mode = request.circuit_type == "sprint" or request.technical_level in ("TD1", "TD2")
        _base_dist = 30 if sprint_mode else 60
        min_dist = scale_min_separation(_base_dist, request.map_scale, request.circuit_type or "md")

        base_config = GenerationConfig(
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
            route_analyzer=request.route_analyzer,
            rules_engine=request.rules_engine,
            map_scale=request.map_scale,
            ocad_line_segments=request.ocad_line_segments,
            segment_index=request.segment_index,
            w_dist_override=request.w_dist_override,
            ga_seed=request.ga_seed,
            w_diversity_mult=request.w_diversity_mult,
            latent_regime=request.latent_regime,
        )

        # Sprint 3.5d — audit signal terrain : heatmap + gradient ISOM
        if request.heatmap_cache is not None and getattr(request.heatmap_cache, 'is_flat_signal', False):
            _n_cands = len(request.candidate_points) if request.candidate_points else 0
            _isom_info = f"{_n_cands} candidats (gradient attendu)" if _n_cands > 0 else "0 candidats → CONSTANT 50.0 (double signal plat)"
            log.warning(
                "[terrain-audit] heatmap plat (std=%.4f) | ISOM fallback: %s",
                getattr(request.heatmap_cache, 'scores_std', 0.0),
                _isom_info,
            )

        # Graphe OSM — construit une seule fois, partagé entre tous les runs
        graph = GraphBuilder()
        graph.build_graph(request.bounding_box, include_paths=True)

        start = request.start_position or (
            (request.bounding_box["min_x"] + request.bounding_box["max_x"]) / 2,
            (request.bounding_box["min_y"] + request.bounding_box["max_y"]) / 2,
        )
        end = request.end_position or start

        # ── A8 : mesure espace libre exploitable (diagnostic convergence) ────────
        if base_config.heatmap_cache is not None:
            _all_free = base_config.heatmap_cache.get_top_candidates(top_percent=1.0)
            _h_grid, _w_grid = base_config.heatmap_cache.scores.shape
            _grid_total = _h_grid * _w_grid
            print(
                f"[candidate-space] free={len(_all_free)} grid_total={_grid_total} "
                f"free_ratio={len(_all_free) / max(1, _grid_total):.3f}",
                flush=True,
            )

        # ── C6 : seeding géographique diversifié par run ──────────────────────
        _tcs = base_config.heatmap_cache.get_top_candidates(top_percent=0.40) if base_config.heatmap_cache else []
        _zones = _spatial_cluster_candidates(_tcs, request.n_runs)
        print(
            f"[diversity-seed] zones={request.n_runs} total={len(_tcs)} sizes={[len(z) for z in _zones]}",
            flush=True,
        )

        # ── N runs GA → pool inter-runs ──────────────────────────────────────
        all_circuits: list = []
        for run_idx in range(request.n_runs):
            run_seed = (request.ga_seed + run_idx) if request.ga_seed is not None else None
            run_config = _dc_replace(base_config, ga_seed=run_seed, zone_seed_candidates=_zones[run_idx])
            ga = GeneticAlgorithm(config=run_config)
            ga.set_graph(graph)
            result = ga.generate(start, end, request.forbidden_zones)
            all_circuits.extend(result.circuits[:request.top_k_per_run])
            self._last_ga = ga  # _ocad_tree identique entre runs (construit depuis candidate_points)

        # ── Filtre qualité avec fallback ─────────────────────────────────────
        all_circuits.sort(key=lambda c: c.fitness, reverse=True)
        if all_circuits:
            ratio = request.diversity_fitness_ratio
            filtered = [c for c in all_circuits if c.fitness >= ratio * all_circuits[0].fitness]
            if len(filtered) < num_variants:
                filtered = all_circuits
        else:
            filtered = []

        # ── A9 : diagnostic distances circuits filtrés (test hypothèse terme B) ─
        if filtered:
            _a9_dists = []
            for _c9 in filtered:
                _a9_arr = np.array(_c9.controls)
                _a9_legs = _haversine_batch(
                    _a9_arr[:-1, 0], _a9_arr[:-1, 1], _a9_arr[1:, 0], _a9_arr[1:, 1]
                )
                _a9_dists.append(float(np.sum(_a9_legs)))
            _a9_target = float(getattr(request, "target_length_m", 0) or 0)
            _a9_min, _a9_max = min(_a9_dists), max(_a9_dists)
            _a9_mean = sum(_a9_dists) / len(_a9_dists)
            print(
                f"[diversity-distance] n={len(_a9_dists)} "
                f"dist=[{_a9_min:.0f}..{_a9_max:.0f}]m mean={_a9_mean:.0f}m "
                f"target={_a9_target:.0f}m err_mean={abs(_a9_mean - _a9_target):.0f}m",
                flush=True,
            )

        # ── CourseProfile + déduplication légère ─────────────────────────────
        _prof_t0 = _time_mod.time()
        bb = request.bounding_box
        bbox_tuple = (bb["min_x"], bb["min_y"], bb["max_x"], bb["max_y"])

        circuits_with_profiles: list = []
        for c in filtered:
            try:
                arr = np.array(c.controls)
                legs_m = _haversine_batch(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])
                cp = compute_course_profile(
                    controls=c.controls,
                    legs_m=legs_m,
                    bbox=bbox_tuple,
                    heatmap_cache=request.heatmap_cache,
                    # route_analyzer omis volontairement : route_diversity_score() trop lent sur 30 circuits
                )
                circuits_with_profiles.append((c, cp))
            except Exception:
                pass

        # Diagnostic diversité brute AVANT deduplication
        if len(circuits_with_profiles) > 1:
            _raw_vecs = [course_profile_vector(cp) for _, cp in circuits_with_profiles]
            _raw_dists = [cosine_distance(_raw_vecs[i], _raw_vecs[j])
                          for i in range(len(_raw_vecs))
                          for j in range(i + 1, len(_raw_vecs))]
            _raw_mean = sum(_raw_dists) / len(_raw_dists)
        else:
            _raw_mean = 0.0
        print(f"[pool-diversity] n={len(circuits_with_profiles)} mean_cosine_raw={_raw_mean:.4f}", flush=True)

        # Dédoublonnage : conserver le meilleur fitness si cosinus < seuil
        deduped: list = []
        deduped_vecs: list = []
        _removed_cos: list = []
        for item in circuits_with_profiles:
            v = course_profile_vector(item[1])
            min_dist = min((cosine_distance(v, dv) for dv in deduped_vecs), default=None)
            if min_dist is None or min_dist >= DIVERSITY_DUPLICATE_THRESHOLD:
                deduped.append(item)
                deduped_vecs.append(v)
            else:
                _removed_cos.append(min_dist)

        # Sélection greedy cosinus
        selected = select_diverse_circuits(deduped, n_select=num_variants)

        # Recalcul profil avec route_analyzer pour les N variantes retenues uniquement
        # (omis lors de la boucle principale pour éviter ~300 appels sur tout le pool)
        if request.route_analyzer is not None and selected:
            recomputed = []
            for c, _cp_old in selected:
                try:
                    arr = np.array(c.controls)
                    legs_m = _haversine_batch(arr[:-1, 0], arr[:-1, 1], arr[1:, 0], arr[1:, 1])
                    cp_full = compute_course_profile(
                        controls=c.controls,
                        legs_m=legs_m,
                        bbox=bbox_tuple,
                        heatmap_cache=request.heatmap_cache,
                        route_analyzer=request.route_analyzer,
                    )
                    recomputed.append((c, cp_full))
                except Exception:
                    recomputed.append((c, _cp_old))
            selected = recomputed

        _prof_elapsed = _time_mod.time() - _prof_t0

        # Log
        if len(selected) > 1:
            sel_vecs = [course_profile_vector(cp) for _, cp in selected]
            dists = [
                cosine_distance(sel_vecs[i], sel_vecs[j])
                for i in range(len(sel_vecs))
                for j in range(i + 1, len(sel_vecs))
            ]
            mean_cos = sum(dists) / len(dists)
        else:
            mean_cos = 0.0
        _dedup_removed = len(circuits_with_profiles) - len(deduped)
        _cos_removed_info = (
            f" cos_removed=[{min(_removed_cos):.4f}..{max(_removed_cos):.4f}]"
            if _removed_cos else ""
        )
        print(
            f"[diversity] runs={request.n_runs} pool={len(all_circuits)} filtered={len(filtered)} "
            f"deduped={len(deduped)} dedup_removed={_dedup_removed}{_cos_removed_info} "
            f"selected={len(selected)} mean_cosine={mean_cos:.4f} "
            f"profiling={_prof_elapsed:.2f}s",
            flush=True,
        )

        # Fallback edge case : pool vide
        if not selected and all_circuits:
            selected = [(all_circuits[0], None)]

        # ── Re-ranker choix d'itinéraire (post-GA, sprint uniquement) ────────
        _route_choices_by_idx: list = [None] * len(selected)
        if request.route_analyzer is not None and sprint_mode and selected:
            _best_idx = 0
            _best_total = -1.0
            _reranker_t0 = _time_mod.time()
            for _ci, (_ckt, _) in enumerate(selected[:3]):
                if _time_mod.time() - _reranker_t0 > 15.0:
                    break
                try:
                    _rc = request.route_analyzer.score_circuit_choices(
                        _ckt.controls, k=2,
                        t_deadline=_reranker_t0 + 15.0,
                    )
                    _route_choices_by_idx[_ci] = _rc
                    if _rc["total_choice_score"] > _best_total:
                        _best_total = _rc["total_choice_score"]
                        _best_idx = _ci
                except Exception:
                    pass
            if _best_idx > 0:
                selected.insert(0, selected.pop(_best_idx))
                _route_choices_by_idx.insert(0, _route_choices_by_idx.pop(_best_idx))
        # ─────────────────────────────────────────────────────────────────────

        # ── Conversion vers GeneratedCircuit ─────────────────────────────────
        circuits = []
        for i, (circuit, _cp) in enumerate(selected):
            controls = []
            for j, pos in enumerate(circuit.controls):
                ctrl_type = (
                    "start" if j == 0
                    else "finish" if j == len(circuit.controls) - 1
                    else "control"
                )
                desc = self._describe_control(pos[0], pos[1], request.candidate_points)
                controls.append({
                    "order": j + 1,
                    "x": pos[0],
                    "y": pos[1],
                    "type": ctrl_type,
                    "description": desc,
                })

            # Distance réelle via RouteAnalyzer pour le circuit gagnant
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

            _labels, _title = _cp.describe(LABEL_THRESHOLDS) if _cp is not None else ([], "Standard")
            _scenario = getattr(self._last_ga, "_scenario", "standard") if hasattr(self, "_last_ga") else "standard"
            circuits.append(GeneratedCircuit(
                id=f"genetic_{i + 1}",
                controls=controls,
                total_length_m=total_length,
                total_climb_m=request.target_climb_m,
                estimated_time_minutes=request.winning_time_minutes,
                score=circuit.fitness,
                generation_method="genetic",
                description=f"Circuit généré par algorithme génétique (génération {circuit.generation})",
                leg_route_choices=_leg_choices,
                label=_labels,
                profile_title=_title,
                scenario=_scenario,
            ))

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
        radius_m: float = 40.0,
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
