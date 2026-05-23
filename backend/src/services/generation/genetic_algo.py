# =============================================
# Algorithme génétique pour génération de circuits
# Sprint 7: Génération de circuits (Forêt)
# =============================================

from __future__ import annotations

import random
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Callable
from datetime import datetime

import numpy as np

try:
    from ..learning.ocad_patch_scorer import OcadPatchScorer as _OcadPatchScorer
    _PATCH_SCORER_CLASS = _OcadPatchScorer
except Exception:
    _PATCH_SCORER_CLASS = None

if TYPE_CHECKING:
    from ..learning.ocad_patch_scorer import HeatmapCache


# =============================================
# Types de données
# =============================================
@dataclass
class Circuit:
    """Un circuit généré (solution candidate)."""

    controls: List[Tuple[float, float]]  # Liste des positions (x, y)
    score: float = 0.0
    fitness: float = 0.0
    generation: int = 0
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"circuit_{random.randint(0, 99999)}"


@dataclass
class GenerationConfig:
    """Configuration de la génération."""

    # Paramètres du circuit cible
    target_length_m: float = 4000  # Longueur cible en mètres
    target_climb_m: float = 200  # D+ cible
    target_controls: int = 10  # Nombre de postes
    winning_time_min: float = 30  # Temps gagnant estimé

    # Bounding box WGS84 {min_x, min_y, max_x, max_y} — pour contraindre les positions
    bounding_box: dict = None

    # Features OCAD attractives (buttes, dépressions, lisières…) — ancrage terrain
    candidate_points: List[Dict] = field(default_factory=list)  # [{x, y, isom}, ...]

    # Paramètres génétiques
    population_size: int = 50
    generations: int = 100
    mutation_rate: float = 0.1
    crossover_rate: float = 0.7
    elite_count: int = 5

    # Contraintes
    min_control_distance: float = 60  # Distance minimale entre postes en mètres (IOF AA3.5.5)
    max_attempts: int = 10

    # Mode sprint urbain (TD1/TD2) — adapte les paramètres pour la CO en ville
    sprint_mode: bool = False  # True → min_dist 30m, jambes ≤ 200m pénalisées

    # Type et niveau technique — pour charger les seuils IOF/FFCO dynamiques
    circuit_type: str = "forest"  # "sprint", "forest", "md", "couleur"
    technical_level: int = 3      # TD1–TD5
    map_scale: Optional[int] = None  # échelle OCAD (ex: 4000 pour 1:4000) — infrastructure future

    # Grille de scores V2 précomputée (optionnel)
    # Si fourni : Smart Seeding + evaluate_fitness() utilisent le cache pour les lookups O(1).
    # Si None : fallback ISOM attractiveness (comportement existant, aucune régression).
    heatmap_cache: Optional[HeatmapCache] = field(default=None, repr=False)

    # Grille d'altitudes précomputée (optionnel)
    # Si fourni : evaluate_fitness() calcule un D+ estimé et pénalise les circuits
    # dont le ratio D+/distance_totale dépasse le seuil IOF (max_climb_ratio).
    # Si None : terme G absent (aucune régression).
    elevation_cache: Optional[object] = field(default=None, repr=False)

    # RouteAnalyzer OSM — si fourni, active le terme E basé sur la diversité réelle
    # des itinéraires (Jaccard k-plus-courts). Fallback GPX Vikazimut si None.
    route_analyzer: Optional[object] = field(default=None, repr=False)

    # Désactive le terme M (leg diversity) sans toucher à technical_level.
    # Réservé à l'ablation study — ne pas utiliser en production.
    ablation_disable_leg_diversity: bool = False

    # FFCORulesEngine — source de vérité des seuils et pondérations (optionnel).
    # Si None : valeurs historiques hardcodées (aucune régression).
    rules_engine: Optional[object] = field(default=None, repr=False)

    # Segments LineString OCAD [{p0, p1, isom_code}] — termes N/O/P forêt.
    # Vide si pas d'OCAD chargé (fallback OSM ou inactif selon le terme).
    ocad_line_segments: list = field(default_factory=list)

    # Index spatial pré-construit (SegmentSpatialIndex) — optionnel.
    # Si fourni par preprocess-ocad, évite la reconstruction à chaque génération.
    segment_index: Optional[object] = field(default=None, repr=False)

    # Timeout en secondes pour la boucle évolutionnaire (évite les boucles infinies)
    timeout_seconds: float = 90.0


@dataclass
class GenerationResult:
    """Résultat de la génération."""

    circuits: List[Circuit]
    best_circuit: Circuit
    generations_run: int
    time_elapsed_seconds: float
    config: GenerationConfig


# =============================================
# Seuils de séparation adaptés à l'échelle OCAD
# =============================================

# "forest"/"foret"/"forêt" = alias non-IOF → md (ref=10000).
# Les circuits LD doivent passer circuit_type="ld" explicitement pour bénéficier de ref=15000.
_SCALE_ALIASES: Dict[str, str] = {"foret": "md", "forest": "md", "forêt": "md"}
_SCALE_REF: Dict[str, int] = {"sprint": 4000, "md": 10000, "ld": 15000}
_SCALE_CLAMP: Dict[str, Tuple[int, int]] = {
    "sprint": (15, 80),
    "md": (40, 150),
    "ld": (40, 150),
}


def scale_min_separation(
    base_m: float,
    map_scale: Optional[int],
    circuit_type: Optional[str],
) -> int:
    """Scale min separation to maintain constant mm-on-map as scale changes.

    Uses ceil (conservative for a minimum constraint — never round below intended min).
    base_m assumed calibrated at IOF reference scale (sprint=4000, md=10000, ld=15000).
    Clamp is always applied, even when map_scale is None.
    """
    ct = (circuit_type or "md").lower()
    ct = _SCALE_ALIASES.get(ct, ct)
    lo, hi = _SCALE_CLAMP.get(ct, (40, 150))
    if not map_scale:
        return int(max(lo, min(hi, math.ceil(base_m))))
    ref = _SCALE_REF.get(ct, 10000)
    return int(max(lo, min(hi, math.ceil(base_m * map_scale / ref))))


# =============================================
# Algorithme génétique
# =============================================
class GeneticAlgorithm:
    """
    Algorithme génétique pour générer des circuits de CO.

    Utilise:
    - Sélection par tournoi
    - Croisement OX (Order Crossover)
    - Mutation par insertion/déplacement
    - Élitisme
    """

    def __init__(
        self,
        config: GenerationConfig = None,
        scoring_function: Callable = None,
    ):
        """
        Initialise l'algorithme.

        Args:
            config: Configuration de génération
            scoring_function: Fonction de scoring personnalisée
        """
        self.config = config or GenerationConfig()
        self.scoring_function = scoring_function or self._default_scoring

        self.population: List[Circuit] = []
        self.best_solution: Optional[Circuit] = None
        self.generation = 0

        # Pour le graphe de navigation
        self.graph = None
        self._stagnation_count = 0
        self._last_best_fitness = 0.0

        # Seuils calibrés depuis placement_rules.json (Étape 11b)
        self._placement_rules = self._load_placement_rules()

        # Seuils et pondérations depuis FFCORulesEngine (si fourni)
        self._ga_weights = None
        self._thresholds = None
        if self.config.rules_engine is not None:
            _ct = self.config.circuit_type or "forest"
            _td = self.config.technical_level or 3
            self._ga_weights = self.config.rules_engine.get_ga_weights(_ct, _td)
            self._thresholds = self.config.rules_engine.get_fitness_thresholds(_ct, _td)

        # Scores d'attractivité IOF par code ISOM (Étape 14 — control_descriptions.json)
        self._isom_att_scores = self._load_isom_attractiveness()

        # Visual terrain scorer (XGBoost, AUC=0.85 — Phase C)
        self._patch_scorer = _PATCH_SCORER_CLASS.load() if _PATCH_SCORER_CLASS else None

        # ── OCAD KDTree (Phase 2 — Ancrage Vectoriel) ──────────────────────
        # Index spatial O(log N) pour ancrage strict sur entités ISOM réelles.
        # Construit uniquement si ≥20 candidate_points portent un code isom.
        # Si scipy absent ou trop peu de features → _ocad_tree = None
        # (comportement identique à Phase 1, aucune régression).
        self._ocad_pts: list = [cp for cp in self.config.candidate_points if cp.get("isom")]
        self._ocad_tree = None
        if len(self._ocad_pts) >= 20:
            try:
                from scipy.spatial import KDTree as _KDTree
                _kd_coords = np.array([[cp["x"], cp["y"]] for cp in self._ocad_pts])
                self._ocad_tree = _KDTree(_kd_coords)
            except Exception:
                self._ocad_tree = None
        if self._ocad_tree is not None:
            print(f"[GA DEBUG] KDTree ISOM: {len(self._ocad_pts)} features", flush=True)
        else:
            print(f"[GA DEBUG] KDTree ISOM: ABSENT (ocad_pts={len(self._ocad_pts)}, threshold>=20)", flush=True)

        # ── RouteAnalyzer (terme E OSM) ────────────────────────────────────────
        self._route_analyzer = self.config.route_analyzer  # None si absent

        # ── Leg Diversity DB (données GPX Vikazimut) ──────────────────────────
        self._leg_diversity_db: list = self._load_leg_diversity_db()

        # ── Navigation roles ISOM (termes I/J/K) ──────────────────────────────
        self._nav_roles: dict = self._load_nav_roles()
        self._nav_params: dict = self._load_nav_params()
        self._nav_cache: dict = {}  # cache (px,py,cx,cy,role) → score, clé arrondie à 4 décimales (~11m)

        # ── ISOM sémantique (termes N, O, P) ──────────────────────────────────────
        import json as _json_isom
        import pathlib as _pathlib_isom
        _sem_path = _pathlib_isom.Path(__file__).parent.parent / "knowledge_base" / "isom_semantics.json"
        self._isom_sem: dict = _json_isom.loads(_sem_path.read_text()) if _sem_path.exists() else {}

        # ── Index spatial perceptuel (SegmentSpatialIndex) ────────────────────
        from .perceptual_model import build_segment_index as _build_seg_idx
        if config.segment_index is not None:
            self._seg_index = config.segment_index  # pré-construit par preprocess-ocad
        elif config.ocad_line_segments:
            _center_lat = (
                (config.bounding_box.get("min_y", 48.0) + config.bounding_box.get("max_y", 48.0)) / 2
                if config.bounding_box else 48.0
            )
            self._seg_index = _build_seg_idx(config.ocad_line_segments, self._isom_sem, _center_lat)
        else:
            self._seg_index = None

        # ── TD1 preferred features (postes sur éléments évidents) ──────────────
        # Actif uniquement pour technical_level == 1. Charge depuis placement_rules.json
        # navigation.preferred_isom_codes. _best_att_ocad() utilise ce set pour
        # prioriser les features chemin/lisière/eau avant de fallback sur l'attractivité générique.
        _prefer_codes = self._nav_params.get("preferred_isom_codes")
        self._td1_prefer_isom: Optional[set] = (
            set(_prefer_codes) if _prefer_codes and self.config.technical_level == 1 else None
        )
        self._td1_prefer_max_dist_m: float = float(
            self._nav_params.get("preferred_isom_max_dist_m", 25.0)
        )

    def _load_leg_diversity_db(self) -> list:
        """Charge leg_diversity.json si présent. Retourne [] si absent (fallback silencieux)."""
        import json
        from pathlib import Path
        db_path = Path(__file__).parents[3] / "data" / "leg_diversity.json"
        try:
            with open(db_path, encoding="utf-8") as f:
                db = json.load(f)
            print(f"[GA] Leg diversity DB: {len(db)} jambes chargees", flush=True)
            return db
        except Exception:
            return []

    def _lookup_leg_cv(
        self,
        a: Tuple[float, float],
        b: Tuple[float, float],
    ) -> Optional[float]:
        """
        Cherche dans leg_diversity_db les jambes géographiquement similaires à (a→b).

        Critères :
          - bbox de l'entrée contient les deux contrôles (±0.01° marge)
          - dist_m de l'entrée est à ±30% de la distance réelle

        Retourne le CV médian des entrées correspondantes, ou None si pas de données.
        """
        if not self._leg_diversity_db:
            return None

        lng_a, lat_a = a
        lng_b, lat_b = b
        dist_real = self._haversine_m(a, b)
        if dist_real < 30:
            return None

        margin = 0.01  # ~1km — tolérance de positionnement géographique
        dist_lo = dist_real * 0.70
        dist_hi = dist_real * 1.30

        cvs = []
        for entry in self._leg_diversity_db:
            # Les deux contrôles doivent être dans la bbox (avec marge)
            if not (
                entry["lat_min"] - margin <= lat_a <= entry["lat_max"] + margin
                and entry["lng_min"] - margin <= lng_a <= entry["lng_max"] + margin
                and entry["lat_min"] - margin <= lat_b <= entry["lat_max"] + margin
                and entry["lng_min"] - margin <= lng_b <= entry["lng_max"] + margin
            ):
                continue
            if not (dist_lo <= entry["dist_m"] <= dist_hi):
                continue
            cvs.append(entry["cv"])

        if not cvs:
            return None
        cvs.sort()
        return cvs[len(cvs) // 2]  # médiane

    def _load_placement_rules(self) -> dict:
        """Charge les seuils IOF/FFCO depuis placement_rules.json selon circuit_type et technical_level."""
        import json
        from pathlib import Path
        rules_path = Path(__file__).parents[2] / "services" / "knowledge_base" / "placement_rules.json"
        defaults = {
            "min_leg_m": 60, "max_leg_m": 400,
            "dog_leg_angle_deg": 25, "max_climb_ratio": 0.04,
            "min_control_separation_m": 60,
        }
        try:
            data = json.loads(rules_path.read_text(encoding="utf-8"))
            ct = self.config.circuit_type or "forest"
            td = self.config.technical_level or 3
            td_key = f"TD{td}"
            category = data.get(ct, data.get("forest", {}))
            rules = category.get(td_key, None)
            if rules is None:
                rules = data.get("_defaults", defaults)
            _scale = self.config.map_scale
            if "min_control_separation_m" in rules:
                rules = {**rules, "min_control_separation_m": scale_min_separation(
                    rules["min_control_separation_m"], _scale, ct
                )}
            return rules
        except Exception:
            return defaults

    def _load_isom_attractiveness(self) -> dict:
        """Charge les scores d'attractivité IOF depuis control_descriptions.json.

        Retourne {isom_code_int: float} — ex: {202: 1.0, 401: 0.15, 503: 0.75}
        """
        import json
        from pathlib import Path
        p = Path(__file__).parents[2] / "data" / "control_descriptions.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            isom_map = data.get("isom_to_description", {})
            att_scores = data.get("attractiveness_score", {
                "very_high": 1.0, "high": 0.75, "medium": 0.45, "low": 0.15
            })
            return {
                int(k): att_scores.get(v.get("attractiveness", "medium"), 0.45)
                for k, v in isom_map.items()
                if k.isdigit()
            }
        except Exception:
            return {}

    def _load_nav_roles(self) -> dict:
        """Charge isom_navigation_roles.json. Retourne {} si absent (fallback silencieux)."""
        import json
        from pathlib import Path
        p = Path(__file__).parents[3] / "data" / "isom_navigation_roles.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_nav_params(self) -> dict:
        """Retourne le bloc navigation de placement_rules.json pour le TD/circuit courant."""
        return self._placement_rules.get("navigation", {})

    def _nav_roles_quality(self, isom: int, role: str) -> float:
        """Retourne la qualité [0.3, 0.5, 0.75, 1.0] d'un code ISOM pour un rôle navigation."""
        roles = self._nav_roles.get(role, {}).get("quality", {})
        if isom in roles.get("very_high", []):
            return 1.0
        if isom in roles.get("high", []):
            return 0.75
        if isom in roles.get("medium", []):
            return 0.5
        return 0.3

    def _score_attack_point(
        self,
        cx: float, cy: float,
        px: float, py: float,
        radius_m: float,
    ) -> float:
        """Score qualité du point d'attaque pour le poste (cx,cy) en arrivant depuis (px,py).

        Retourne [0, 1]. Neutre 0.5 si KDTree absent ou radius_m=0.
        Approximation V1 : radius en degrés = radius_m/111_000 (sur-sélection en longitude à hautes lat).
        """
        if self._ocad_tree is None or radius_m == 0:
            return 0.5
        _key = (round(px, 4), round(py, 4), round(cx, 4), round(cy, 4), "attack")
        if _key in self._nav_cache:
            return self._nav_cache[_key]

        LNG_TO_M = 111_000 * math.cos(math.radians(cy))
        LAT_TO_M = 110_540
        approach_dx_m = (cx - px) * LNG_TO_M
        approach_dy_m = (cy - py) * LAT_TO_M

        radius_deg = radius_m / 111_000
        idxs = self._ocad_tree.query_ball_point([cx, cy], radius_deg)
        codes = self._nav_roles.get("attack_point", {}).get("codes", [])
        best = 0.0
        for idx in idxs:
            cp = self._ocad_pts[idx]
            isom = cp.get("isom")
            if isom not in codes:
                continue
            quality = self._nav_roles_quality(isom, "attack_point")
            dist_m = math.hypot((cp["x"] - cx) * LNG_TO_M, (cp["y"] - cy) * LAT_TO_M)
            feat_dx_m = (cp["x"] - cx) * LNG_TO_M
            feat_dy_m = (cp["y"] - cy) * LAT_TO_M
            dot = approach_dx_m * feat_dx_m + approach_dy_m * feat_dy_m
            side_bonus = 1.0 if dot < 0 else 0.6
            dist_factor = max(0.0, 1.0 - dist_m / radius_m)
            best = max(best, quality * side_bonus * dist_factor)

        result = min(best, 1.0)
        self._nav_cache[_key] = result
        return result

    def _score_catching_feature(
        self,
        cx: float, cy: float,
        px: float, py: float,
        radius_m: float,
    ) -> float:
        """Score ligne d'arrêt au-delà du poste (cx,cy), en arrivant depuis (px,py).

        Retourne [0, 1]. Neutre 0.5 si KDTree absent ou radius_m=0.
        """
        if self._ocad_tree is None or radius_m == 0:
            return 0.5
        _key = (round(px, 4), round(py, 4), round(cx, 4), round(cy, 4), "catch")
        if _key in self._nav_cache:
            return self._nav_cache[_key]

        LNG_TO_M = 111_000 * math.cos(math.radians(cy))
        LAT_TO_M = 110_540
        approach_dx_m = (cx - px) * LNG_TO_M
        approach_dy_m = (cy - py) * LAT_TO_M
        norm_m = max(math.hypot(approach_dx_m, approach_dy_m), 1e-6)
        overshoot_x = cx + (approach_dx_m / norm_m) * (radius_m * 0.5) / LNG_TO_M
        overshoot_y = cy + (approach_dy_m / norm_m) * (radius_m * 0.5) / LAT_TO_M

        radius_deg = radius_m * 0.6 / 111_000
        idxs = self._ocad_tree.query_ball_point([overshoot_x, overshoot_y], radius_deg)
        codes = self._nav_roles.get("catching_feature", {}).get("codes", [])
        best = 0.0
        for idx in idxs:
            cp = self._ocad_pts[idx]
            isom = cp.get("isom")
            if isom not in codes:
                continue
            quality = self._nav_roles_quality(isom, "catching_feature")
            best = max(best, quality * 0.9)

        self._nav_cache[_key] = best
        return best

    def _score_handrail(
        self,
        ax: float, ay: float,
        bx: float, by: float,
        n_samples: int = 5,
    ) -> float:
        """Score disponibilité d'une main courante le long de la jambe A→B.

        Échantillonne n_samples points intermédiaires, vérifie une feature HANDRAIL à ≤50m.
        Retourne [0, 1]. Neutre 0.5 si KDTree absent.
        """
        if self._ocad_tree is None:
            return 0.5
        _key = (round(ax, 4), round(ay, 4), round(bx, 4), round(by, 4), "handrail")
        if _key in self._nav_cache:
            return self._nav_cache[_key]

        codes = self._nav_roles.get("handrail", {}).get("codes", [])
        radius_deg = 50.0 / 111_000  # Option B : rayon en degrés
        hits = 0
        for i in range(1, n_samples + 1):
            t = i / (n_samples + 1)
            sx = ax + t * (bx - ax)
            sy = ay + t * (by - ay)
            idxs = self._ocad_tree.query_ball_point([sx, sy], radius_deg)
            if any(self._ocad_pts[idx].get("isom") in codes for idx in idxs):
                hits += 1

        result = hits / n_samples
        self._nav_cache[_key] = result
        return result

    def compute_nav_scores(
        self,
        controls: list,
    ) -> list:
        """Calcule les scores navigation par jambe sur le circuit final (une seule fois).

        Appelé sur le meilleur individu après convergence GA, avant de construire
        GeneratedCircuit. Ne pas appeler dans evaluate_fitness() (trop coûteux).

        Returns:
            list de dicts [{attack, catch, handrail, decision_points, route_diversity}]
            — une entrée par jambe (len = len(controls)-1).
        """
        nav = self._nav_params
        _r_att = nav.get("attack_radius_m", 0)
        _r_cat = nav.get("catching_radius_m", 0)
        result = []
        for i in range(1, len(controls)):
            cx, cy = controls[i][0], controls[i][1]
            px, py = controls[i - 1][0], controls[i - 1][1]
            att = self._score_attack_point(cx, cy, px, py, _r_att) if _r_att > 0 else None
            cat = self._score_catching_feature(cx, cy, px, py, _r_cat) if _r_cat > 0 else None
            hr = self._score_handrail(px, py, cx, cy) if nav.get("handrail_required") else None
            dp = None
            rd = None
            if self._route_analyzer is not None:
                try:
                    dp = self._route_analyzer.count_decision_points(px, py, cx, cy)
                    rd = self._route_analyzer.route_diversity_info(px, py, cx, cy)
                except Exception:
                    pass
            result.append({"attack": att, "catch": cat, "handrail": hr,
                           "decision_points": dp, "route_diversity": rd})
        return result

    def compute_td1_path_distances(self, controls: list) -> dict:
        """Calcule la distance à la nearest preferred TD1 feature pour chaque poste.

        Utilisé par le contrôleur C17. Retourne {control_index: dist_m}.
        Retourne {} si technical_level != 1, _td1_prefer_isom absent, ou KDTree absent.
        """
        if self._td1_prefer_isom is None or self._ocad_tree is None:
            return {}
        result = {}
        for i, ctrl in enumerate(controls):
            cx, cy = ctrl[0], ctrl[1]
            _, dist_m = self._best_att_ocad(
                cx, cy, 200.0,
                prefer_isom=self._td1_prefer_isom,
                prefer_max_dist_m=200.0,
            )
            result[i] = round(dist_m, 1)
        return result

    # ── Nav context (Phase 5 — highlight visuel) ─────────────────────────────

    def compute_nav_context(
        self,
        from_lng: float, from_lat: float,
        to_lng: float, to_lat: float,
    ) -> dict:
        """Contexte de navigation pour un leg — utilisé par l'endpoint dédié.

        Retourne les coordonnées des features clés + route + points de décision.
        Sûr à appeler de l'extérieur : ne modifie pas l'état du GA.
        """
        nav = self._nav_params
        _r_att = nav.get("attack_radius_m", 0)
        _r_cat = nav.get("catching_radius_m", 0)

        attack = self._find_attack_coords(to_lng, to_lat, from_lng, from_lat, _r_att) if _r_att > 0 else None
        catch = self._find_catch_coords(to_lng, to_lat, from_lng, from_lat, _r_cat) if _r_cat > 0 else None
        handrail_pts = self._find_handrail_sample_coords(from_lng, from_lat, to_lng, to_lat) \
            if nav.get("handrail_required") else []

        optimal_route = []
        decision_pts = []
        credible_routes = None
        if self._route_analyzer is not None:
            try:
                path = self._route_analyzer.find_optimal_route(from_lng, from_lat, to_lng, to_lat)
                if path:
                    optimal_route = [{"lng": n[0], "lat": n[1]} for n in path]
                decision_pts = self._route_analyzer.get_decision_point_coords(
                    from_lng, from_lat, to_lng, to_lat
                )
                div = self._route_analyzer.route_diversity_info(from_lng, from_lat, to_lng, to_lat)
                credible_routes = div.get("credible_routes")
            except Exception:
                pass

        return {
            "attack_point": attack,
            "catching_feature": catch,
            "handrail_samples": handrail_pts,
            "optimal_route": optimal_route,
            "decision_points": decision_pts,
            "credible_routes": credible_routes,
        }

    def _find_attack_coords(
        self, cx: float, cy: float, px: float, py: float, radius_m: float
    ) -> Optional[dict]:
        """Retourne {lng, lat, isom, score} du meilleur point d'attaque, ou None."""
        if self._ocad_tree is None or radius_m == 0:
            return None
        LNG_TO_M = 111_000 * math.cos(math.radians(cy))
        LAT_TO_M = 110_540
        approach_dx_m = (cx - px) * LNG_TO_M
        approach_dy_m = (cy - py) * LAT_TO_M
        radius_deg = radius_m / 111_000
        idxs = self._ocad_tree.query_ball_point([cx, cy], radius_deg)
        codes = self._nav_roles.get("attack_point", {}).get("codes", [])
        best_score, best_cp = 0.0, None
        for idx in idxs:
            cp = self._ocad_pts[idx]
            isom = cp.get("isom")
            if isom not in codes:
                continue
            quality = self._nav_roles_quality(isom, "attack_point")
            dist_m = math.hypot((cp["x"] - cx) * LNG_TO_M, (cp["y"] - cy) * LAT_TO_M)
            feat_dx_m = (cp["x"] - cx) * LNG_TO_M
            feat_dy_m = (cp["y"] - cy) * LAT_TO_M
            dot = approach_dx_m * feat_dx_m + approach_dy_m * feat_dy_m
            side_bonus = 1.0 if dot < 0 else 0.6
            dist_factor = max(0.0, 1.0 - dist_m / radius_m)
            score = min(quality * side_bonus * dist_factor, 1.0)
            if score > best_score:
                best_score, best_cp = score, cp
        if best_cp is None:
            return None
        return {"lng": best_cp["x"], "lat": best_cp["y"],
                "isom": best_cp.get("isom"), "score": round(best_score, 2)}

    def _find_catch_coords(
        self, cx: float, cy: float, px: float, py: float, radius_m: float
    ) -> Optional[dict]:
        """Retourne {lng, lat, isom, score} de la meilleure ligne d'arrêt, ou None."""
        if self._ocad_tree is None or radius_m == 0:
            return None
        LNG_TO_M = 111_000 * math.cos(math.radians(cy))
        LAT_TO_M = 110_540
        approach_dx_m = (cx - px) * LNG_TO_M
        approach_dy_m = (cy - py) * LAT_TO_M
        norm_m = max(math.hypot(approach_dx_m, approach_dy_m), 1e-6)
        overshoot_x = cx + (approach_dx_m / norm_m) * (radius_m * 0.5) / LNG_TO_M
        overshoot_y = cy + (approach_dy_m / norm_m) * (radius_m * 0.5) / LAT_TO_M
        radius_deg = radius_m * 0.6 / 111_000
        idxs = self._ocad_tree.query_ball_point([overshoot_x, overshoot_y], radius_deg)
        codes = self._nav_roles.get("catching_feature", {}).get("codes", [])
        best_score, best_cp = 0.0, None
        for idx in idxs:
            cp = self._ocad_pts[idx]
            isom = cp.get("isom")
            if isom not in codes:
                continue
            quality = self._nav_roles_quality(isom, "catching_feature")
            score = quality * 0.9
            if score > best_score:
                best_score, best_cp = score, cp
        if best_cp is None:
            return None
        return {"lng": best_cp["x"], "lat": best_cp["y"],
                "isom": best_cp.get("isom"), "score": round(best_score, 2)}

    def _find_handrail_sample_coords(
        self,
        ax: float, ay: float,
        bx: float, by: float,
        n_samples: int = 5,
    ) -> list:
        """Retourne [{lng, lat}] des points intermédiaires qui ont une main courante à ≤50m."""
        if self._ocad_tree is None:
            return []
        codes = self._nav_roles.get("handrail", {}).get("codes", [])
        radius_deg = 50.0 / 111_000
        result = []
        for i in range(1, n_samples + 1):
            t = i / (n_samples + 1)
            sx = ax + t * (bx - ax)
            sy = ay + t * (by - ay)
            idxs = self._ocad_tree.query_ball_point([sx, sy], radius_deg)
            if any(self._ocad_pts[idx].get("isom") in codes for idx in idxs):
                result.append({"lng": sx, "lat": sy})
        return result

    def set_graph(self, graph):
        """Définit le graphe de navigation."""
        self.graph = graph

    def _find_nearest_cp(
        self,
        x: float,
        y: float,
        max_dist_m: float,
    ) -> Optional[Tuple[float, float]]:
        """Retourne le candidate_point OCAD le plus proche dans un rayon max_dist_m.

        Permet d'ancrer les postes sur des features terrain réelles (butte, dépression,
        lisière, clôture…) plutôt que sur des positions purement aléatoires.
        Retourne None si aucun point dans le rayon.
        """
        if not self.config.candidate_points:
            return None
        best = None
        best_d = max_dist_m
        for cp in self.config.candidate_points:
            d = self._haversine_m((x, y), (cp["x"], cp["y"]))
            if d < best_d:
                best_d = d
                best = (cp["x"], cp["y"])
        return best

    def _nearest_ocad(self, x: float, y: float) -> tuple:
        """Retourne (cp_dict, dist_m) du feature OCAD ISOM le plus proche via KDTree.

        Si KDTree non disponible → (None, inf).
        dist_m : approximation haversine simplifiée (err < 1% pour dist < 500m, lat < 65°).
        """
        if self._ocad_tree is None:
            return None, float("inf")
        dist_deg, idx = self._ocad_tree.query([x, y])
        dist_m = dist_deg * 111_000  # 1° ≈ 111 km (équateur)
        return self._ocad_pts[idx], dist_m

    def _best_att_ocad(
        self,
        x: float,
        y: float,
        radius_m: float,
        prefer_isom: Optional[set] = None,
        prefer_max_dist_m: Optional[float] = None,
    ) -> tuple:
        """Retourne (cp_dict, dist_m) du feature OCAD ISOM le plus attractif dans radius_m.

        Si prefer_isom défini : cherche d'abord dans min(radius_m, prefer_max_dist_m)
        les features dont isom ∈ prefer_isom. Si trouvé, sélectionne parmi ceux-là.
        Sinon fallback attractivité générique sur radius_m complet (comportement par défaut).

        Si KDTree non disponible ou rayon vide → (None, inf).
        """
        if self._ocad_tree is None:
            return None, float("inf")
        radius_deg = radius_m / 111_000
        idxs = self._ocad_tree.query_ball_point([x, y], radius_deg)
        if not idxs:
            return None, float("inf")

        # TD1 preferred: chercher d'abord dans un rayon borné sur les codes cibles
        if prefer_isom:
            pref_r_deg = min(radius_deg, (prefer_max_dist_m or radius_m) / 111_000)
            pref_idxs = self._ocad_tree.query_ball_point([x, y], pref_r_deg)
            preferred = [i for i in pref_idxs if self._ocad_pts[i].get("isom") in prefer_isom]
            if preferred:
                idxs = preferred  # sélectionner uniquement parmi les preferred

        best_cp = None
        best_att = -1.0
        best_dist = float("inf")
        for idx in idxs:
            cp = self._ocad_pts[idx]
            isom = cp.get("isom")
            att = cp.get(
                "attractiveness",
                self._isom_att_scores.get(isom, 0.45) if isom else 0.45,
            )
            if cp.get("_intersection"):
                att = 1.0
            dist_deg = math.hypot(cp["x"] - x, cp["y"] - y)
            dist_m = dist_deg * 111_000
            if att > best_att or (att == best_att and dist_m < best_dist):
                best_att = att
                best_dist = dist_m
                best_cp = cp
        return best_cp, best_dist

    def generate(
        self,
        start_pos: Tuple[float, float],
        end_pos: Tuple[float, float],
        forbidden_zones: List[Dict] = None,
    ) -> GenerationResult:
        """
        Génère des circuits optimaux.

        Args:
            start_pos: Position de départ
            end_pos: Position d'arrivée
            forbidden_zones: Zones à éviter [{x, y, radius}, ...]

        Returns:
            GenerationResult avec les circuits générés
        """
        import time as _time_ga
        start_time = datetime.now()
        _t0_ga = _time_ga.time()
        forbidden_zones = forbidden_zones or []
        self._current_forbidden_zones = forbidden_zones  # accessible dans _default_scoring

        # Initialiser la population
        self.population = self._initialize_population(
            start_pos, end_pos, forbidden_zones
        )

        # Évaluer la population initiale
        for circuit in self.population:
            circuit.fitness = self.scoring_function(circuit, self.config)

        # Trier par fitness
        self.population.sort(key=lambda c: c.fitness, reverse=True)
        self.best_solution = self.population[0]

        if self._route_analyzer is not None:
            _cov = self._osm_coverage_ratio(self.config.bounding_box)
            print(f"[GA] OSM coverage {_cov:.2f} — nav metrics "
                  f"{'enabled' if _cov > 0.40 else 'disabled (sparse OSM)'}")

        # Boucle évolutionnaire
        for gen in range(self.config.generations):
            self.generation = gen + 1

            # Timeout : retourner le meilleur trouvé plutôt que boucler à l'infini
            if _time_ga.time() - _t0_ga > self.config.timeout_seconds:
                break

            # Sélection
            parents = self._select_parents()

            # Croisement
            offspring = self._crossover(parents)

            # Mutation
            offspring = self._mutate(offspring, forbidden_zones)

            # Évaluation
            for circuit in offspring:
                circuit.fitness = self.scoring_function(circuit, self.config)
                circuit.generation = self.generation

            # Élitisme - garder les meilleurs
            elite = self.population[: self.config.elite_count]

            # Nouvelle population
            self.population = elite + offspring
            self.population = self.population[: self.config.population_size]
            self.population.sort(key=lambda c: c.fitness, reverse=True)

            # Mettre à jour le meilleur
            if self.population[0].fitness > self.best_solution.fitness:
                self.best_solution = self.population[0]

            # Critère d'arrêt précoce
            if self._check_early_stop():
                break

        elapsed = (datetime.now() - start_time).total_seconds()

        if self._route_analyzer is not None:
            _cs = self._route_analyzer.get_cache_stats()
            print(
                f"[GA] RouteAnalyzer cache: hit_rate={_cs['hit_rate']:.0%}, "
                f"avg={_cs.get('avg_time_ms', 0):.0f}ms, "
                f"calls={_cs['total_calls']}",
                flush=True,
            )

        return GenerationResult(
            circuits=self.population[:10],  # Top 10
            best_circuit=self.best_solution,
            generations_run=self.generation,
            time_elapsed_seconds=elapsed,
            config=self.config,
        )

    def _initialize_population(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        forbidden_zones: List[Dict],
    ) -> List[Circuit]:
        """Initialise une population.

        80% smart (jambes calibrées à target_leg_m) + 20% aléatoire pour la diversité.
        L'initialisation smart est indispensable sur les grandes cartes (bbox > 2× target) :
        les circuits aléatoires seraient trop longs pour que le GA converge.

        Smart Seeding V2 : si config.heatmap_cache est fourni, précompute les top 20%
        de positions visuellement attractives pour biaiser l'initialisation.
        """
        # Précomputer les top candidats pour le Smart Seeding V2
        self._top_candidates: List[Tuple[float, float]] = []
        if self.config.heatmap_cache is not None:
            self._top_candidates = self.config.heatmap_cache.get_top_candidates(
                top_percent=0.40
            )

        population = []
        smart_count = int(self.config.population_size * 0.8)

        for i in range(self.config.population_size):
            if i < smart_count:
                circuit = self._create_smart_circuit(start, end, forbidden_zones)
            else:
                circuit = self._create_random_circuit(start, end, forbidden_zones)
            circuit.id = f"circuit_{i}"
            population.append(circuit)

        return population

    def _create_random_circuit(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        forbidden_zones: List[Dict],
    ) -> Circuit:
        """Crée un circuit aléatoire valide."""
        controls = [start]

        # Générer des positions intermédiaires
        num_controls = self.config.target_controls - 2  # - départ et arrivée

        for _ in range(num_controls):
            # Générer une position aléatoire dans une zone raisonnable
            pos = self._generate_random_position(start, end, forbidden_zones)
            if pos:
                controls.append(pos)

        controls.append(end)

        return Circuit(controls=controls)

    def _create_smart_circuit(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        forbidden_zones: List[Dict],
    ) -> Circuit:
        """Crée un circuit avec des jambes proches de la longueur cible.

        Place chaque poste à ~target_leg_m du précédent (±40%) dans une direction
        aléatoire, au lieu de placer uniformément dans toute la bbox.
        Garantit une longueur initiale proche de la cible → gradient de fitness actif.
        """
        n_intermediate = self.config.target_controls - 2
        if n_intermediate <= 0:
            return Circuit(controls=[start, end])

        target_leg_m = self.config.target_length_m / self.config.target_controls
        lat_deg = target_leg_m / 111000.0
        lng_deg = target_leg_m / 72600.0

        bb = self.config.bounding_box
        controls = [start]
        current = start

        for _ in range(n_intermediate):
            angle = random.uniform(0, 2 * math.pi)
            factor = random.uniform(0.6, 1.4)
            nx = current[0] + math.cos(angle) * lng_deg * factor
            ny = current[1] + math.sin(angle) * lat_deg * factor
            if bb:
                nx = max(bb["min_x"], min(bb["max_x"], nx))
                ny = max(bb["min_y"], min(bb["max_y"], ny))

            # Smart Seeding V2 (40% des cas si HeatmapCache disponible) :
            # tire le poste depuis les top-40% de la carte plutôt qu'au hasard.
            # → la population initiale démarre déjà sur des terrains attractifs.
            if self._top_candidates and random.random() < 0.40:
                nx, ny = random.choice(self._top_candidates)
                # Chaîner avec KDTree : ancre le candidat CNN sur la feature ISOM la plus attractive
                if self._ocad_tree is not None:
                    _cp, _d = self._best_att_ocad(nx, ny, 40,
                        prefer_isom=self._td1_prefer_isom, prefer_max_dist_m=self._td1_prefer_max_dist_m)
                    if _cp:
                        nx, ny = _cp["x"], _cp["y"]

            # Snap vers feature OCAD ISOM la plus attractive dans le rayon (90% si KDTree, sinon 60% O(n))
            # → ancre les postes sur des éléments terrain réels dès l'initialisation
            elif self._ocad_tree is not None and random.random() < 0.90:
                _cp, _d = self._best_att_ocad(nx, ny, 80,
                    prefer_isom=self._td1_prefer_isom, prefer_max_dist_m=self._td1_prefer_max_dist_m)
                if _cp:
                    nx, ny = _cp["x"], _cp["y"]
            elif random.random() < 0.60:
                cp = self._find_nearest_cp(nx, ny, target_leg_m * 0.5)
                if cp:
                    nx, ny = cp

            if not self._is_in_forbidden_zone(nx, ny, forbidden_zones):
                controls.append((nx, ny))
                current = (nx, ny)
            else:
                pos = self._generate_random_position(start, end, forbidden_zones)
                if pos:
                    controls.append(pos)
                    current = pos

        controls.append(end)
        return Circuit(controls=controls)

    def _generate_random_position(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        forbidden_zones: List[Dict],
    ) -> Optional[Tuple[float, float]]:
        """Génère une position aléatoire dans la bounding box de la carte."""
        max_attempts = self.config.max_attempts
        bb = self.config.bounding_box

        if bb:
            min_x = bb.get("min_x", start[0] - 0.05)
            max_x = bb.get("max_x", start[0] + 0.05)
            min_y = bb.get("min_y", start[1] - 0.05)
            max_y = bb.get("max_y", start[1] + 0.05)
        else:
            # Fallback : ±0.03° autour du centre (~3km)
            min_x, max_x = start[0] - 0.03, start[0] + 0.03
            min_y, max_y = start[1] - 0.03, start[1] + 0.03

        for _ in range(max_attempts):
            x = random.uniform(min_x, max_x)
            y = random.uniform(min_y, max_y)

            if self._is_in_forbidden_zone(x, y, forbidden_zones):
                continue

            return (x, y)

        return None

    @staticmethod
    def _haversine_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Distance haversine en mètres entre deux points WGS84 (x=lng, y=lat)."""
        R = 6371000.0
        lat1, lat2 = math.radians(p1[1]), math.radians(p2[1])
        dlat = math.radians(p2[1] - p1[1])
        dlng = math.radians(p2[0] - p1[0])
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _isom_profile(self, code: int) -> dict:
        """Profil sémantique d'un code ISOM depuis isom_semantics.json."""
        return self._isom_sem.get(str(code), {
            "mobility_weight": 0.3, "crossing_salience": 0.4,
            "misleading_potential": 0.3, "handrail_strength": 0.2,
        })

    @staticmethod
    def _seg_cross_t(
        ax: float, ay: float, bx: float, by: float,
        px: float, py: float, qx: float, qy: float,
    ):
        """Intersection paramétrique de AB × PQ. Retourne (t, s) ou (None, None)."""
        d1x, d1y = bx - ax, by - ay
        d2x, d2y = qx - px, qy - py
        denom = d1x * d2y - d1y * d2x
        if abs(denom) < 1e-10:
            return None, None
        dx, dy = px - ax, py - ay
        t = (dx * d2y - dy * d2x) / denom
        s = (dx * d1y - dy * d1x) / denom
        if 0.0 < t < 1.0 and 0.0 < s < 1.0:
            return t, s
        return None, None

    def _score_pp_ocad(
        self,
        lng0: float, lat0: float, lng1: float, lat1: float,
        ocad_segs: list,
        heatmap_cache,
    ) -> float:
        """Terme N OCAD : chemin longeant la jambe (segments OCAD praticables).

        Remplace score_parallel_path_choice (OSM) en forêt.
        Retourne un score ∈ [0, 1].
        """
        m_per_lat = 111000.0
        m_per_lng = 111000.0 * math.cos(math.radians((lat0 + lat1) / 2))
        bx_m = (lng1 - lng0) * m_per_lng
        by_m = (lat1 - lat0) * m_per_lat
        leg_m = math.sqrt(bx_m ** 2 + by_m ** 2)
        if leg_m < 1.0:
            return 0.0

        buf_min_m = max(30.0, 0.07 * leg_m)
        buf_max_m = min(400.0, 0.30 * leg_m)
        _mobile_codes = {501, 502, 503, 504, 505, 507, 508, 516, 305}

        intervals_left: list = []
        intervals_right: list = []

        for seg in ocad_segs:
            if seg.isom_code not in _mobile_codes:
                continue
            if seg.mobility_weight <= 0:
                continue

            p0, p1 = seg.p0, seg.p1
            p0x = (p0[0] - lng0) * m_per_lng
            p0y = (p0[1] - lat0) * m_per_lat
            p1x = (p1[0] - lng0) * m_per_lng
            p1y = (p1[1] - lat0) * m_per_lat

            # Parallélisme : cosine ≥ 0.64
            sdx, sdy = p1x - p0x, p1y - p0y
            seg_len = math.sqrt(sdx ** 2 + sdy ** 2)
            if seg_len < 0.5:
                continue
            cos_a = abs(sdx * bx_m + sdy * by_m) / (seg_len * leg_m)
            if cos_a < 0.64:
                continue

            # Projection t sur l'axe de la jambe [0,1]
            t0 = (p0x * bx_m + p0y * by_m) / (leg_m ** 2)
            t1 = (p1x * bx_m + p1y * by_m) / (leg_m ** 2)
            t_min, t_max = min(t0, t1), max(t0, t1)
            if t_max < 0 or t_min > 1:
                continue
            t_min, t_max = max(0.0, t_min), min(1.0, t_max)

            # Distance latérale au milieu du segment
            mx, my = (p0x + p1x) / 2, (p0y + p1y) / 2
            cross = mx * by_m - my * bx_m
            lat_dist_m = abs(cross) / leg_m
            if lat_dist_m < buf_min_m or lat_dist_m > buf_max_m:
                continue

            # Poids effectif (runnabilité multi-point)
            base_w = seg.mobility_weight
            if heatmap_cache is not None:
                samples = [
                    heatmap_cache.get_score(
                        p0[0] + t * (p1[0] - p0[0]),
                        p0[1] + t * (p1[1] - p0[1]),
                    )
                    for t in (0.25, 0.5, 0.75)
                ]
                local_run = sum(samples) / 3
                eff_w = base_w * (0.5 + 0.5 * local_run)
            else:
                eff_w = base_w

            if cross >= 0:
                intervals_left.append((t_min, t_max, eff_w))
            else:
                intervals_right.append((t_min, t_max, eff_w))

        def _union_w(intervals):
            if not intervals:
                return 0.0
            ivs = sorted(intervals)
            cs, ce, cw = ivs[0]
            total = 0.0
            for s, e, w in ivs[1:]:
                if s <= ce:
                    ce, cw = max(ce, e), max(cw, w)
                else:
                    total += (ce - cs) * cw
                    cs, ce, cw = s, e, w
            total += (ce - cs) * cw
            return total

        best = max(_union_w(intervals_left), _union_w(intervals_right))
        return min(best / 0.50, 1.0)

    def _score_lc_ocad(
        self,
        lng0: float, lat0: float, lng1: float, lat1: float,
        ocad_segs: list,
    ) -> float:
        """Terme O OCAD : saut de ligne via segments OCAD (courbes, fossés, chemins).

        Remplace score_line_crossing (OSM) en forêt.
        Retourne un score ∈ [0, 1].
        """
        qualities: list = []
        m_per_lng = 111000.0 * math.cos(math.radians((lat0 + lat1) / 2))
        m_per_lat = 111000.0
        dlng_m = (lng1 - lng0) * m_per_lng
        dlat_m = (lat1 - lat0) * m_per_lat
        leg_m = math.sqrt(dlng_m ** 2 + dlat_m ** 2)
        if leg_m < 1.0:
            return 0.0

        for seg in ocad_segs:
            if seg.crossing_salience <= 0:
                continue
            p0, p1 = seg.p0, seg.p1
            t, _ = self._seg_cross_t(lng0, lat0, lng1, lat1, p0[0], p0[1], p1[0], p1[1])
            if t is None or not (0.10 <= t <= 0.90):
                continue

            sdlng_m = (p1[0] - p0[0]) * m_per_lng
            sdlat_m = (p1[1] - p0[1]) * m_per_lat
            seg_len_m = math.sqrt(sdlng_m ** 2 + sdlat_m ** 2)
            if seg_len_m < 0.5:
                continue
            cos_a = abs(dlng_m * sdlng_m + dlat_m * sdlat_m) / (leg_m * seg_len_m)
            if cos_a >= 0.64:
                continue

            angle_q = 1.0 - cos_a / 0.64
            pos_q = 1.0 - abs(t - 0.5) * 2.0
            quality = seg.crossing_salience * pos_q * angle_q
            qualities.append(quality)

        if not qualities:
            return 0.0
        return min(sum(qualities) / len(qualities) / 0.80, 1.0)

    def _score_exit_clarity(
        self,
        ctrl_lng: float, ctrl_lat: float,
        next_lng: float, next_lat: float,
        ocad_segs: list,
    ) -> float:
        """Terme P : clarté de sortie de balise.

        Mesure l'ambiguïté directionnelle dans un rayon de 60m autour du poste.
        Retourne un score ∈ [0, 1] — 1.0 = sortie sans ambiguïté.
        """
        m_per_lat = 111000.0
        m_per_lng = 111000.0 * math.cos(math.radians(ctrl_lat))
        _ec_radius_m = 60.0
        radius_lat = _ec_radius_m / m_per_lat
        radius_lng = _ec_radius_m / m_per_lng

        exit_bearing = math.degrees(math.atan2(
            (next_lng - ctrl_lng) * m_per_lng,
            (next_lat - ctrl_lat) * m_per_lat,
        )) % 360

        reinforcing = 0.0
        misleading = 0.0

        for seg in ocad_segs:
            p0, p1 = seg.p0, seg.p1

            # Distance du poste au point le plus proche sur le segment
            sdlng = p1[0] - p0[0]
            sdlat = p1[1] - p0[1]
            seg_len_sq = sdlng ** 2 + sdlat ** 2
            if seg_len_sq < 1e-20:
                d_lng = (p0[0] - ctrl_lng) * m_per_lng
                d_lat = (p0[1] - ctrl_lat) * m_per_lat
            else:
                t_c = ((ctrl_lng - p0[0]) * sdlng + (ctrl_lat - p0[1]) * sdlat) / seg_len_sq
                t_c = max(0.0, min(1.0, t_c))
                cl = p0[0] + t_c * sdlng
                cla = p0[1] + t_c * sdlat
                d_lng = (cl - ctrl_lng) * m_per_lng
                d_lat = (cla - ctrl_lat) * m_per_lat

            dist_m = math.sqrt(d_lng ** 2 + d_lat ** 2)
            if dist_m > _ec_radius_m:
                continue

            strength = seg.misleading_potential * math.exp(-dist_m / 30.0)

            # Angle (bidirectionnel : segment a deux directions)
            seg_bearing = math.degrees(math.atan2(sdlng * m_per_lng, sdlat * m_per_lat)) % 360
            delta = abs(seg_bearing - exit_bearing) % 360
            if delta > 180:
                delta = 360 - delta
            delta = min(delta, 180 - delta)  # 0-90°: 0=parallel, 90=perpendicular

            if delta < 45:
                reinforcing += strength * (1.0 - delta / 45)
            else:
                misleading += strength * min((delta - 45) / 45, 1.0)

        return reinforcing / (reinforcing + misleading + 1e-6)

    def _build_leg_cognitive_profile(
        self,
        lng0: float, lat0: float,
        lng1: float, lat1: float,
        heatmap_cache,
    ):
        """Construit un LegIntentInference via l'index spatial pré-filtré.
        Niveau 1 : N/O/P + contour_crossing_guidance + direct_run_index + safety_recovery.
        """
        from .perceptual_model import LegIntentInference
        if self._seg_index is None:
            return LegIntentInference()

        m_per_lat = 111000.0
        cos_lat = math.cos(math.radians((lat0 + lat1) / 2))
        m_per_lng = 111000.0 * cos_lat
        leg_m = math.sqrt(((lng1 - lng0) * m_per_lng) ** 2 + ((lat1 - lat0) * m_per_lat) ** 2)

        # Corridor partagé N/O : max(half_width_N, 50m pour O)
        half_w = max(max(30.0, 0.30 * leg_m), 50.0)
        corridor = self._seg_index.query_corridor(lng0, lat0, lng1, lat1, half_w)
        exit_near = self._seg_index.query_radius(lng0, lat0, 60.0)

        parallel_affordance = self._score_pp_ocad(lng0, lat0, lng1, lat1, corridor, heatmap_cache)
        crossing_density = self._score_lc_ocad(lng0, lat0, lng1, lat1, corridor)
        exit_clarity = self._score_exit_clarity(lng0, lat0, lng1, lat1, exit_near)

        # ── RELIEF_CROSSING_GUIDANCE (contour_crossing_guidance) ─────────────────
        # Traversées transverses de contours (101-103) — slope crossing uniquement.
        # Convention bearing : atan2(Δlng, Δlat) — même convention que seg.bearing_rad.
        _CONTOUR_CODES = {101, 102, 103}
        # Convention bearing : atan2(Δlng, Δlat) → Nord=0, Est=π/2 (compas, non math).
        # Même formule que seg.bearing_rad dans perceptual_model._build_perceptual_feature → cohérence garantie.
        # Vérification : cos(Nord_seg - Est_leg) = cos(0 - π/2) = 0 (perpendiculaires ✓)
        leg_bearing = math.atan2(lng1 - lng0, lat1 - lat0)
        leg_m_approx = leg_m  # déjà calculé ci-dessus
        relief_crossings = 0.0
        _contour_total = 0
        _micro_rejects = 0
        for seg in corridor:
            if seg.isom_code not in _CONTOUR_CODES:
                continue
            _contour_total += 1
            if seg.length_m < 6.0:
                _micro_rejects += 1
                continue  # micro-segment : bearing instable (zig-zag OCAD)
            cos_angle = abs(math.cos(seg.bearing_rad - leg_bearing))
            if cos_angle >= 0.64:
                continue  # parallèle = pas un croisement de terrain
            relief_crossings += seg.crossing_salience * (1.0 - cos_angle / 0.64)
        contour_crossing_guidance = min(relief_crossings / max(leg_m_approx / 50.0, 1.0), 1.0)

        # ── DIRECT_RUN_INDEX ─────────────────────────────────────────────────────
        # "open low-guidance traversal" — proxy Phase A pour azimut.
        # openness_factor = runnabilité CNN (heatmap), PAS visibilité cognitive.
        guidance_feats = [f for f in corridor if f.handrail_strength > 0.5]
        guidance_density = len(guidance_feats) / max(leg_m_approx / 100.0, 1.0)
        if heatmap_cache is not None:
            _scores = [heatmap_cache.get_score(lng0 + t * (lng1 - lng0), lat0 + t * (lat1 - lat0))
                       for t in (0.25, 0.5, 0.75)]
            openness_factor = sum(_scores) / len(_scores)
        else:
            openness_factor = 0.5
        direct_run_index = max(0.0,
            (1.0 - min(guidance_density, 1.0)) * openness_factor * (1.0 - parallel_affordance)
        )

        # ── SAFETY_RECOVERY ──────────────────────────────────────────────────────
        # Ambiguïté sans structure — semi-redondant avec P (log-only longtemps).
        _support = max(parallel_affordance, contour_crossing_guidance)
        _noise = crossing_density * (1.0 - _support)
        safety_recovery = max(0.0, (1.0 - exit_clarity) * (1.0 - _support) * (0.5 + 0.5 * _noise))

        return (
            LegIntentInference(
                parallel_affordance=parallel_affordance,
                crossing_density=crossing_density,
                exit_clarity=exit_clarity,
                contour_crossing_guidance=contour_crossing_guidance,
                direct_run_index=direct_run_index,
                safety_recovery=safety_recovery,
            ),
            _contour_total,
            _micro_rejects,
        )

    def _classify_leg_type(
        self,
        jaccard: Optional[float],
        handrail: Optional[float],
        catch: Optional[float],
        pp_score: Optional[float] = None,
        lc_score: Optional[float] = None,
        clarity_score: Optional[float] = None,
    ) -> set:
        """Étiquettes navigables d'une jambe — SET non exclusif (Terme M).

        Tags possibles : route_choice, handrail, technical_read, parallel_path,
        line_crossing, clear_exit, direct.
        Utilise les seuils de placement_rules.json["leg_type_thresholds"].
        """
        rules = self._placement_rules.get("leg_type_thresholds", {})
        types: set = set()
        if jaccard is not None and jaccard >= rules.get("route_choice_jaccard", 0.30):
            types.add("route_choice")
        if handrail is not None and handrail >= rules.get("handrail_coverage", 0.70):
            types.add("handrail")
        if catch is not None and catch <= rules.get("low_catch_score", 0.30):
            types.add("technical_read")
        if pp_score is not None and pp_score >= rules.get("parallel_path_score", 0.40):
            types.add("parallel_path")
        if lc_score is not None and lc_score >= rules.get("line_crossing_score", 0.35):
            types.add("line_crossing")
        if clarity_score is not None and clarity_score >= 0.65:
            types.add("clear_exit")
        return types if types else {"direct"}

    def _osm_coverage_ratio(self, bbox: Optional[dict]) -> float:
        """Estimation de la densité OSM dans la bbox (heuristique edges/km²).

        Retourne un ratio ∈ [0, 1] — > 0.40 signifie couverture suffisante pour
        que le RouteAnalyzer produise des scores Jaccard fiables.
        Retourne 0.0 si RouteAnalyzer absent ou bbox invalide.
        """
        if self._route_analyzer is None or not bbox:
            return 0.0
        try:
            g = self._route_analyzer.graph
            n_edges = g.number_of_edges()
            if n_edges == 0:
                return 0.0
            # Aire approximative en km² (projection rectangulaire — OK pour ~10km)
            dlng = abs(bbox.get("max_x", 0) - bbox.get("min_x", 0))
            dlat = abs(bbox.get("max_y", 0) - bbox.get("min_y", 0))
            mid_lat = (bbox.get("min_y", 0) + bbox.get("max_y", 0)) / 2
            area_km2 = dlng * math.cos(math.radians(mid_lat)) * 111.0 * dlat * 111.0
            if area_km2 < 1e-6:
                return 0.0
            density = n_edges / area_km2  # edges/km²
            # Sprint urbain dense ≈ 300–800 ; forêt OSM sparse ≈ 20–80.
            # Seuil 50 edges/km² → ratio 1.0 (couverture suffisante).
            return min(1.0, density / 50.0)
        except Exception:
            return 0.0

    def _is_in_forbidden_zone(
        self,
        x: float,
        y: float,
        forbidden_zones: List[Dict],
    ) -> bool:
        """Vérifie si une position est dans une zone interdite.

        Supporte 2 formats :
          - Cercle : {x, y, radius}
          - Polygone WGS84 : {coordinates: [[lat, lng], ...]}
        """
        for zone in forbidden_zones:
            if "coordinates" in zone:
                if self._point_in_polygon(x, y, zone["coordinates"]):
                    return True
            elif "radius" in zone:
                dist = math.sqrt((x - zone.get("x", 0)) ** 2 + (y - zone.get("y", 0)) ** 2)
                if dist < zone.get("radius", 0):
                    return True
        return False

    def _point_in_polygon(self, x: float, y: float, polygon: List) -> bool:
        """Ray casting algorithm — point dans polygone [[lat, lng], ...]."""
        n = len(polygon)
        if n < 3:
            return False
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i][0], polygon[i][1]
            xj, yj = polygon[j][0], polygon[j][1]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def _select_parents(self) -> List[Circuit]:
        """Sélectionne les parents par tournoi."""
        parents = []
        tournament_size = 3

        for _ in range(self.config.population_size):
            # Tournoi
            candidates = random.sample(self.population, tournament_size)
            winner = max(candidates, key=lambda c: c.fitness)
            parents.append(winner)

        return parents

    def _crossover(self, parents: List[Circuit]) -> List[Circuit]:
        """Effectue le croisement Segment (spatial)."""
        offspring = []

        for i in range(0, len(parents) - 1, 2):
            parent1 = parents[i]
            parent2 = parents[i + 1]

            if random.random() < self.config.crossover_rate:
                child1, child2 = self._segment_crossover(parent1, parent2)
                offspring.append(child1)
                offspring.append(child2)
            else:
                offspring.append(Circuit(controls=parent1.controls.copy()))
                offspring.append(Circuit(controls=parent2.controls.copy()))

        return offspring

    def _ox_crossover(self, p1: Circuit, p2: Circuit) -> Tuple[Circuit, Circuit]:
        """Order Crossover pour les circuits."""
        n = len(p1.controls)
        # Sécurité : tailles différentes ou trop court → copie sans croisement
        if n != len(p2.controls) or n < 4:
            return Circuit(controls=list(p1.controls)), Circuit(controls=list(p2.controls))

        # Choisir deux points de croisement
        start_idx = random.randint(0, n - 2)
        end_idx = random.randint(start_idx + 1, n)

        # Enfant 1
        child1_controls = [None] * n
        child1_controls[start_idx:end_idx] = p1.controls[start_idx:end_idx]

        # Remplir avec l'ordre de p2
        p2_idx = 0
        for i in range(n):
            if child1_controls[i] is None:
                if p2_idx >= n:
                    break
                while p2.controls[p2_idx] in child1_controls:
                    p2_idx += 1
                    if p2_idx >= n:
                        break
                if p2_idx < n:
                    child1_controls[i] = p2.controls[p2_idx]
                    p2_idx += 1

        # Enfant 2 (inverse)
        child2_controls = [None] * n
        child2_controls[start_idx:end_idx] = p2.controls[start_idx:end_idx]

        p1_idx = 0
        for i in range(n):
            if child2_controls[i] is None:
                if p1_idx >= n:
                    break
                while p1.controls[p1_idx] in child2_controls:
                    p1_idx += 1
                    if p1_idx >= n:
                        break
                if p1_idx < n:
                    child2_controls[i] = p1.controls[p1_idx]
                    p1_idx += 1

        # Si None restants (positions dupliquées p.ex. départ==arrivée), copie sans croisement
        if None in child1_controls or None in child2_controls:
            return Circuit(controls=list(p1.controls)), Circuit(controls=list(p2.controls))
        return Circuit(controls=child1_controls), Circuit(controls=child2_controls)

    def _segment_crossover(self, p1: Circuit, p2: Circuit) -> Tuple[Circuit, Circuit]:
        """Segment Crossover spatial — remplace OX TSP.

        Trouve le point de jonction naturel entre les deux parents (la paire de contrôles
        internes la plus proche géographiquement) et effectue le croisement à ce point.
        Préserve des sous-tours géographiquement cohérents dans les enfants.
        Longueur du chromosome garantie par construction.
        """
        n = len(p1.controls)
        if n != len(p2.controls) or n < 4:
            return Circuit(controls=list(p1.controls)), Circuit(controls=list(p2.controls))

        inner_n = n - 2
        if inner_n < 2:
            return Circuit(controls=list(p1.controls)), Circuit(controls=list(p2.controls))

        inner1 = list(p1.controls[1:-1])
        inner2 = list(p2.controls[1:-1])

        # Point de coupe aléatoire dans [1, inner_n-1]
        cut = random.randint(1, inner_n - 1)

        # Ancre = dernier contrôle du premier segment de P1
        anchor = inner1[cut - 1]

        # j = contrôle de inner2 le plus proche de l'ancre (point de jonction naturel)
        j = min(range(inner_n), key=lambda k: self._haversine_m(anchor, inner2[k]))

        # Rotation de inner2 pour aligner inner2[j] à la position cut-1
        # → inner2_rot[cut-1] == inner2[j] : jonction géographique cohérente
        rotation = (j - cut + 1) % inner_n
        inner2_rot = inner2[rotation:] + inner2[:rotation]

        # Enfants : longueur = inner_n garantie (cut + (inner_n - cut) = inner_n)
        child1_inner = inner1[:cut] + inner2_rot[cut:]
        child2_inner = inner2_rot[:cut] + inner1[cut:]

        return (
            Circuit(controls=[p1.controls[0]] + child1_inner + [p1.controls[-1]]),
            Circuit(controls=[p2.controls[0]] + child2_inner + [p2.controls[-1]]),
        )

    def _mutate(
        self,
        circuits: List[Circuit],
        forbidden_zones: List[Dict],
    ) -> List[Circuit]:
        """Applique les mutations."""
        for circuit in circuits:
            if random.random() < self.config.mutation_rate:
                circuit.controls = self._mutate_circuit(
                    circuit.controls, forbidden_zones
                )

        return circuits

    def _mutate_circuit(
        self,
        controls: List[Tuple[float, float]],
        forbidden_zones: List[Dict],
    ) -> List[Tuple[float, float]]:
        """
        Mutation intelligente avec 3 stratégies :
        - random_walk (40%) : déplacement ±50m classique
        - leg_improvement (40%) : corrige le pire angle (dog-leg / demi-tour)
        - perturbation (20%) : déplacement fort ±100m pour exploration
        """
        if len(controls) < 3:
            return controls

        mutation_type = random.choices(
            ["random_walk", "leg_improvement", "perturbation"],
            weights=[0.40, 0.40, 0.20],
        )[0]

        if mutation_type == "leg_improvement" and len(controls) >= 4:
            return self._mutate_leg_improvement(controls, forbidden_zones)
        elif mutation_type == "perturbation":
            return self._mutate_perturbation(controls, forbidden_zones)
        else:
            return self._mutate_random_walk(controls, forbidden_zones)

    def _mutate_random_walk(
        self,
        controls: List[Tuple[float, float]],
        forbidden_zones: List[Dict],
    ) -> List[Tuple[float, float]]:
        """Déplacement ±12% d'une jambe cible d'un poste aléatoire (WGS84 en degrés).

        Proportionnel à la longueur cible : ±30m pour sprint, ±56m pour circuit long.
        """
        idx = random.randint(1, len(controls) - 2)
        leg_m = self.config.target_length_m / max(self.config.target_controls, 1)
        delta_m = random.uniform(-leg_m * 0.12, leg_m * 0.12)
        x = controls[idx][0] + delta_m / 72600
        y = controls[idx][1] + delta_m / 111000
        # Clamp à la bounding box (évite postes dans le blanc hors-carte)
        if self.config.bounding_box:
            bb = self.config.bounding_box
            x = max(bb["min_x"], min(bb["max_x"], x))
            y = max(bb["min_y"], min(bb["max_y"], y))
        # 60% snap vers la feature OCAD ISOM la plus attractive dans ≤50m
        if self._ocad_tree is not None and random.random() < 0.60:
            _cp, _d = self._best_att_ocad(x, y, 50,
                prefer_isom=self._td1_prefer_isom, prefer_max_dist_m=self._td1_prefer_max_dist_m)
            if _cp:
                x, y = _cp["x"], _cp["y"]
        if not self._is_in_forbidden_zone(x, y, forbidden_zones):
            controls[idx] = (x, y)
        return controls

    def _mutate_leg_improvement(
        self,
        controls: List[Tuple[float, float]],
        forbidden_zones: List[Dict],
    ) -> List[Tuple[float, float]]:
        """
        Trouve le poste avec le pire angle (dog-leg ou demi-tour)
        et le repositionne perpendiculairement à la droite prev→next.
        """
        worst_score = -1.0
        worst_idx = -1

        for i in range(1, len(controls) - 1):
            prev, curr, nxt = controls[i-1], controls[i], controls[i+1]
            in_a = math.atan2(curr[1]-prev[1], curr[0]-prev[0])
            out_a = math.atan2(nxt[1]-curr[1],  nxt[0]-curr[0])
            diff = abs(math.degrees(out_a - in_a)) % 360
            if diff > 180:
                diff = 360 - diff
            # Score de "mauvais angle" : max pour dog-leg (0°) ou demi-tour (180°)
            angle_badness = abs(diff - 90)  # 0 = parfait (90°), 90 = pire
            if angle_badness > worst_score:
                worst_score = angle_badness
                worst_idx = i

        if worst_idx == -1:
            return self._mutate_random_walk(controls, forbidden_zones)

        prev, nxt = controls[worst_idx-1], controls[worst_idx+1]
        mid_x = (prev[0] + nxt[0]) / 2
        mid_y = (prev[1] + nxt[1]) / 2

        # Vecteur perpendiculaire à prev→nxt
        dx = nxt[0] - prev[0]
        dy = nxt[1] - prev[1]
        length = math.sqrt(dx**2 + dy**2)
        if length == 0:
            return self._mutate_random_walk(controls, forbidden_zones)

        perp_x = -dy / length
        perp_y =  dx / length
        # offset en mètres converti en degrés WGS84
        offset_m = random.uniform(60, 150)
        sign = random.choice([-1, 1])
        new_x = mid_x + perp_x * (offset_m / 72600) * sign
        new_y = mid_y + perp_y * (offset_m / 111000) * sign
        # Clamp à la bounding box
        if self.config.bounding_box:
            bb = self.config.bounding_box
            new_x = max(bb["min_x"], min(bb["max_x"], new_x))
            new_y = max(bb["min_y"], min(bb["max_y"], new_y))

        # Snap vers la feature OCAD ISOM la plus attractive dans ≤50m
        # → évite d'atterrir dans le vide cartographique après le repositionnement géométrique
        if self._ocad_tree is not None and random.random() < 0.60:
            _cp, _d = self._best_att_ocad(new_x, new_y, 50,
                prefer_isom=self._td1_prefer_isom, prefer_max_dist_m=self._td1_prefer_max_dist_m)
            if _cp:
                new_x, new_y = _cp["x"], _cp["y"]

        if not self._is_in_forbidden_zone(new_x, new_y, forbidden_zones):
            controls[worst_idx] = (new_x, new_y)
        return controls

    def _mutate_perturbation(
        self,
        controls: List[Tuple[float, float]],
        forbidden_zones: List[Dict],
    ) -> List[Tuple[float, float]]:
        """Déplacement fort ±25% d'une jambe cible pour sortir des minima locaux.

        40% de probabilité de snapper sur un feature OCAD attractif voisin.
        Proportionnel à la longueur cible : ±62m pour sprint, ±117m pour circuit long.
        """
        idx = random.randint(1, len(controls) - 2)
        leg_m = self.config.target_length_m / max(self.config.target_controls, 1)
        delta_m = random.uniform(-leg_m * 0.25, leg_m * 0.25)
        x = controls[idx][0] + delta_m / 72600
        y = controls[idx][1] + delta_m / 111000
        # Clamp à la bounding box
        if self.config.bounding_box:
            bb = self.config.bounding_box
            x = max(bb["min_x"], min(bb["max_x"], x))
            y = max(bb["min_y"], min(bb["max_y"], y))
        # Snap vers la feature OCAD ISOM la plus attractive dans ≤80m
        if self._ocad_tree is not None and random.random() < 0.80:
            _cp, _d = self._best_att_ocad(x, y, 80,
                prefer_isom=self._td1_prefer_isom, prefer_max_dist_m=self._td1_prefer_max_dist_m)
            if _cp:
                x, y = _cp["x"], _cp["y"]
        elif random.random() < 0.40:
            cp = self._find_nearest_cp(x, y, leg_m * 2.0)
            if cp:
                x, y = cp
        if not self._is_in_forbidden_zone(x, y, forbidden_zones):
            controls[idx] = (x, y)
        return controls

    def evaluate_fitness(
        self,
        controls: List[Tuple[float, float]],
        config: GenerationConfig,
    ) -> float:
        """
        Fitness multicritère d'un chromosome ordonné (parcours point-to-point).

        Le parcours est traité comme une séquence ordonnée D→P1→P2→…→A.
        Maximiser ce score produit des circuits visuellement attractifs,
        respectant la distance cible et sans dog-legs IOF.

        Critères :
          A (+) AI Score      — score V2 moyen par HeatmapCache lookup O(1)
          B (-) Distance      — pénalité relative erreur longueur totale vs cible
          C (-) Dog-legs      — pénalité éliminatoire par angle intérieur < seuil IOF
          D (+) Rythme        — bonus CV (écart-type / moyenne) des inter-postes

        Args:
            controls: Liste ordonnée [(lng, lat)] incluant départ et arrivée.
            config:   GenerationConfig avec target_length_m, heatmap_cache, etc.

        Returns:
            float — score global, à maximiser. Peut être négatif pour mauvais circuits.
        """
        if len(controls) < 2:
            return -100.0

        # ── A. Score IA (HeatmapCache lookup) ──────────────────────────────
        if config.heatmap_cache is not None:
            ai_scores = np.array(
                [config.heatmap_cache.query(lng, lat) for lng, lat in controls]
            )
            ai_score = float(ai_scores.mean())
        else:
            # Fallback : attractivité ISOM rule-based (comportement existant)
            ai_score = self._terrain_quality_score_isom(controls) / 100.0

        # ── B. Pénalité distance ────────────────────────────────────────────
        leg_m = np.array([
            self._haversine_m(controls[i], controls[i + 1])
            for i in range(len(controls) - 1)
        ], dtype=np.float64)
        total_m = float(leg_m.sum())
        target_m = config.target_length_m
        dist_error = abs(total_m - target_m) / max(target_m, 1.0)
        dist_penalty = dist_error  # [0, ∞] — 1.0 = erreur 100%

        # ── C. Pénalité dog-leg (angle intérieur < seuil IOF) ─────────────
        # IMPORTANT : vecteurs partent DEPUIS le poste i vers l'extérieur.
        # Droite → angle intérieur ≈ 180° → pas de pénalité.
        # Aller-retour → angle intérieur ≈ 0° → dog-leg éliminatoire.
        dog_leg_threshold = float(self._placement_rules.get("dog_leg_angle_deg", 60.0))
        n_dogleg = 0
        for i in range(1, len(controls) - 1):
            # v1 : du poste i vers le poste PRÉCÉDENT
            dx1 = controls[i - 1][0] - controls[i][0]
            dy1 = controls[i - 1][1] - controls[i][1]
            # v2 : du poste i vers le poste SUIVANT
            dx2 = controls[i + 1][0] - controls[i][0]
            dy2 = controls[i + 1][1] - controls[i][1]
            norm1 = math.hypot(dx1, dy1)
            norm2 = math.hypot(dx2, dy2)
            if norm1 < 1e-10 or norm2 < 1e-10:
                continue
            cos_a = (dx1 * dx2 + dy1 * dy2) / (norm1 * norm2)
            angle_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))
            if angle_deg < dog_leg_threshold:
                n_dogleg += 1
        angle_penalty = float(n_dogleg) * 20.0  # −20 pts par dog-leg

        # ── D. Bonus de rythme (coefficient de variation des inter-postes) ─
        if len(leg_m) >= 2:
            mean_leg = float(leg_m.mean())
            rhythm = float(leg_m.std() / (mean_leg + 1e-6))  # CV [0, ∞]
            rhythm = min(rhythm, 0.8)  # cap : évite de récompenser circuits pathologiques
        else:
            rhythm = 0.0

        # ── L. Conformité longueur jambes au profil format ────────────────────
        # Pénalise les circuits dont la longueur moyenne de jambe s'éloigne de la
        # cible IOF par format : Sprint ~250m, MD ~600m, LD ~2000m.
        # Complète terme D (CV) qui récompense la variété sans tenir compte du format.
        _TARGET_LEG_M = {"sprint": 250.0, "md": 600.0, "ld": 2000.0, "foret": 600.0}
        _ct = (config.circuit_type or "forest").lower()
        _target_leg = _TARGET_LEG_M.get(_ct, 600.0)
        _n_legs = len(leg_m)
        _mean_leg = float(leg_m.mean()) if _n_legs > 0 else _target_leg
        _leg_conformity = 1.0 - min(abs(_mean_leg - _target_leg) / _target_leg, 1.0)

        # Niveau TD (1-5) — utilisé par les termes E, N, M pour gater les règles
        # de choix d'itinéraire inadaptées aux jeunes/débutants (TD1=Blanc, TD2=Orange).
        _td_level = int(config.technical_level or 3)

        # ── E. Route diversity ─────────────────────────────────────────────────
        # Priorité OSM (RouteAnalyzer) si disponible ET jambe assez longue ET
        # couverture OSM suffisante. Fallback GPX Vikazimut sinon.
        # Inactif pour TD≤2 (circuits linéaires, aucun choix tactique attendu).
        # Bonus maximal ≈ +4.5 pts (jaccard=0.50) ; malus ≈ −3 pts (jaccard=0.00).
        diversity_bonus = 0.0
        _per_leg_jaccard: list = []   # None ou float — Terme M
        _per_leg_pp: list = []        # None ou float — Terme N (chemin parallèle)
        _per_leg_lc: list = []        # None ou float — Terme O (saut de ligne)
        _per_leg_clarity: list = []   # None ou float — Terme P (exit clarity)
        _ocad_segs: list = getattr(config, "ocad_line_segments", [])
        _rc_min = float(
            self._placement_rules.get("route_choice_leg_min_m", {}).get(_ct, 80.0)
        )
        _use_osm = (
            self._route_analyzer is not None
            and self._osm_coverage_ratio(config.bounding_box) > 0.40
        )
        for i in range(len(controls) - 1):
            p0, p1 = controls[i], controls[i + 1]
            _leg_dist = self._haversine_m(p0, p1)
            if _use_osm and _leg_dist > _rc_min:
                div = self._route_analyzer.route_diversity_info(
                    p0[0], p0[1], p1[0], p1[1]
                )
                _j = div["jaccard"]
                _per_leg_jaccard.append(_j)
                if _td_level >= 3:
                    if _ct == "sprint":
                        # En sprint TD3+ : récompenser les choix G/D visuellement ambigus.
                        # similarity_ratio = min_dist/max_dist — 1.0 = longueurs identiques.
                        # Inactif en TD1/TD2 : jeunes coureurs sur parcours linéaires.
                        _sim = div.get("similarity_ratio", 0.0)
                        _sim_bonus = 1.0 if _sim >= 0.85 else (_sim / 0.85)
                        _choice_score = _j * _sim_bonus  # ∈ [0, 1]
                        diversity_bonus += (_choice_score - 0.15) * 15.0
                    else:
                        diversity_bonus += (_j - 0.20) * 15.0
                # TD1/TD2 : jaccard enregistré pour Terme M, mais aucun bonus/malus.
            else:
                _per_leg_jaccard.append(None)
                if self._leg_diversity_db and _td_level >= 3:
                    cv = self._lookup_leg_cv(controls[i], controls[i + 1])
                    if cv is not None:
                        diversity_bonus += (cv - 0.20) * 15.0

        # ── F. Pénalité zones interdites (HeatmapCache.is_forbidden) ─────────
        # Pénalise les postes qui tombent dans le forbidden_mask (vert olive, eau,
        # bâtiments dilatés) même si forbidden_zones JSON ne les couvre pas.
        forbidden_penalty = 0.0
        if config.heatmap_cache is not None and config.heatmap_cache.forbidden_mask is not None:
            for lng, lat in controls[1:-1]:  # hors départ et arrivée
                if config.heatmap_cache.is_forbidden(lng, lat):
                    forbidden_penalty += 50.0

        # ── G. Pénalité dénivelé (D+/distance > seuil IOF) ───────────────────
        # Estime le D+ via ElevationCache (grille SRTM/IGN précomputée).
        # Pénalise si le ratio D+/distance_totale dépasse max_climb_ratio (défaut 4% IOF).
        # Fallback silencieux si elevation_cache absent ou données insuffisantes.
        dplus_penalty = 0.0
        if config.elevation_cache is not None and total_m > 0:
            estimated_dplus = config.elevation_cache.estimate_dplus(controls)
            max_climb_ratio = float(self._placement_rules.get("max_climb_ratio", 0.04))
            dplus_ratio = estimated_dplus / total_m
            if dplus_ratio > max_climb_ratio:
                _dp_mod = float(
                    self._placement_rules.get("d_plus_penalty_modulation", {}).get(_ct, 1.0)
                )
                dplus_penalty = (dplus_ratio - max_climb_ratio) * 200.0 * _dp_mod

        # ── H. Score de forme géométrique (aspect du tracé) ──────────────────
        # Indépendant du terrain — pénalise Z-patterns, spirales, accordéons.
        # Fallback 0.5 (neutre) si < 4 contrôles.
        shape_score = self._compute_shape_score(controls, config.bounding_box)

        # ── I. Qualité point d'attaque ─────────────────────────────────────────
        # ── J. Ligne d'arrêt ──────────────────────────────────────────────────
        # ── K. Main courante ──────────────────────────────────────────────────
        # Conditionnels au KDTree OCAD. Sans KDTree : score neutre 0.5, impact nul.
        _nav = self._nav_params
        _r_att = _nav.get("attack_radius_m", 0)
        _r_cat = _nav.get("catching_radius_m", 0)

        attack_scores_f: list = []
        if _nav.get("attack_required") and self._ocad_tree is not None and _r_att > 0:
            for i in range(1, len(controls)):
                cx, cy = controls[i][0], controls[i][1]
                px, py = controls[i - 1][0], controls[i - 1][1]
                attack_scores_f.append(self._score_attack_point(cx, cy, px, py, _r_att))
        attack_score_f = sum(attack_scores_f) / len(attack_scores_f) if attack_scores_f else 0.5

        catch_scores_f: list = []
        if _r_cat > 0 and self._ocad_tree is not None:
            for i in range(1, len(controls)):
                cx, cy = controls[i][0], controls[i][1]
                px, py = controls[i - 1][0], controls[i - 1][1]
                catch_scores_f.append(self._score_catching_feature(cx, cy, px, py, _r_cat))
        catch_score_f = sum(catch_scores_f) / len(catch_scores_f) if catch_scores_f else 0.5

        hr_scores_f: list = []
        handrail_score_f = 0.5
        if _nav.get("handrail_required") and self._ocad_tree is not None:
            for i in range(1, len(controls)):
                cx, cy = controls[i][0], controls[i][1]
                px, py = controls[i - 1][0], controls[i - 1][1]
                hr_scores_f.append(self._score_handrail(px, py, cx, cy))
            handrail_score_f = sum(hr_scores_f) / len(hr_scores_f) if hr_scores_f else 0.5

        W_ATTACK = 8.0
        W_CATCH = 6.0
        W_HANDRAIL = 5.0
        nav_score_i = W_ATTACK * (attack_score_f - 0.5)
        _w_catch_eff = W_CATCH if _nav.get("catching_required") else W_CATCH * 0.4
        nav_score_j = _w_catch_eff * (catch_score_f - 0.5)
        if _nav.get("handrail_required") and hr_scores_f:
            _cov_min = _nav.get("handrail_coverage_min", 0.0)
            if handrail_score_f >= _cov_min:
                nav_score_k = W_HANDRAIL * handrail_score_f
            else:
                nav_score_k = -W_HANDRAIL * (_cov_min - handrail_score_f) * 3
        else:
            nav_score_k = 0.0

        # Pénalité worst-leg : pénalise si >max_bad_leg_ratio des jambes sous seuil
        _min_catch = _nav.get("min_leg_catch_score", 0.0)
        _min_hr = _nav.get("min_leg_handrail_score", 0.0)
        _max_bad = _nav.get("max_bad_leg_ratio", 1.0)
        nav_worst_leg = 0.0
        if _nav.get("catching_required") and catch_scores_f and _min_catch > 0:
            n_bad = sum(1 for s in catch_scores_f if s < _min_catch)
            if n_bad / len(catch_scores_f) > _max_bad:
                nav_worst_leg -= W_CATCH * 2 * (n_bad / len(catch_scores_f))
        if _nav.get("handrail_required") and hr_scores_f and _min_hr > 0:
            n_bad_hr = sum(1 for s in hr_scores_f if s < _min_hr)
            if n_bad_hr / len(hr_scores_f) > _max_bad:
                nav_worst_leg -= W_HANDRAIL * 2 * (n_bad_hr / len(hr_scores_f))

        # ── N / O / P — via LegIntentInference ───────────────────────────────────
        # OCAD : index spatial pré-filtré (O(log n + k) par jambe).
        # Fallback OSM pour N/O si pas d'index OCAD et route_analyzer disponible.
        _is_forest_ct = _ct in {"md", "ld", "forest", "foret"}
        W_PARALLEL = 6.0
        W_LINE_CROSSING = 5.0
        W_EXIT_CLARITY = 4.0
        parallel_bonus = line_crossing_bonus = exit_clarity_bonus = 0.0

        _pp_min = float(self._placement_rules.get("parallel_path_min_leg_m", {}).get(_ct, 250.0))
        _lc_min = float(self._placement_rules.get("line_crossing_min_leg_m", {}).get(_ct, 150.0))
        _pp_thr = self._placement_rules.get("leg_type_thresholds", {}).get("parallel_path_score", 0.40)
        _lc_thr = self._placement_rules.get("leg_type_thresholds", {}).get("line_crossing_score", 0.35)
        _use_cog = self._seg_index is not None

        pp_scores: list = []
        lc_scores: list = []
        clarity_scores_raw: list = []

        # Phase A — collecte intent vectors + telemetry (log-only, pas de fitness)
        from .perceptual_model import LegIntentInference as _LII
        _intent_vectors: list = []
        _intent_norms: list = []
        _leg_densities: list = []
        _leg_direct_run: list = []
        _leg_relief: list = []
        _dominant_hist: dict = {}
        _leg_parallel: list = []
        _leg_safety: list = []
        _leg_clarity: list = []
        _leg_crossing: list = []
        _relief_contour_total: int = 0
        _relief_micro_rejects: int = 0

        for i in range(len(controls) - 1):
            _leg_m_i = self._haversine_m(controls[i], controls[i + 1])

            if _use_cog and _td_level >= 2:
                cog, _seg_contour_n, _seg_micro_n = self._build_leg_cognitive_profile(
                    controls[i][0], controls[i][1],
                    controls[i + 1][0], controls[i + 1][1],
                    config.heatmap_cache,
                )
                clarity_scores_raw.append(cog.exit_clarity)
                _per_leg_clarity.append(cog.exit_clarity)

                # Phase A : vecteur intent 6-dim — gate max(v) > 0.25 (évite phantom diversity)
                _vec = tuple(cog.navigation_evidence[k] for k in _LII.INTENT_KEYS)
                _leg_densities.append(cog.activation_density)
                _leg_direct_run.append(cog.direct_run_index)
                _leg_relief.append(cog.contour_crossing_guidance)
                _leg_parallel.append(cog.parallel_affordance)
                _leg_safety.append(cog.safety_recovery)
                _leg_clarity.append(cog.exit_clarity)
                _leg_crossing.append(cog.crossing_density)
                _relief_contour_total += _seg_contour_n
                _relief_micro_rejects += _seg_micro_n
                _dom = cog.dominant_intent
                _dominant_hist[_dom] = _dominant_hist.get(_dom, 0) + 1
                if max(_vec) > 0.25:
                    _norm = math.sqrt(sum(x * x for x in _vec)) or _LII._EPS
                    _intent_vectors.append(_vec)
                    _intent_norms.append(_norm)

                if _is_forest_ct and _td_level >= 3:
                    if _leg_m_i >= _pp_min:
                        pp_scores.append(cog.parallel_affordance)
                        _per_leg_pp.append(cog.parallel_affordance)
                    else:
                        _per_leg_pp.append(None)
                    if _leg_m_i >= _lc_min:
                        lc_scores.append(cog.crossing_density)
                        _per_leg_lc.append(cog.crossing_density)
                    else:
                        _per_leg_lc.append(None)
                else:
                    _per_leg_pp.append(None)
                    _per_leg_lc.append(None)

            else:
                # Fallback OSM pour N/O (pas d'index OCAD)
                _per_leg_clarity.append(None)
                if _is_forest_ct and _td_level >= 3:
                    if _leg_m_i >= _pp_min:
                        if self._route_analyzer is not None:
                            _pp_s = self._route_analyzer.score_parallel_path_choice(
                                controls[i][0], controls[i][1],
                                controls[i + 1][0], controls[i + 1][1],
                                min_leg_m=_pp_min,
                            )
                            pp_scores.append(_pp_s)
                            _per_leg_pp.append(_pp_s)
                        else:
                            _per_leg_pp.append(None)
                    else:
                        _per_leg_pp.append(None)
                    if _leg_m_i >= _lc_min:
                        if self._route_analyzer is not None:
                            _lc_s = self._route_analyzer.score_line_crossing(
                                controls[i][0], controls[i][1],
                                controls[i + 1][0], controls[i + 1][1],
                                min_leg_m=_lc_min,
                            )
                            lc_scores.append(_lc_s)
                            _per_leg_lc.append(_lc_s)
                        else:
                            _per_leg_lc.append(None)
                    else:
                        _per_leg_lc.append(None)
                else:
                    _per_leg_pp.append(None)
                    _per_leg_lc.append(None)

        # Phase A — diversité cosine + telemetry JSON (log-only, NE PAS injecter dans fitness)
        _circuit_diversity = 0.0
        _circuit_transition_cost = 0.0
        _nv = len(_intent_vectors)
        _n_eligible = len(_leg_densities)

        if _nv >= 4:
            def _cdist(i, j):
                dot = sum(_intent_vectors[i][k] * _intent_vectors[j][k] for k in range(6))
                return 1.0 - dot / (_intent_norms[i] * _intent_norms[j])

            _pairwise = [_cdist(i, j) for i in range(_nv) for j in range(i + 1, _nv)]
            _circuit_diversity = sum(_pairwise) / len(_pairwise)
            _trans = [_cdist(i, i + 1) for i in range(_nv - 1)]
            _circuit_transition_cost = sum(_trans) / len(_trans) if _trans else 0.0

        if _leg_densities:
            # Helpers locaux — 3 usages, YAGNI
            def _pct(xs, q):
                ys = sorted(xs)
                return ys[int(q * (len(ys) - 1))]

            def _corr(xs, ys):
                # zip en premier — cohérence de n garantie même si len(xs)≠len(ys)
                pairs = list(zip(xs, ys))
                n = len(pairs)
                if n < 3:
                    return 0.0
                mx = sum(x for x, _ in pairs) / n
                my = sum(y for _, y in pairs) / n
                num = sum((x - mx) * (y - my) for x, y in pairs)
                dx = sum((x - mx) ** 2 for x, _ in pairs) ** 0.5
                dy = sum((y - my) ** 2 for _, y in pairs) ** 0.5
                return num / (dx * dy) if dx * dy > 1e-9 else 0.0

            _mean_dens   = sum(_leg_densities) / len(_leg_densities)
            _mean_direct = sum(_leg_direct_run) / len(_leg_direct_run)
            _mean_relief = sum(_leg_relief) / len(_leg_relief)
            _mean_safety = sum(_leg_safety) / len(_leg_safety)

            _pct90_density = _pct(_leg_densities, 0.9)
            _pct90_direct  = _pct(_leg_direct_run, 0.9)
            _pct90_relief  = _pct(_leg_relief, 0.9)

            _corr_safety_pamb     = _corr(_leg_safety, [1.0 - c for c in _leg_clarity])
            _corr_direct_parallel = _corr(_leg_direct_run, _leg_parallel)
            _corr_relief_crossing = _corr(_leg_relief, _leg_crossing)

            _relief_micro_ratio = (_relief_micro_rejects / _relief_contour_total
                                   if _relief_contour_total else 0.0)

            # Baseline sémantique : shuffle composantes (préserve magnitude, détruit structure)
            # Estime "semantic-randomized diversity ceiling" — PAS une navigation réaliste aléatoire.
            _random_baseline_diversity = 0.0
            if _nv >= 4:
                _baseline_k = 3 if _nv > 24 else 5
                _baseline_trials = []
                for _ in range(_baseline_k):
                    _sv = [list(v) for v in _intent_vectors]
                    for _row in _sv:
                        random.shuffle(_row)
                    _sn = [math.sqrt(sum(x * x for x in _row)) or _LII._EPS for _row in _sv]
                    _bp = [
                        1.0 - sum(_sv[i][k] * _sv[j][k] for k in range(6)) / (_sn[i] * _sn[j])
                        for i in range(_nv) for j in range(i + 1, _nv)
                    ]
                    _baseline_trials.append(sum(_bp) / len(_bp) if _bp else 0.0)
                _random_baseline_diversity = sum(_baseline_trials) / len(_baseline_trials)

            import json as _json, hashlib as _hashlib
            _circuit_id = _hashlib.md5(
                str([(round(c[0], 5), round(c[1], 5)) for c in controls]).encode()
            ).hexdigest()[:10]

            _intent_payload = {
                "schema": 1,
                "circuit_id": _circuit_id,
                "td": _td_level,
                "course_type": "forest" if _is_forest_ct else "sprint",
                "legs": len(controls) - 1,
                "intent_diversity":  round(_circuit_diversity, 4),
                "intent_transition": round(_circuit_transition_cost, 4),
                "eligible_legs":     _n_eligible,
                "active_legs":       _nv,
                "active_ratio":      round(_nv / _n_eligible, 4) if _n_eligible else 0.0,
                "intent_gate_threshold": 0.25,
                "density_mean":  round(_mean_dens, 4),
                "density_p90":   round(_pct90_density, 4),
                "direct_mean":   round(_mean_direct, 4),
                "direct_p90":    round(_pct90_direct, 4),
                "relief_mean":   round(_mean_relief, 4),
                "relief_p90":    round(_pct90_relief, 4),
                "safety_mean":   round(_mean_safety, 4),
                "corr_safety_pamb":     round(_corr_safety_pamb, 3),
                "corr_direct_parallel": round(_corr_direct_parallel, 3),
                "corr_relief_crossing": round(_corr_relief_crossing, 3),
                "relief_contour_total":  _relief_contour_total,
                "relief_micro_rejects":  _relief_micro_rejects,
                "relief_micro_ratio":    round(_relief_micro_ratio, 3),
                "random_baseline_diversity": round(_random_baseline_diversity, 4),
                "diversity_vs_baseline":     round(_circuit_diversity - _random_baseline_diversity, 4),
                "dominant_hist":         _dominant_hist,
                "intent_vector_count":   _nv,
            }
            print("[intent_json]" + _json.dumps(_intent_payload, separators=(",", ":")), flush=True)

            import os as _os, csv as _csv, pathlib as _pl
            if _os.environ.get("INTENT_DEBUG_CSV") == "1" and (int(_circuit_id[:6], 16) % 20) == 0:
                _debug_dir = _pl.Path(__file__).parent.parent.parent.parent / "debug"
                _debug_dir.mkdir(parents=True, exist_ok=True)
                _csv_path = _debug_dir / "intent_metrics.csv"
                _write_header = not _csv_path.exists()
                _csv_row = {**_intent_payload, "dominant_hist": str(_dominant_hist)}
                with open(_csv_path, "a", newline="", encoding="utf-8") as _cf:
                    _w = _csv.DictWriter(_cf, fieldnames=list(_csv_row.keys()))
                    if _write_header:
                        _w.writeheader()
                    _w.writerow(_csv_row)

        if pp_scores:
            parallel_bonus = W_PARALLEL * sum(1 for s in pp_scores if s >= _pp_thr) / len(pp_scores)
        if lc_scores:
            line_crossing_bonus = W_LINE_CROSSING * sum(1 for s in lc_scores if s >= _lc_thr) / len(lc_scores)
        if clarity_scores_raw:
            exit_clarity_bonus = W_EXIT_CLARITY * sum(clarity_scores_raw) / len(clarity_scores_raw)

        # ── M. Diversité des types de legs ────────────────────────────────────
        # Récompense les circuits qui mélangent route choice, main courante et lecture
        # technique. Neutre (W=0) pour TD ≤ 2 — trop complexe pour les circuits enfants.
        # Ablation study Phase 0 confirme l'utilité avant d'augmenter le poids.
        W_LEG_DIVERSITY = 0.0 if (_td_level <= 2 or config.ablation_disable_leg_diversity) else 4.0
        leg_diversity_bonus = 0.0
        if W_LEG_DIVERSITY > 0:
            _n_legs = len(controls) - 1
            _all_tags: set = set()
            for _i in range(_n_legs):
                _jac = _per_leg_jaccard[_i] if _i < len(_per_leg_jaccard) else None
                _hr = hr_scores_f[_i] if _i < len(hr_scores_f) else None
                _cat = catch_scores_f[_i] if _i < len(catch_scores_f) else None
                _pp = _per_leg_pp[_i] if _i < len(_per_leg_pp) else None
                _lc = _per_leg_lc[_i] if _i < len(_per_leg_lc) else None
                _cl = _per_leg_clarity[_i] if _i < len(_per_leg_clarity) else None
                _all_tags.update(self._classify_leg_type(_jac, _hr, _cat, _pp, _lc, _cl))
            # len ∈ [1,7] → score ∈ [0.14, 1.0] (7 tags possibles désormais)
            leg_diversity_bonus = W_LEG_DIVERSITY * len(_all_tags) / 7.0

        # ── Score final (à maximiser) ───────────────────────────────────────
        # Seuils depuis FFCORulesEngine si disponible, sinon valeurs historiques
        if self._thresholds is not None:
            W_AI = self._thresholds.w_ai
            W_DIST = self._thresholds.w_dist
            W_ANGLE = self._thresholds.w_angle
            W_RHYTHM = self._thresholds.w_rhythm
            _density_mult = self._thresholds.density_penalty_mult
        else:
            W_AI = 30.0
            W_DIST = 40.0    # poids fort — respect de la distance cible
            W_ANGLE = 1.0    # multiplicateur × 20 par dog-leg → éliminatoire
            W_RHYTHM = 15.0
            _density_mult = 50.0
        W_SHAPE = 15.0  # forme géométrique — anti-Z/spirale/accordéon (H5 actif)
        W_LEG_PROFILE = 8.0  # conformité longueur jambes au profil format IOF

        # Pénalité quadratique si trop peu de postes par rapport à la cible
        n_postes = len(controls) - 2  # hors départ et arrivée
        deficit = max(0, config.target_controls - 2 - n_postes)
        density_penalty = deficit ** 2 * _density_mult if deficit > 0 else 0.0

        return (
            W_AI * ai_score
            - W_DIST * dist_penalty
            - W_ANGLE * angle_penalty
            + W_RHYTHM * rhythm
            + W_LEG_PROFILE * _leg_conformity
            + W_SHAPE * shape_score
            - density_penalty
            + diversity_bonus
            - forbidden_penalty
            - dplus_penalty
            + nav_score_i
            + nav_score_j
            + nav_score_k
            + nav_worst_leg
            + parallel_bonus
            + line_crossing_bonus
            + exit_clarity_bonus
            + leg_diversity_bonus
        )

    def _compute_shape_score(
        self,
        controls: List[Tuple[float, float]],
        bounding_box: dict,
    ) -> float:
        """
        Terme H : score de forme géométrique du circuit (0–1).

        Évalue l'aspect visuel du tracé indépendamment du terrain.
        Pénalise les Z-patterns, spirales, accordéons et circuits trop groupés.

        H1 (35%) — Winding balance   : somme des angles de virage signés ≈ 0
        H2 (30%) — Variance circulaire: diversité des directions de jambes
        H3 (20%) — Runs consécutifs  : pas de séquence de N jambes dans le même quart
        H4 (15%) — Spread spatial    : les postes couvrent bien la bbox

        Returns:
            float in [0.0, 1.0]. Fallback 0.5 (neutre) si < 4 contrôles.
        """
        if len(controls) < 4:
            return 0.5

        n = len(controls)

        # ── H1 : Winding balance ──────────────────────────────────────────
        winding_sum = 0.0
        for i in range(1, n - 1):
            ax = controls[i][0] - controls[i - 1][0]
            ay = controls[i][1] - controls[i - 1][1]
            bx = controls[i + 1][0] - controls[i][0]
            by = controls[i + 1][1] - controls[i][1]
            winding_sum += math.atan2(ax * by - ay * bx, ax * bx + ay * by)
        winding_deg = abs(math.degrees(winding_sum))
        h1 = max(0.0, 1.0 - winding_deg / 270.0)  # 0° → 1.0 ; ≥270° → 0.0

        # ── H2 : Variance circulaire des azimuts ──────────────────────────
        sin_sum = cos_sum = 0.0
        n_legs = n - 1
        for i in range(n_legs):
            az = math.atan2(
                controls[i + 1][0] - controls[i][0],
                controls[i + 1][1] - controls[i][1],
            )
            sin_sum += math.sin(az)
            cos_sum += math.cos(az)
        circ_var = 1.0 - math.hypot(sin_sum / n_legs, cos_sum / n_legs)
        h2 = min(circ_var / 0.60, 1.0)  # cible : circ_var ≥ 0.60

        # ── H3 : Runs consécutifs dans le même quart ──────────────────────
        quads = [
            int((math.atan2(
                controls[i + 1][0] - controls[i][0],
                controls[i + 1][1] - controls[i][1],
            ) + math.pi) / (math.pi / 2)) % 4
            for i in range(n_legs)
        ]
        max_run = cur_run = 1
        for i in range(1, len(quads)):
            cur_run = cur_run + 1 if quads[i] == quads[i - 1] else 1
            if cur_run > max_run:
                max_run = cur_run
        h3 = max(0.0, 1.0 - max(0, max_run - 3) * 0.25)  # −0.25 par run > 3

        # ── H4 : Spread spatial ───────────────────────────────────────────
        inner = controls[1:-1]  # hors départ et arrivée
        if len(inner) >= 2:
            lngs = [p[0] for p in inner]
            lats = [p[1] for p in inner]
            bbox_w = max((bounding_box.get("max_x", 0) - bounding_box.get("min_x", 0)), 1e-9)
            bbox_h = max((bounding_box.get("max_y", 0) - bounding_box.get("min_y", 0)), 1e-9)
            import numpy as _np
            spread = (float(_np.std(lngs)) / bbox_w + float(_np.std(lats)) / bbox_h) / 2
            h4 = min(spread / 0.20, 1.0)  # cible : spread ≥ 20 % de la bbox
        else:
            h4 = 0.5

        # ── H5 : Pénalité accordéon (retours en arrière > 120°) ──────────────
        bearings_h5 = []
        for i in range(n - 1):
            bearings_h5.append(math.atan2(
                controls[i + 1][0] - controls[i][0],
                controls[i + 1][1] - controls[i][1],
            ))
        reversals = 0
        for i in range(1, len(bearings_h5)):
            delta_deg = abs(math.degrees(bearings_h5[i] - bearings_h5[i - 1]))
            delta_deg = min(delta_deg, 360 - delta_deg)
            if delta_deg > 120:
                reversals += 1
        reversal_ratio = reversals / max(len(bearings_h5) - 1, 1)
        h5 = max(0.0, 1.0 - reversal_ratio * 2.5)

        return 0.28 * h1 + 0.22 * h2 + 0.15 * h3 + 0.15 * h4 + 0.20 * h5

    def _terrain_quality_score_isom(self, controls: List[Tuple[float, float]]) -> float:
        """
        [Fallback] Critère terrain via ISOM attractiveness + ML OSM (sans HeatmapCache).
        Utilisé par evaluate_fitness() quand config.heatmap_cache is None.
        """
        return self._terrain_quality_score(controls)

    def _terrain_quality_score(self, controls: List[Tuple[float, float]]) -> float:
        """
        Critère terrain quality : blend ISOM attractiveness (rule-based) + ML visual scorer.

        Pour chaque poste intermédiaire (hors départ/arrivée) :
        - ISOM attractiveness : candidat le plus proche dans 60m → score 0–1
        - ML patch scorer : XGBoost sur vecteur couleur ISOM 7-dim (si modèle chargé)
        - Blend : 40% ISOM + 60% ML quand les deux sont disponibles, sinon ISOM seul
        - Intersection géométrique (_intersection=True) → attractiveness forcé à 1.0
        """
        if not self.config.candidate_points or len(controls) < 3:
            return 50.0  # Neutre si pas de candidats

        # Rayon de pénalité : poste trop loin d'une entité ISOM → score effondré
        # Sprint : 40m (carte 1:4000, précision fine)  Forêt : 80m (carte 1:10000)
        PENALTY_RADIUS_M = 40.0 if self.config.sprint_mode else 80.0
        ATT_RADIUS_M = 60.0
        ML_RADIUS_M = 64.0
        scores = []

        for pos in controls[1:-1]:  # Exclure départ et arrivée

            if self._ocad_tree is not None:
                # ── Chemin KDTree O(log N) — Phase 2 ───────────────────────
                _near_cp, _near_d = self._nearest_ocad(pos[0], pos[1])

                if _near_d > PENALTY_RADIUS_M:
                    # Poste dans le vide cartographique : pénalité × 0.10
                    ml_raw = self._patch_scorer.score_position(
                        pos[0], pos[1], self.config.candidate_points, ML_RADIUS_M
                    ) if self._patch_scorer else None
                    scores.append(0.10 * (ml_raw if ml_raw is not None else 0.30))
                    continue

                # Feature dans le rayon : attractivité depuis le dict frontend
                # ou depuis _isom_att_scores (control_descriptions.json)
                if _near_cp.get("_intersection"):
                    att = 1.0
                else:
                    isom = _near_cp.get("isom")
                    att = _near_cp.get(
                        "attractiveness",
                        self._isom_att_scores.get(isom, 0.45) if isom else 0.45,
                    )
            else:
                # ── Fallback O(N) — pas d'OCAD chargé (OSM-only, rétrocompat) ─
                best_att = None
                best_d = ATT_RADIUS_M
                for cp in self.config.candidate_points:
                    d = self._haversine_m(pos, (cp["x"], cp["y"]))
                    if d < best_d:
                        best_d = d
                        if cp.get("_intersection"):
                            best_att = 1.0
                        else:
                            isom = cp.get("isom")
                            best_att = self._isom_att_scores.get(isom, 0.45) if isom else 0.45
                att = best_att if best_att is not None else 0.15

            # --- Score ML visuel (data-driven, blend quand disponible) ---
            if self._patch_scorer is not None:
                ml = self._patch_scorer.score_position(
                    pos[0], pos[1], self.config.candidate_points, ML_RADIUS_M
                )
                if ml is not None:
                    scores.append(att * 0.4 + ml * 0.6)
                    continue

            scores.append(att)

        if not scores:
            return 50.0
        return (sum(scores) / len(scores)) * 100.0

    def _monotony_score(self, controls: List[Tuple[float, float]]) -> float:
        """
        Pénalise la monotonie directionnelle : séquences de jambes consécutives
        dans la même direction (±60°). Un circuit varié explore toutes les directions.
        Score 100 si max_run ≤ 2 jambes, décroît ensuite (40→ pour 4+).
        """
        if len(controls) < 4:
            return 75.0
        bearings = []
        for i in range(len(controls) - 1):
            dx = controls[i + 1][0] - controls[i][0]
            dy = controls[i + 1][1] - controls[i][1]
            bearings.append(math.degrees(math.atan2(dx, dy)) % 360)
        max_run = 1
        current_run = 1
        for i in range(1, len(bearings)):
            diff = abs(bearings[i] - bearings[i - 1]) % 360
            if diff > 180:
                diff = 360 - diff
            if diff < 60:
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 1
        if max_run <= 2:
            return 100.0
        elif max_run == 3:
            return 70.0
        elif max_run == 4:
            return 40.0
        else:
            return max(0.0, 40.0 - (max_run - 4) * 15.0)

    def _leg_alternation_score(self, controls: List[Tuple[float, float]]) -> float:
        """
        Récompense l'alternance court/long entre jambes consécutives.
        Classe chaque jambe en C(<80% moy), L(>120% moy) ou M.
        Score = % d'alternances C↔L parmi les jambes C/L (0-100).
        Évite les circuits monotones type CCCCLLL ou toutes jambes identiques.
        """
        if len(controls) < 4:
            return 75.0
        legs = [self._haversine_m(controls[i], controls[i + 1]) for i in range(len(controls) - 1)]
        mean_leg = sum(legs) / len(legs) if legs else 0.0
        if mean_leg == 0.0:
            return 75.0
        types = [
            'C' if l < mean_leg * 0.80 else ('L' if l > mean_leg * 1.20 else 'M')
            for l in legs
        ]
        cl_types = [t for t in types if t != 'M']
        if len(cl_types) < 2:
            return 75.0
        alternations = sum(1 for i in range(len(cl_types) - 1) if cl_types[i] != cl_types[i + 1])
        return (alternations / (len(cl_types) - 1)) * 100.0

    def _default_scoring(
        self,
        circuit: Circuit,
        config: GenerationConfig,
    ) -> float:
        """
        Fitness multi-objectifs IOF (9 critères pondérés).
        Critères 8-9 : anti-monotonie directionnelle + alternance court/long.
        """
        controls = circuit.controls
        if len(controls) < 2:
            return 0.0

        # ── OOB : pénalité éliminatoire ────────────────────────────────────
        _forbidden = getattr(self, "_current_forbidden_zones", [])
        if _forbidden:
            for _ctrl in controls:
                if self._is_in_forbidden_zone(_ctrl[0], _ctrl[1], _forbidden):
                    return -10000.0
        # ── HeatmapCache : éliminer les postes en zones non-attractives ───
        # Score ≤ 0.01 = forêt lente (vert olive), eau, zone privée → interdit
        # O(1) par poste via lookup grille (remplace vérification polygonale lente)
        if config.heatmap_cache is not None:
            for _ctrl in controls[1:-1]:  # hors départ et arrivée
                if (config.heatmap_cache.query(_ctrl[0], _ctrl[1]) <= 0.01
                        or config.heatmap_cache.is_forbidden(_ctrl[0], _ctrl[1])):
                    return -10000.0
        # ──────────────────────────────────────────────────────────────────

        total_length = self._calculate_total_length(controls)
        leg_lengths = [
            self._haversine_m(controls[i], controls[i+1])
            for i in range(len(controls) - 1)
        ]

        # --- 1. Longueur (20%) : gradient continu — pas de clamping à 0 ---
        # Sans clamping, le GA peut distinguer 10km vs 17km (les deux mauvais).
        # 100 si ratio ±15%, décroît linéairement → peut être négatif pour très mauvais circuits.
        if config.target_length_m > 0 and total_length > 0:
            ratio = total_length / config.target_length_m
            if 0.85 <= ratio <= 1.15:
                length_score = 100.0
            else:
                deviation = abs(ratio - 1.0) - 0.15
                length_score = 100.0 - deviation * 200  # Peut être négatif → gradient préservé
        else:
            length_score = 75.0

        # --- 2. Dénivelé (15%) : D+ ≤ 4% de la distance (IOF AA8.3) ---
        climb = config.target_climb_m
        if total_length > 0 and climb > 0:
            climb_ratio = climb / total_length
            if climb_ratio <= 0.04:
                climb_score = 100.0
            elif climb_ratio <= 0.06:
                climb_score = 60.0 - (climb_ratio - 0.04) * 1500
            else:
                climb_score = max(0.0, 30.0 - (climb_ratio - 0.06) * 1000)
        else:
            climb_score = 75.0

        # --- 3. Cohérence TD (15%) : CV des jambes entre 20% et 50% ---
        if leg_lengths:
            mean_leg = sum(leg_lengths) / len(leg_lengths)
            if mean_leg > 0:
                cv = (sum((l - mean_leg)**2 for l in leg_lengths) / len(leg_lengths))**0.5 / mean_leg
                if 0.20 <= cv <= 0.50:
                    td_score = 100.0
                elif cv < 0.20:
                    td_score = 40.0 + cv * 300  # trop régulier
                else:
                    td_score = max(0.0, 100.0 - (cv - 0.50) * 150)
            else:
                td_score = 50.0
        else:
            td_score = 50.0

        # --- 4. Variété des angles (20%) : angles 30-150° entre jambes (IOF AA3.4.1) ---
        if len(controls) >= 3:
            good_angles = 0
            total_angles = len(controls) - 2
            for i in range(1, len(controls) - 1):
                prev, curr, nxt = controls[i-1], controls[i], controls[i+1]
                in_a = math.atan2(curr[1]-prev[1], curr[0]-prev[0])
                out_a = math.atan2(nxt[1]-curr[1], nxt[0]-curr[0])
                diff = abs(math.degrees(out_a - in_a)) % 360
                if diff > 180:
                    diff = 360 - diff
                if 30 <= diff <= 150:
                    good_angles += 1
            angle_score = 100.0 * good_angles / total_angles if total_angles > 0 else 50.0
        else:
            angle_score = 50.0

        # --- 5. Équité (20%) : pas de dog-legs, séparation minimale (seuils IOF/FFCO dynamiques) ---
        _rules = self._placement_rules
        _dogleg_threshold = _rules.get("dog_leg_angle_deg", 25)
        _min_sep = _rules.get("min_control_separation_m", config.min_control_distance)
        dog_legs = 0
        too_close = 0
        if len(controls) >= 3:
            for i in range(1, len(controls) - 1):
                prev, curr, nxt = controls[i-1], controls[i], controls[i+1]
                in_a = math.atan2(curr[1]-prev[1], curr[0]-prev[0])
                out_a = math.atan2(nxt[1]-curr[1], nxt[0]-curr[0])
                diff = abs(math.degrees(out_a - in_a)) % 360
                if diff > 180:
                    diff = 360 - diff
                if diff < _dogleg_threshold:
                    dog_legs += 1
        for i in range(len(controls)):
            for j in range(i + 1, len(controls)):
                d = self._haversine_m(controls[i], controls[j])
                if d < _min_sep:
                    too_close += 1
        equity_score = max(0.0, 100.0 - dog_legs * 15 - too_close * 20)

        # --- 6. Sécurité (10%) : pénalité si nb postes incorrect ---
        control_diff = abs(len(controls) - config.target_controls)
        safety_score = max(0.0, 100.0 - control_diff * 10)

        # --- 7. Terrain quality (10%) : V2 visual (HeatmapCache) ou fallback ISOM ---
        # Quand heatmap_cache disponible : score moyen V2 sur les postes intermédiaires.
        # Sinon : comportement ISOM attractiveness identique à avant (aucune régression).
        if config.heatmap_cache is not None:
            pts_mid = controls[1:-1] if len(controls) > 2 else controls
            terrain_score = float(np.mean([
                config.heatmap_cache.query(lng, lat) for lng, lat in pts_mid
            ])) * 100.0
        else:
            terrain_score = self._terrain_quality_score(controls)

        # --- 8. Anti-monotonie directionnelle ---
        monotony_score = self._monotony_score(controls)

        # --- 9. Alternance court/long ---
        alternation_score = self._leg_alternation_score(controls)

        # --- 10. Sprint : pénaliser les jambes > max_leg_m (seuil dynamique) ---
        if config.sprint_mode and leg_lengths:
            max_leg_m = float(_rules.get("max_leg_m", 200))
            long_legs = sum(1 for l in leg_lengths if l > max_leg_m)
            sprint_leg_score = max(0.0, 100.0 - long_legs * 25)

            # Bonus cluster de désorientation
            cluster_bonus = 0.0
            cluster_radius = float(_rules.get("disorientation_cluster_radius_m", 0))
            cluster_target_size = int(_rules.get("disorientation_cluster_size", 0))
            cluster_target_count = int(_rules.get("disorientation_cluster_count", 0))
            if cluster_radius > 0 and cluster_target_size >= 3:
                n = len(controls)
                found_clusters = 0
                counted_in_cluster = set()
                for i in range(n):
                    if i in counted_in_cluster:
                        continue
                    nearby = [i]
                    for j in range(n):
                        if j != i and j not in counted_in_cluster:
                            if self._haversine_m(controls[i], controls[j]) <= cluster_radius:
                                nearby.append(j)
                    if len(nearby) >= cluster_target_size:
                        found_clusters += 1
                        counted_in_cluster.update(nearby[:cluster_target_size])
                if cluster_target_count > 0:
                    cluster_bonus = min(100.0, (found_clusters / cluster_target_count) * 100.0)

            # Pondération sprint : dénivelé remplacé par jambe_sprint + terrain_quality + cluster
            cluster_weight = 0.08 if cluster_radius > 0 else 0.0
            base_weight_adj = 1.0 - cluster_weight
            _w = self._ga_weights
            if _w is not None:
                return (
                    (length_score       * _w.w_length
                    + sprint_leg_score  * _w.w_sprint_leg
                    + td_score          * _w.w_td
                    + angle_score       * _w.w_angle
                    + equity_score      * _w.w_equity
                    + safety_score      * _w.w_safety
                    + terrain_score     * _w.w_terrain
                    + monotony_score    * _w.w_monotony
                    + alternation_score * _w.w_alternation) * base_weight_adj
                    + cluster_bonus * cluster_weight
                )
            return (
                (length_score       * 0.22
                + sprint_leg_score  * 0.15
                + td_score          * 0.11
                + angle_score       * 0.17
                + equity_score      * 0.07
                + safety_score      * 0.05
                + terrain_score     * 0.10
                + monotony_score    * 0.07
                + alternation_score * 0.06) * base_weight_adj
                + cluster_bonus * cluster_weight
            )

        _w = self._ga_weights
        if _w is not None:
            return (
                length_score       * _w.w_length
                + climb_score      * _w.w_climb
                + td_score         * _w.w_td
                + angle_score      * _w.w_angle
                + equity_score     * _w.w_equity
                + safety_score     * _w.w_safety
                + terrain_score    * _w.w_terrain
                + monotony_score   * _w.w_monotony
                + alternation_score * _w.w_alternation
            )
        return (
            length_score       * 0.18
            + climb_score      * 0.10
            + td_score         * 0.11
            + angle_score      * 0.15
            + equity_score     * 0.13
            + safety_score     * 0.08
            + terrain_score    * 0.10
            + monotony_score   * 0.08
            + alternation_score * 0.07
        )

    def _calculate_total_length(self, controls: List[Tuple[float, float]]) -> float:
        """Calcule la longueur totale en mètres (haversine WGS84)."""
        total = 0.0
        for i in range(len(controls) - 1):
            total += self._haversine_m(controls[i], controls[i + 1])
        return total

    def _get_min_control_distance(self, controls: List[Tuple[float, float]]) -> float:
        """Calcule la distance minimale entre postes en mètres."""
        min_dist = float("inf")

        for i in range(len(controls)):
            for j in range(i + 1, len(controls)):
                dist = self._haversine_m(controls[i], controls[j])
                if dist < min_dist:
                    min_dist = dist

        return min_dist if min_dist != float("inf") else 0

    def _calculate_variety(self, controls: List[Tuple[float, float]]) -> float:
        """Calcule un score de variété (0-1)."""
        if len(controls) < 3:
            return 0

        # Calculer les angles entre interpostes
        angles = []
        for i in range(len(controls) - 2):
            v1 = (
                controls[i + 1][0] - controls[i][0],
                controls[i + 1][1] - controls[i][1],
            )
            v2 = (
                controls[i + 2][0] - controls[i + 1][0],
                controls[i + 2][1] - controls[i + 1][1],
            )

            angle = math.atan2(v2[1], v2[0]) - math.atan2(v1[1], v1[0])
            angles.append(abs(angle))

        # Variance des angles (plus c'est varié, mieux c'est)
        if not angles:
            return 0

        mean = sum(angles) / len(angles)
        variance = sum((a - mean) ** 2 for a in angles) / len(angles)

        return min(1.0, variance / 2)  # Normaliser

    def _check_early_stop(self) -> bool:
        """Arrêt si le meilleur fitness n'a pas progressé depuis 20 générations.
        Exception : ne pas stopper si la distance est < 85% de la cible (GA pas convergé)."""
        current_best = self.population[0].fitness if self.population else 0.0

        # Ne pas stopper si le circuit est encore trop court
        if (self.best_solution is not None
                and self.config.target_length_m > 0
                and len(self.best_solution.controls) >= 2):
            actual = self._calculate_total_length(self.best_solution.controls)
            if actual < self.config.target_length_m * 0.85:
                # Réinitialiser la stagnation — forcer la continuation
                self._stagnation_count = 0
                self._last_best_fitness = current_best
                return False

        if abs(current_best - self._last_best_fitness) < 0.01:
            self._stagnation_count += 1
        else:
            self._stagnation_count = 0
            self._last_best_fitness = current_best
        return self._stagnation_count >= 20
