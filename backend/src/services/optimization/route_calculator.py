# =============================================
# Calcul de routes réalistes entre postes
# Sprint 5: Optimisation des positions de postes
# =============================================

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime


# =============================================
# Fonction de Tobler (coût terrain réaliste)
# =============================================

# Multiplicateurs de vitesse OCAD/ISOM 2017 (relatif à terrain plat idéal = 1.0)
# Basés sur passability de ocad_semantics.json + pratique CO
OCAD_TERRAIN_MULTIPLIERS = {
    "open":           1.00,   # Terrain ouvert (vert clair ISOM 401)
    "rough_open":     0.85,   # Terrain ouvert accidenté
    "road":           1.10,   # Route/chemin asphalté
    "path":           0.95,   # Sentier large (légère perte vs route)
    "narrow_path":    0.90,   # Sentier étroit
    "light_forest":   0.80,   # Forêt coureable
    "forest":         0.70,   # Forêt normale
    "dense_forest":   0.50,   # Forêt dense (vert ISOM)
    "slow_forest":    0.45,   # Végétation lente (vert foncé)
    "impassable":     0.00,   # Forêt impraticable (ISOM 311) — contournement
    "swamp":          0.35,   # Marécage franchissable
    "wet":            0.55,   # Terrain humide
    "fight":          0.30,   # Taillis dense
}


def tobler_speed_multiplier(slope: float) -> float:
    """
    Multiplicateur de vitesse Tobler en fonction de la pente.
    slope = dénivelé / distance horizontale (positif = montée)

    Formule : V_rel = exp(-3.5 × |slope + 0.05|) / exp(-3.5 × 0.05)
    Normalisée à 1.0 sur terrain plat (slope=0).
    Optimum à slope ≈ -5% (légère descente).

    Returns:
        float : multiplicateur (1.0 = plat, >1 = descente douce, <1 = montée)
    """
    # Tobler normalisé sur plat
    v_flat = math.exp(-3.5 * abs(0.05))
    v_slope = math.exp(-3.5 * abs(slope + 0.05))
    return v_slope / v_flat


def leg_time_minutes(
    dist_m: float,
    elev_gain_m: float = 0.0,
    terrain_type: str = "forest",
    base_speed_m_per_min: float = 170.0,
) -> float:
    """
    Estime le temps de parcours d'une jambe (en minutes) avec Tobler.

    Args:
        dist_m: Distance horizontale en mètres
        elev_gain_m: Dénivelé positif (montée) en mètres
        terrain_type: Clé de OCAD_TERRAIN_MULTIPLIERS
        base_speed_m_per_min: Vitesse de référence sur terrain plat idéal (m/min)
            Valeur typique compétition M21E ≈ 200, M45 ≈ 150, Vert ≈ 100

    Returns:
        float : durée estimée en minutes (inf si terrain impassable)
    """
    if dist_m <= 0:
        return 0.0

    terrain_mult = OCAD_TERRAIN_MULTIPLIERS.get(terrain_type, 0.70)
    if terrain_mult == 0.0:
        return float("inf")  # Impassable : contournement nécessaire

    # Pente
    slope = elev_gain_m / dist_m if dist_m > 0 else 0.0
    tobler_mult = tobler_speed_multiplier(slope)

    effective_speed = base_speed_m_per_min * terrain_mult * tobler_mult
    return dist_m / effective_speed if effective_speed > 0 else float("inf")


# =============================================
# Types de données
# =============================================
@dataclass
class Waypoint:
    """Un point sur le parcours."""

    x: float
    y: float
    cumulative_distance: float = 0.0
    cumulative_time: float = 0.0


@dataclass
class Route:
    """Une route calculée entre deux postes."""

    start_control: int
    end_control: int
    waypoints: List[Waypoint] = field(default_factory=list)
    total_distance: float = 0.0
    total_time: float = 0.0
    elevation_gain: float = 0.0
    elevation_loss: float = 0.0
    route_type: str = "direct"  # direct, path, optimal


@dataclass
class RouteAnalysis:
    """Analyse complète d'un interposte."""

    from_control: int
    to_control: int
    direct_distance: float = 0.0
    route_distance: float = 0.0
    route_time: float = 0.0
    route: Optional[Route] = None
    route_quality: str = "good"  # excellent, good, fair, poor
    choices_available: int = 0
    navigation_difficulty: str = "easy"  # easy, medium, hard


# =============================================
# Calculateur de routes
# =============================================
class RouteCalculator:
    """
    Calcule des itinéraires réalistes entre les postes d'un circuit.

    Utilise les données de runnability pour estimer le temps de parcours
    et proposer des itinéraires réalistes plutôt que des lignes droites.
    """

    # Vitesses de base en mètres/minute (terrain plat)
    BASE_SPEEDS = {
        "road": 300,  # Route asphaltée
        "path": 200,  # Sentier large
        "narrow_path": 150,  # Sentier étroit
        "flat_grass": 180,  # Terrain plat herbage
        "light_forest": 140,  # Forêt légère
        "dense_forest": 80,  # Forêt dense
        "rough_terrain": 60,  # Terrain difficile
        "swamp": 40,  # Marécage
    }

    # Pénalités de dénivelé (multiplicateur)
    UPHILL_PENALTY = 1.5  # 50% plus lent en montée
    DOWNHILL_PENALTY = 1.2  # 20% plus lent en descente

    def __init__(self):
        """Initialise le calculateur."""
        self.runnability_map = None
        self.osm_data = None

    def load_runnability(self, runnability_map):
        """Charge la carte de runnability."""
        self.runnability_map = runnability_map

    def load_osm_data(self, osm_data):
        """Charge les données OSM pour les chemins."""
        self.osm_data = osm_data

    def calculate_route(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        waypoints: List[Tuple[float, float]] = None,
    ) -> Route:
        """
        Calcule une route entre deux points.

        Args:
            start: (x, y) point de départ
            end: (x, y) point d'arrivée
            waypoints: Points de passage obligatoires (chemins)

        Returns:
            Route avec waypoints et temps
        """
        route = Route(
            start_control=0,
            end_control=0,
            route_type="direct",
        )

        # Ajouter le point de départ
        route.waypoints.append(Waypoint(x=start[0], y=start[1]))

        # Si on a des waypoints (chemins), les utiliser
        if waypoints:
            route.route_type = "path"
            for wp in waypoints:
                route.waypoints.append(Waypoint(x=wp[0], y=wp[1]))
        else:
            # Route directe (ligne droite)
            route.route_type = "direct"

        # Ajouter le point d'arrivée
        route.waypoints.append(Waypoint(x=end[0], y=end[1]))

        # Calculer les distances et temps
        self._calculate_route_metrics(route)

        return route

    def calculate_interpost_route(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        terrain_type: str = "flat_grass",
        has_path: bool = False,
    ) -> Route:
        """
        Calcule une route pour un interposte avec estimation réaliste.

        Args:
            start: (x, y) point de départ
            end: (x, y) point d'arrivée
            terrain_type: Type de terrain (pour vitesse de base)
            has_path: Y a-t-il un chemin praticable ?

        Returns:
            Route avec estimations de temps
        """
        route = Route(
            start_control=0,
            end_control=0,
            route_type="optimal",
        )

        # Point de départ
        current_pos = start
        route.waypoints.append(
            Waypoint(x=start[0], y=start[1], cumulative_distance=0, cumulative_time=0)
        )

        # Si on a un chemin, créer des waypoints le long du chemin
        if has_path:
            # Créer des points intermédiaires le long d'un chemin imaginaire
            # Dans la réalité, on utiliserait les données OSM
            num_intermediate = max(2, int(self._calculate_distance(start, end) / 100))
            for i in range(1, num_intermediate):
                t = i / num_intermediate
                intermediate = (
                    start[0] + (end[0] - start[0]) * t,
                    start[1] + (end[1] - start[1]) * t,
                )
                route.waypoints.append(Waypoint(x=intermediate[0], y=intermediate[1]))
                current_pos = intermediate
        else:
            # Pas de chemin - on traverse le terrain directement
            route.waypoints.append(Waypoint(x=end[0], y=end[1]))
            current_pos = end

        # Calculer les métriques
        self._calculate_route_metrics(route, terrain_type)

        return route

    def analyze_interpost(
        self,
        from_control: Dict,
        to_control: Dict,
        terrain_data: Dict = None,
    ) -> RouteAnalysis:
        """
        Analyse un interposte et évalue sa qualité.

        Args:
            from_control: Poste de départ {x, y, type, ...}
            to_control: Poste d'arrivée {x, y, type, ...}
            terrain_data: Données de terrain (optionnel)

        Returns:
            Analyse de l'interposte
        """
        start = (from_control.get("x", 0), from_control.get("y", 0))
        end = (to_control.get("x", 0), to_control.get("y", 0))

        analysis = RouteAnalysis(
            from_control=from_control.get("order", 0),
            to_control=to_control.get("order", 0),
        )

        # Distance directe
        analysis.direct_distance = self._calculate_distance(start, end)

        # Calculer la route
        terrain_type = (
            terrain_data.get("terrain_type", "flat_grass")
            if terrain_data
            else "flat_grass"
        )
        has_path = terrain_data.get("has_path", False) if terrain_data else False

        route = self.calculate_interpost_route(start, end, terrain_type, has_path)
        analysis.route = route
        analysis.route_distance = route.total_distance
        analysis.route_time = route.total_time

        # Évaluer la qualité de l'interposte
        analysis.route_quality = self._evaluate_interpost_quality(
            analysis.direct_distance,
            analysis.route_distance,
            analysis.route_time,
            has_path,
        )

        # Nombre de choix disponibles (simplifié)
        analysis.choices_available = self._estimate_choices(
            analysis.direct_distance, has_path, terrain_type
        )

        # Difficulté de navigation
        analysis.navigation_difficulty = self._estimate_navigation_difficulty(
            analysis.route_quality, analysis.choices_available
        )

        return analysis

    def _calculate_route_metrics(
        self, route: Route, terrain_type: str = "flat_grass"
    ) -> None:
        """Calcule les distances et temps pour une route."""
        base_speed = self.BASE_SPEEDS.get(terrain_type, 150)

        total_dist = 0.0
        total_time = 0.0
        prev_point = None

        for waypoint in route.waypoints:
            if prev_point:
                dist = self._calculate_distance(
                    (prev_point.x, prev_point.y), (waypoint.x, waypoint.y)
                )
                total_dist += dist

                # Estimer le temps (simplifié - sans dénivelé)
                time = dist / base_speed
                total_time += time

                waypoint.cumulative_distance = total_dist
                waypoint.cumulative_time = total_time

            prev_point = waypoint

        route.total_distance = total_dist
        route.total_time = total_time

    def _evaluate_interpost_quality(
        self,
        direct_distance: float,
        route_distance: float,
        route_time: float,
        has_path: bool,
    ) -> str:
        """Évalue la qualité d'un interposte."""
        if direct_distance == 0:
            return "poor"

        # Ratio entre distance réelle et distance directe
        ratio = route_distance / direct_distance

        if ratio < 1.1 and has_path:
            return "excellent"  # Court et sur chemin
        elif ratio < 1.3:
            return "good"  # Assez direct
        elif ratio < 1.5:
            return "fair"  # Long mais OK
        else:
            return "poor"  # Très long - peut-être à optimiser

    def _estimate_choices(
        self, distance: float, has_path: bool, terrain_type: str
    ) -> int:
        """Estime le nombre de choix d'itinéraires."""
        choices = 1  # Toujours au moins un choix (le direct)

        if distance > 200:
            choices += 1  # Assez long pour avoir des alternatives

        if has_path:
            choices += 1  # Chemin = choix supplémentaire

        if terrain_type in ["light_forest", "flat_grass"]:
            choices += 1  # Terrain praticable = plus de liberté

        return min(choices, 4)  # Maximum 4 choix

    def _estimate_navigation_difficulty(self, quality: str, choices: int) -> str:
        """Estime la difficulté de navigation."""
        if quality == "excellent" and choices <= 2:
            return "easy"
        elif quality == "good" and choices <= 3:
            return "medium"
        else:
            return "hard"

    def _calculate_distance(
        self, p1: Tuple[float, float], p2: Tuple[float, float]
    ) -> float:
        """Calcule la distance entre deux points."""
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)

    def calculate_leg_time(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        elev_gain_m: float = 0.0,
        terrain_type: str = "forest",
        base_speed_m_per_min: float = 170.0,
    ) -> float:
        """
        Calcule le temps de parcours d'une jambe avec la fonction de Tobler.

        Args:
            start, end: coordonnées (x, y) en mètres
            elev_gain_m: dénivelé positif sur la jambe
            terrain_type: type de terrain OCAD (clé OCAD_TERRAIN_MULTIPLIERS)
            base_speed_m_per_min: vitesse de référence coureur

        Returns:
            float : temps en minutes (inf si impassable)
        """
        dist = self._calculate_distance(start, end)
        return leg_time_minutes(dist, elev_gain_m, terrain_type, base_speed_m_per_min)


# =============================================
# Optimiseur de positions de postes
# =============================================
class PositionOptimizer:
    """
    Optimise les positions des postes pour améliorer la qualité du circuit.

    Pour chaque interposte, cherche une position optimale dans un rayon donné.
    """

    SEARCH_RADIUS = 50  # Rayon de recherche en mètres

    def __init__(self):
        """Initialise l'optimiseur."""
        self.route_calculator = RouteCalculator()

    def optimize_control_position(
        self,
        current_pos: Tuple[float, float],
        previous_pos: Tuple[float, float],
        next_pos: Tuple[float, float],
        terrain_data: Dict = None,
    ) -> Tuple[Tuple[float, float], float]:
        """
        Optimise la position d'un poste.

        Args:
            current_pos: Position actuelle du poste
            previous_pos: Position du poste précédent
            next_pos: Position du poste suivant
            terrain_data: Données de terrain

        Returns:
            (nouvelle_position, improvement_score)
        """
        best_pos = current_pos
        best_score = self._score_position(
            current_pos, previous_pos, next_pos, terrain_data
        )

        # Tester des positions autour
        angles = [0, 45, 90, 135, 180, 225, 270, 315]
        distances = [10, 20, 30, 40, 50]

        for angle in angles:
            for dist in distances:
                # Nouvelle position
                rad = math.radians(angle)
                new_pos = (
                    current_pos[0] + dist * math.cos(rad),
                    current_pos[1] + dist * math.sin(rad),
                )

                # Évaluer
                score = self._score_position(
                    new_pos, previous_pos, next_pos, terrain_data
                )

                if score > best_score:
                    best_score = score
                    best_pos = new_pos

        return best_pos, best_score

    def _score_position(
        self,
        pos: Tuple[float, float],
        prev: Tuple[float, float],
        next_pos: Tuple[float, float],
        terrain_data: Dict,
    ) -> float:
        """
        Score une position de poste.

        Plus le score est haut, mieux c'est.
        """
        score = 100.0

        # Distance au poste précédent (éviter trop proche)
        dist_prev = self._calculate_distance(prev, pos)
        if dist_prev < 60:
            score -= (60 - dist_prev) * 2

        # Distance au poste suivant
        dist_next = self._calculate_distance(pos, next_pos)
        if dist_next < 60:
            score -= (60 - dist_next) * 2

        # Évitement des lignes droites parfaites (interpostes linéaires)
        # Si les deux interpostes sont alignés -> score réduit
        angle1 = math.atan2(pos[1] - prev[1], pos[0] - prev[0])
        angle2 = math.atan2(next_pos[1] - pos[1], next_pos[0] - pos[0])
        angle_diff = abs(angle1 - angle2)
        if angle_diff < 0.2 or abs(angle_diff - math.pi) < 0.2:
            score -= 20  # Pénalité pour alignement

        return score

    def _calculate_distance(
        self, p1: Tuple[float, float], p2: Tuple[float, float]
    ) -> float:
        """Calcule la distance entre deux points."""
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)


# =============================================
# Fonctions utilitaires
# =============================================
def estimate_circuit_time(
    controls: List[Dict],
    terrain_type: str = "forest",
    has_paths: bool = True,
    base_speed_m_per_min: float = 170.0,
    elevation_per_leg: List[float] = None,
) -> Dict:
    """
    Estime le temps total d'un circuit avec la fonction de Tobler.

    Args:
        controls: Liste des postes dans l'ordre [{x, y, order, ...}]
        terrain_type: Type de terrain dominant (clé OCAD_TERRAIN_MULTIPLIERS)
        has_paths: Y a-t-il des chemins (ajuste le terrain_type si True)
        base_speed_m_per_min: Vitesse coureur de référence sur plat idéal
        elevation_per_leg: Dénivelé (m) pour chaque jambe (optionnel)

    Returns:
        {
            "total_distance": float,
            "total_time_minutes": float,
            "time_per_interpost": [...],
            "estimated_winning_time_minutes": float,
        }
    """
    calculator = RouteCalculator()

    # Si chemin disponible, utiliser type "path" plus rapide
    effective_terrain = "path" if has_paths else terrain_type

    total_distance = 0.0
    total_time = 0.0
    time_per_interpost = []

    for i in range(len(controls) - 1):
        start = (controls[i].get("x", 0), controls[i].get("y", 0))
        end = (controls[i + 1].get("x", 0), controls[i + 1].get("y", 0))
        elev = elevation_per_leg[i] if elevation_per_leg and i < len(elevation_per_leg) else 0.0

        dist = calculator._calculate_distance(start, end)
        t = calculator.calculate_leg_time(
            start, end,
            elev_gain_m=elev,
            terrain_type=effective_terrain,
            base_speed_m_per_min=base_speed_m_per_min,
        )

        total_distance += dist
        total_time += t if t != float("inf") else 0.0
        time_per_interpost.append(
            {
                "from": controls[i].get("order"),
                "to": controls[i + 1].get("order"),
                "distance": round(dist, 1),
                "time_minutes": round(t, 2) if t != float("inf") else None,
                "elev_gain_m": elev,
            }
        )

    return {
        "total_distance": round(total_distance, 1),
        "total_time_minutes": round(total_time, 2),
        "time_per_interpost": time_per_interpost,
        "estimated_winning_time_minutes": round(total_time * 0.8, 2),
    }
