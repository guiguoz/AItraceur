# =============================================
# Détection de problèmes sur les circuits CO
# Sprint 4: Détection de problèmes (Forêt)
# =============================================

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime


# =============================================
# Types de problèmes détectés
# =============================================
PROBLEM_TYPES = {
    # === Problèmes de sécurité ===
    "road_crossing": {
        "severity": "high",
        "description": "Traversée de route dangereuse",
        "category": "safety",
    },
    "private_area": {
        "severity": "high",
        "description": "Poste en zone privée",
        "category": "safety",
    },
    "dangerous_terrain": {
        "severity": "high",
        "description": "Terrain dangereux à proximité",
        "category": "safety",
    },
    # === Problèmes techniques ===
    "controls_too_close": {
        "severity": "medium",
        "description": "Postes trop proches l'un de l'autre",
        "category": "technical",
    },
    "linear_interpost": {
        "severity": "low",
        "description": "Interposte trop linéaire (sans choix)",
        "category": "technical",
    },
    "no_route_choice": {
        "severity": "low",
        "description": "Pas de choix d'itinéraire évident",
        "category": "technical",
    },
    "technical_imbalance": {
        "severity": "medium",
        "description": "Déséquilibre technique du circuit",
        "category": "technical",
    },
    # === Problèmes de visibilité ===
    "visibility_spoil": {
        "severity": "medium",
        "description": "Poste visible depuis un autre (spoil)",
        "category": "visibility",
    },
    # === Problèmes de données ===
    "unmapped_path": {
        "severity": "low",
        "description": "Chemin non cartographié détecté",
        "category": "data",
    },
    "circuit_crossing": {
        "severity": "medium",
        "description": "Croisement de circuits",
        "category": "data",
    },
}


# =============================================
# Structure de données
# =============================================
@dataclass
class Problem:
    """Un problème détecté sur un circuit."""

    type: str
    severity: str  # low, medium, high
    category: str  # safety, technical, visibility, data
    description: str
    location: Tuple[float, float]  # (x, y)
    control_id: Optional[int] = None
    interpost_id: Optional[Tuple[int, int]] = None  # (from_id, to_id)
    details: Dict = field(default_factory=dict)
    suggested_fix: Optional[str] = None


@dataclass
class AnalysisResult:
    """Résultat de l'analyse d'un circuit."""

    circuit_id: int
    analyzed_at: datetime = field(default_factory=datetime.utcnow)
    problems: List[Problem] = field(default_factory=list)
    score: float = 100.0  # Score sur 100
    status: str = "pending"  # pending, analyzed, error

    @property
    def has_critical_issues(self) -> bool:
        """Retourne True s'il y a des problèmes critiques."""
        return any(p.severity == "high" for p in self.problems)

    @property
    def problem_count(self) -> Dict[str, int]:
        """Compte les problèmes par catégorie."""
        counts = {"high": 0, "medium": 0, "low": 0}
        for p in self.problems:
            counts[p.severity] = counts.get(p.severity, 0) + 1
        return counts


# =============================================
# Détecteur de problèmes
# =============================================
class ProblemDetector:
    """
    Détecte les problèmes sur un circuit de CO.

    Utilise les données OCAD, OSM et LIDAR pour détecter
    différents types de problèmes.
    """

    # Distances minimales (en mètres)
    MIN_CONTROL_DISTANCE = 60  # Distance minimale entre 2 postes
    MIN_ROAD_CROSSING_DISTANCE = 20  # Distance minimale d'une route

    # Pour les spoilers (visibilité)
    SPOIL_DISTANCE = 150  # Distance à laquelle un poste peut être visible

    def __init__(self):
        """Initialise le détecteur."""
        self.osm_data = None
        self.lidar_data = None
        self.results: List[AnalysisResult] = []

    def load_osm_data(self, osm_data):
        """Charge les données OSM pour l'analyse."""
        self.osm_data = osm_data

    def load_lidar_data(self, lidar_data):
        """Charge les données LIDAR pour l'analyse."""
        self.lidar_data = lidar_data

    def analyze_circuit(
        self, circuit_id: int, controls: List[Dict], bounds: Dict = None
    ) -> AnalysisResult:
        """
        Analyse un circuit et détecte les problèmes.

        Args:
            circuit_id: ID du circuit
            controls: Liste des postes {id, x, y, type, ...}
            bounds: Bornes du circuit (optionnel)

        Returns:
            AnalysisResult avec les problèmes détectés
        """
        result = AnalysisResult(circuit_id=circuit_id, status="analyzed")

        if not controls or len(controls) < 2:
            result.status = "error"
            return result

        # Trier les contrôles par ordre
        sorted_controls = sorted(controls, key=lambda c: c.get("order", 0))

        # === Détection des problèmes ===

        # 1. Postes trop proches
        self._check_controls_distance(sorted_controls, result)

        # 2. Interpostes linéaires
        self._check_linear_interposts(sorted_controls, result)

        # 3. Traversées de routes (si OSM disponible)
        if self.osm_data:
            self._check_road_crossings(sorted_controls, result)

        # 4. Zones privées (si OSM disponible)
        if self.osm_data:
            self._check_private_areas(sorted_controls, result)

        # 5. Visibilité/Spoils
        self._check_visibility(sorted_controls, result)

        # 6. Croisements de circuits (si bounds disponible)
        if bounds:
            self._check_circuit_crossing(sorted_controls, bounds, result)

        # Calculer le score
        result.score = self._calculate_score(result.problems)

        return result

    def _check_controls_distance(
        self, controls: List[Dict], result: AnalysisResult
    ) -> None:
        """Détecte les postes trop proches."""
        for i in range(len(controls) - 1):
            c1 = controls[i]
            c2 = controls[i + 1]

            dist = self._calculate_distance(
                (c1.get("x", 0), c1.get("y", 0)), (c2.get("x", 0), c2.get("y", 0))
            )

            if dist < self.MIN_CONTROL_DISTANCE:
                result.problems.append(
                    Problem(
                        type="controls_too_close",
                        severity="medium",
                        category="technical",
                        description=f"Postes {c1.get('order')} et {c2.get('order')} trop proches: {dist:.0f}m",
                        location=(c1.get("x", 0), c1.get("y", 0)),
                        control_id=c1.get("id"),
                        interpost_id=(c1.get("id"), c2.get("id")),
                        details={
                            "distance": dist,
                            "min_distance": self.MIN_CONTROL_DISTANCE,
                        },
                        suggested_fix=f"Déplacer le poste {c2.get('order')} d'au moins {self.MIN_CONTROL_DISTANCE - dist:.0f}m",
                    )
                )

    def _check_linear_interposts(
        self, controls: List[Dict], result: AnalysisResult
    ) -> None:
        """Détecte les interpostes trop linéaires (sans choix)."""
        for i in range(len(controls) - 1):
            c1 = controls[i]
            c2 = controls[i + 1]

            # Calculer la direction
            dx = c2.get("x", 0) - c1.get("x", 0)
            dy = c2.get("y", 0) - c1.get("y", 0)
            angle = math.degrees(math.atan2(dy, dx))

            # Si l'angle est proche de 0, 90, 180, 270 -> linéaire
            # C'est une simplification
            angle_normalized = angle % 90
            if angle_normalized < 10 or angle_normalized > 80:
                result.problems.append(
                    Problem(
                        type="linear_interpost",
                        severity="low",
                        category="technical",
                        description=f"Interposte {c1.get('order')} -> {c2.get('order')} très linéaire",
                        location=(
                            (c1.get("x", 0) + c2.get("x", 0)) / 2,
                            (c1.get("y", 0) + c2.get("y", 0)) / 2,
                        ),
                        control_id=c1.get("id"),
                        interpost_id=(c1.get("id"), c2.get("id")),
                        details={"angle": angle},
                        suggested_fix="Envisager un autre placement pour créer un choix d'itinéraire",
                    )
                )

    def _check_road_crossings(
        self, controls: List[Dict], result: AnalysisResult
    ) -> None:
        """Détecte les traversées de routes dangereuses."""
        if not self.osm_data:
            return

        # Vérifier chaque contrôle près des routes
        for control in controls:
            cx, cy = control.get("x", 0), control.get("y", 0)

            # Simuler la vérification (en réalité, vérifier la distance aux routes OSM)
            # Pour l'instant, on retourne un exemple
            pass

    def _check_private_areas(
        self, controls: List[Dict], result: AnalysisResult
    ) -> None:
        """Détecte les postes en zones privées."""
        if not self.osm_data:
            return

        # Vérifier chaque contrôle par rapport aux zones privées OSM
        for control in controls:
            # Logique à implémenter
            pass

    def _check_visibility(self, controls: List[Dict], result: AnalysisResult) -> None:
        """Détecte les problèmes de visibilité (spoils)."""
        for i in range(len(controls)):
            for j in range(i + 1, len(controls)):
                c1 = controls[i]
                c2 = controls[j]

                dist = self._calculate_distance(
                    (c1.get("x", 0), c1.get("y", 0)), (c2.get("x", 0), c2.get("y", 0))
                )

                if dist < self.SPOIL_DISTANCE:
                    result.problems.append(
                        Problem(
                            type="visibility_spoil",
                            severity="medium",
                            category="visibility",
                            description=f"Postes {c1.get('order')} et {c2.get('order')} trop proches visuellement: {dist:.0f}m",
                            location=(c1.get("x", 0), c1.get("y", 0)),
                            control_id=c1.get("id"),
                            interpost_id=(c1.get("id"), c2.get("id")),
                            details={
                                "distance": dist,
                                "spoil_distance": self.SPOIL_DISTANCE,
                            },
                            suggested_fix=f"Éloigner les postes d'au moins {self.SPOIL_DISTANCE - dist:.0f}m",
                        )
                    )

    def _check_circuit_crossing(
        self, controls: List[Dict], bounds: Dict, result: AnalysisResult
    ) -> None:
        """Détecte les croisements de circuits."""
        # Logique à implémenter si on a plusieurs circuits
        pass

    def _calculate_distance(
        self, p1: Tuple[float, float], p2: Tuple[float, float]
    ) -> float:
        """Calcule la distance entre deux points."""
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)

    def _calculate_score(self, problems: List[Problem]) -> float:
        """Calcule un score全局 sur 100."""
        score = 100.0

        for problem in problems:
            if problem.severity == "high":
                score -= 15
            elif problem.severity == "medium":
                score -= 5
            else:  # low
                score -= 2

        return max(0.0, score)

    def generate_report(self, result: AnalysisResult) -> Dict:
        """Génère un rapport d'analyse."""
        return {
            "circuit_id": result.circuit_id,
            "analyzed_at": result.analyzed_at.isoformat(),
            "score": result.score,
            "status": "OK"
            if result.score >= 70
            else "ATTENTION"
            if result.score >= 50
            else "CRITIQUE",
            "problem_count": result.problem_count,
            "has_critical_issues": result.has_critical_issues,
            "problems": [
                {
                    "type": p.type,
                    "severity": p.severity,
                    "category": p.category,
                    "description": p.description,
                    "location": p.location,
                    "suggested_fix": p.suggested_fix,
                }
                for p in result.problems
            ],
        }


# =============================================
# Fonctions utilitaires
# =============================================
def calculate_distance_meters(
    x1: float, y1: float, x2: float, y2: float, crs: str = "WGS84"
) -> float:
    """
    Calcule la distance entre deux points en mètres.

    Args:
        x1, y1: Coordonnées point 1
        x2, y2: Coordonnées point 2
        crs: Système de coordonnées

    Returns:
        Distance en mètres
    """
    if crs == "WGS84":
        # Utiliser la formule de Haversine pour les coordonnées lat/lon
        # Approximation pour les courtes distances
        lat1, lon1 = y1, x1
        lat2, lon2 = y2, x2

        # 1 degré de latitude ≈ 111 km
        # 1 degré de longitude ≈ 111 km * cos(lat)
        dlat = (lat2 - lat1) * 111000
        dlon = (lon2 - lon1) * 111000 * abs(math.cos(math.radians((lat1 + lat2) / 2)))

        return math.sqrt(dlat**2 + dlon**2)
    else:
        # Pour les autres CRS (Lambert, etc.), les unités sont déjà en mètres
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
