# =============================================
# Scorer de circuits
# Sprint 7: Génération de circuits (Forêt)
# =============================================

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    from ..controleur.controleur import ControleurSprint
    _CONTROLEUR_AVAILABLE = True
except Exception:
    _CONTROLEUR_AVAILABLE = False


# =============================================
# Types de données
# =============================================
@dataclass
class ScoreBreakdown:
    """Détail du score."""

    length_score: float = 0
    climb_score: float = 0
    control_distance_score: float = 0
    variety_score: float = 0
    balance_score: float = 0
    safety_score: float = 0
    technical_score: float = 0


@dataclass
class IOFCompliance:
    """Conformité IOF du circuit."""

    td_grade: int = 0         # 1-5 (Difficulté Technique)
    pd_grade: int = 0         # 1-5 (Difficulté Physique)
    td_label: str = ""        # "TD1 — Très facile", etc.
    pd_label: str = ""
    climb_ratio: float = 0.0  # D+ / distance (limite IOF: ≤4%)
    dog_legs: int = 0         # Nombre de dog-legs détectés (angle < 20°)
    too_close_controls: int = 0  # Postes à moins de 60m
    iof_valid: bool = False   # Conformité globale IOF
    compliance_score: float = 0.0  # 0-100


@dataclass
class CircuitScore:
    """Score complet d'un circuit."""

    total_score: float  # 0-100
    grade: str  # A, B, C, D, F
    breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    iof: IOFCompliance = field(default_factory=IOFCompliance)
    issues: List[Dict] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


# =============================================
# Scorer
# =============================================
class CircuitScorer:
    """
    Évalue la qualité d'un circuit de CO.

    Critères:
    - Longueur (proximité de la cible)
    - Dénivelé (équilibre)
    - Distance entre postes
    - Variété technique
    - Équilibre général
    - Sécurité
    """

    # Pondérations
    WEIGHTS = {
        "length": 0.20,
        "climb": 0.15,
        "control_distance": 0.15,
        "variety": 0.20,
        "balance": 0.15,
        "safety": 0.15,
    }

    def __init__(self):
        """Initialise le scorer."""
        self.osm_data = None
        self.lidar_data = None

    @staticmethod
    def _haversine_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Distance haversine en mètres entre deux points WGS84 (x=lng, y=lat)."""
        R = 6_371_000.0
        lat1, lat2 = math.radians(p1[1]), math.radians(p2[1])
        dlat = math.radians(p2[1] - p1[1])
        dlng = math.radians(p2[0] - p1[0])
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def load_osm_data(self, osm_data: Dict):
        """Charge les données OSM."""
        self.osm_data = osm_data

    def load_lidar_data(self, lidar_data: Dict):
        """Charge les données LIDAR."""
        self.lidar_data = lidar_data

    def score(
        self,
        controls: List[Dict],
        target_length: float = None,
        target_climb: float = None,
        category: str = None,
    ) -> CircuitScore:
        """
        Calcule le score d'un circuit.

        Args:
            controls: Liste des postes [{x, y, order, ...}]
            target_length: Longueur cible en mètres
            target_climb: D+ cible en mètres
            category: Catégorie du circuit

        Returns:
            CircuitScore complet
        """
        breakdown = ScoreBreakdown()
        issues = []
        strengths = []
        suggestions = []

        # Préparation des données
        positions = [(c["x"], c["y"]) for c in controls]

        # 1. Score de longueur
        length = self._calculate_total_length(positions)
        if target_length:
            breakdown.length_score = self._score_length(length, target_length)
        else:
            breakdown.length_score = 75  # Score moyen si pas de cible

        # 2. Score de dénivelé
        if target_climb:
            climb = target_climb  # À calculer depuis LIDAR
            breakdown.climb_score = self._score_climb(climb, target_climb)
        else:
            breakdown.climb_score = 75

        # 3. Score de distance entre postes
        breakdown.control_distance_score = self._score_control_distances(positions)

        # 4. Score de variété
        breakdown.variety_score = self._score_variety(positions)

        # 5. Score d'équilibre
        breakdown.balance_score = self._score_balance(positions)

        # 6. Score de sécurité (si OSM disponible)
        if self.osm_data:
            breakdown.safety_score = self._score_safety(positions)
        else:
            breakdown.safety_score = 70

        # Calcul du score total
        total = (
            breakdown.length_score * self.WEIGHTS["length"]
            + breakdown.climb_score * self.WEIGHTS["climb"]
            + breakdown.control_distance_score * self.WEIGHTS["control_distance"]
            + breakdown.variety_score * self.WEIGHTS["variety"]
            + breakdown.balance_score * self.WEIGHTS["balance"]
            + breakdown.safety_score * self.WEIGHTS["safety"]
        )

        # Déterminer la lettre
        if total >= 90:
            grade = "A"
        elif total >= 80:
            grade = "B"
        elif total >= 70:
            grade = "C"
        elif total >= 60:
            grade = "D"
        else:
            grade = "F"

        # Conformité IOF (TD/PD/dog-legs/séparation)
        iof = self._compute_iof_compliance(positions, target_length, target_climb)

        # Générer les suggestions
        suggestions = self._generate_suggestions(breakdown)
        strengths = self._generate_strengths(breakdown)

        # Ajouter suggestions IOF
        if not iof.iof_valid:
            if iof.dog_legs > 0:
                suggestions.append(f"Corriger {iof.dog_legs} dog-leg(s) détecté(s) (angle entrée/sortie < 25°)")
            if iof.too_close_controls > 0:
                suggestions.append(f"{iof.too_close_controls} poste(s) trop proches — règle IOF AA3.5.5")
            if iof.climb_ratio > 0.04 and target_length:
                suggestions.append(
                    f"D+ trop élevé ({iof.climb_ratio:.1%} vs limite IOF 4%) — alléger le tracé"
                )

        # Enrichir issues avec le contrôleur IOF/FFCO (per-poste avec références)
        if _CONTROLEUR_AVAILABLE and controls:
            try:
                ctrl_report = ControleurSprint().validate(controls)
                issues = [
                    {
                        "code": iss.code,
                        "severity": iss.severity,
                        "control_index": iss.control_index,
                        "leg_from": iss.leg_from,
                        "leg_to": iss.leg_to,
                        "message": iss.message,
                        "suggestion": iss.suggestion,
                        "rule_reference": iss.rule_reference,
                    }
                    for iss in ctrl_report.issues
                ]
                # Sync dog-leg count avec le contrôleur (haversine corrigé)
                iof.dog_legs = sum(1 for iss in ctrl_report.issues if iss.code == "C01")
                iof.too_close_controls = sum(1 for iss in ctrl_report.issues if iss.code == "C02")
            except Exception:
                pass  # Fallback silencieux si contrôleur non disponible

        return CircuitScore(
            total_score=total,
            grade=grade,
            breakdown=breakdown,
            iof=iof,
            issues=issues,
            strengths=strengths,
            suggestions=suggestions,
        )

    def _calculate_total_length(self, positions: List[Tuple[float, float]]) -> float:
        """Calcule la longueur totale en mètres (haversine WGS84)."""
        total = 0.0
        for i in range(len(positions) - 1):
            total += self._haversine_m(positions[i], positions[i + 1])
        return total

    def _score_length(self, actual: float, target: float) -> float:
        """Score de longueur (0-100)."""
        if target == 0:
            return 50

        ratio = actual / target

        if 0.95 <= ratio <= 1.05:
            return 100  # Parfait
        elif 0.90 <= ratio <= 1.10:
            return 90
        elif 0.85 <= ratio <= 1.15:
            return 80
        elif 0.80 <= ratio <= 1.20:
            return 70
        elif 0.70 <= ratio <= 1.30:
            return 60
        else:
            return 50

    def _score_climb(self, actual: float, target: float) -> float:
        """Score de dénivelé (0-100)."""
        if target == 0:
            return 50

        ratio = actual / target

        if 0.90 <= ratio <= 1.10:
            return 100
        elif 0.80 <= ratio <= 1.20:
            return 85
        elif 0.70 <= ratio <= 1.30:
            return 70
        else:
            return 55

    def _score_control_distances(self, positions: List[Tuple[float, float]]) -> float:
        """Score des distances entre postes."""
        min_distances = []

        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dist = self._haversine_m(positions[i], positions[j])
                min_distances.append(dist)

        if not min_distances:
            return 50

        # Calculer la distance minimale entre postes consécutifs
        consecutive_dists = []
        for i in range(len(positions) - 1):
            dist = self._haversine_m(positions[i], positions[i + 1])
            consecutive_dists.append(dist)

        # Score basé sur les distances minimales
        avg_dist = sum(consecutive_dists) / len(consecutive_dists)
        min_dist = min(consecutive_dists)

        # Pénalité si des postes sont trop proches
        penalty = 0
        for dist in consecutive_dists:
            if dist < 60:
                penalty += 20
            elif dist < 80:
                penalty += 10

        return max(0, 100 - penalty)

    def _score_variety(self, positions: List[Tuple[float, float]]) -> float:
        """Score de variété technique."""
        if len(positions) < 3:
            return 50

        # Calculer les angles entre interpostes
        angles = []
        for i in range(len(positions) - 2):
            v1 = (
                positions[i + 1][0] - positions[i][0],
                positions[i + 1][1] - positions[i][1],
            )
            v2 = (
                positions[i + 2][0] - positions[i + 1][0],
                positions[i + 2][1] - positions[i + 1][1],
            )

            angle = abs(math.atan2(v2[1], v2[0]) - math.atan2(v1[1], v1[0]))
            angles.append(angle)

        if not angles:
            return 50

        # Calculer la variance
        mean = sum(angles) / len(angles)
        variance = sum((a - mean) ** 2 for a in angles) / len(angles)

        # Plus de variance = plus de variété = meilleur score
        # Normaliser ( variance max ~ 3)
        normalized = min(1.0, variance / 2)

        return normalized * 100

    def _score_balance(self, positions: List[Tuple[float, float]]) -> float:
        """Score d'équilibre du circuit."""
        if len(positions) < 2:
            return 50

        # Calculer les distances entre interpostes
        distances = []
        for i in range(len(positions) - 1):
            dist = math.sqrt(
                (positions[i + 1][0] - positions[i][0]) ** 2
                + (positions[i + 1][1] - positions[i][1]) ** 2
            )
            distances.append(dist)

        if not distances:
            return 50

        # Calculer le coefficient de variation
        mean = sum(distances) / len(distances)
        if mean == 0:
            return 50

        variance = sum((d - mean) ** 2 for d in distances) / len(distances)
        std_dev = math.sqrt(variance)
        cv = std_dev / mean

        # CV bas = circuit équilibré
        if cv < 0.2:
            return 100
        elif cv < 0.3:
            return 85
        elif cv < 0.4:
            return 70
        elif cv < 0.5:
            return 55
        else:
            return 40

    def _score_safety(self, positions: List[Tuple[float, float]]) -> float:
        """Score de sécurité basé sur OSM."""
        if not self.osm_data:
            return 70

        # Vérifier les routes à proximité
        roads = self.osm_data.get("roads", [])

        # Pour l'instant, score de base
        # À implémenter: vérifier les traversées de routes
        return 75

    def _compute_iof_compliance(
        self,
        positions: List[Tuple[float, float]],
        target_length: Optional[float],
        target_climb: Optional[float],
    ) -> IOFCompliance:
        """
        Calcule la conformité IOF complète : TD, PD, dog-legs, séparation postes.
        Règles appliquées :
          - AA3.5.5 : séparation minimale 60m entre postes
          - AA8.3   : D+ ≤ 4% de la distance totale
          - AA3.5.4 : pas de dog-leg (angle entrée/sortie < 20°)
        """
        iof = IOFCompliance()

        # Longueur totale
        total_length = self._calculate_total_length(positions)

        # --- TD (Difficulté Technique) basé sur les jambes ---
        iof.td_grade, iof.td_label = self._grade_td(positions)

        # --- PD (Difficulté Physique) basé sur le dénivelé / distance ---
        climb = target_climb or 0.0
        iof.pd_grade, iof.pd_label = self._grade_pd(climb, total_length)
        if total_length > 0:
            iof.climb_ratio = climb / total_length

        # --- Dog-legs : bearing haversine corrigé (angle entrée/sortie < 25°) ---
        dog_legs = 0
        for i in range(1, len(positions) - 1):
            prev, curr, nxt = positions[i - 1], positions[i], positions[i + 1]
            # positions = (lng, lat), donc lng=x, lat=y
            b_in = math.degrees(math.atan2(
                math.sin(math.radians(curr[0] - prev[0])) * math.cos(math.radians(curr[1])),
                math.cos(math.radians(prev[1])) * math.sin(math.radians(curr[1])) -
                math.sin(math.radians(prev[1])) * math.cos(math.radians(curr[1])) *
                math.cos(math.radians(curr[0] - prev[0]))
            )) % 360
            b_out = math.degrees(math.atan2(
                math.sin(math.radians(nxt[0] - curr[0])) * math.cos(math.radians(nxt[1])),
                math.cos(math.radians(curr[1])) * math.sin(math.radians(nxt[1])) -
                math.sin(math.radians(curr[1])) * math.cos(math.radians(nxt[1])) *
                math.cos(math.radians(nxt[0] - curr[0]))
            )) % 360
            # Dog-leg: angle entre b_in et inverse de b_out
            b_out_inv = (b_out + 180) % 360
            diff = abs(b_in - b_out_inv) % 360
            if diff > 180:
                diff = 360 - diff
            if diff < 25:
                dog_legs += 1
        iof.dog_legs = dog_legs

        # --- Séparation minimale entre postes (≥ 60m) ---
        too_close = 0
        for i in range(len(positions) - 1):
            dist = self._haversine_m(positions[i], positions[i + 1])
            if dist < 60:
                too_close += 1
        iof.too_close_controls = too_close

        # --- Score de conformité global ---
        penalty = 0
        if iof.climb_ratio > 0.04:
            penalty += 20
        if iof.climb_ratio > 0.06:
            penalty += 10
        penalty += min(40, dog_legs * 10)
        penalty += min(30, too_close * 15)
        iof.compliance_score = max(0.0, 100.0 - penalty)
        iof.iof_valid = penalty == 0

        return iof

    def _grade_td(
        self, positions: List[Tuple[float, float]]
    ) -> Tuple[int, str]:
        """
        Estime la Difficulté Technique (TD1-TD5) à partir de la géométrie des jambes.
        Sans données terrain, on utilise la longueur maximale des jambes comme proxy.
        TD1 ≤200m | TD2 ≤350m | TD3 ≤700m | TD4 ≤1500m | TD5 >1500m
        """
        TD_LABELS = {
            1: "TD1 — Très facile (Blanc/Jaune)",
            2: "TD2 — Facile (Jaune)",
            3: "TD3 — Moyen (Orange)",
            4: "TD4 — Difficile (Vert)",
            5: "TD5 — Très difficile (Bleu/Noir)",
        }

        if len(positions) < 2:
            return 1, TD_LABELS[1]

        leg_lengths = []
        for i in range(len(positions) - 1):
            d = self._haversine_m(positions[i], positions[i + 1])
            leg_lengths.append(d)

        max_leg = max(leg_lengths)
        avg_leg = sum(leg_lengths) / len(leg_lengths)

        # Le TD se détermine sur la jambe la plus exigeante
        if max_leg <= 200:
            td = 1
        elif max_leg <= 350:
            td = 2
        elif max_leg <= 700:
            td = 3
        elif max_leg <= 1500:
            td = 4
        else:
            td = 5

        return td, TD_LABELS[td]

    def _grade_pd(
        self, climb_m: float, total_length_m: float
    ) -> Tuple[int, str]:
        """
        Calcule la Difficulté Physique (PD1-PD5) selon le ratio D+/distance.
        Règle IOF : D+ ≤ 4% de la distance = PD3 maximum en compétition.
        """
        PD_LABELS = {
            1: "PD1 — Très facile physiquement (<1% dénivelé)",
            2: "PD2 — Facile physiquement (<2%)",
            3: "PD3 — Moyen physiquement (<4% — limite IOF)",
            4: "PD4 — Difficile physiquement (<6%)",
            5: "PD5 — Très difficile physiquement (>6%)",
        }

        if total_length_m <= 0:
            return 1, PD_LABELS[1]

        ratio = climb_m / total_length_m

        if ratio < 0.01:
            pd = 1
        elif ratio < 0.02:
            pd = 2
        elif ratio < 0.04:
            pd = 3
        elif ratio < 0.06:
            pd = 4
        else:
            pd = 5

        return pd, PD_LABELS[pd]

    def _generate_suggestions(self, breakdown: ScoreBreakdown) -> List[str]:
        """Génère des suggestions d'amélioration."""
        suggestions = []

        if breakdown.length_score < 70:
            suggestions.append("Ajuster la longueur du circuit vers la valeur cible")

        if breakdown.control_distance_score < 70:
            suggestions.append("Éloigner certains postes trop proches")

        if breakdown.variety_score < 60:
            suggestions.append("Varier les directions pour créer plus de choix")

        if breakdown.balance_score < 70:
            suggestions.append("Équilibrer les distances entre interpostes")

        if breakdown.safety_score < 70:
            suggestions.append(
                "Vérifier les aspects de sécurité (routes, zones privées)"
            )

        return suggestions

    def _generate_strengths(self, breakdown: ScoreBreakdown) -> List[str]:
        """Génère la liste des points forts."""
        strengths = []

        if breakdown.length_score >= 90:
            strengths.append("Longueur conforme aux normes")

        if breakdown.control_distance_score >= 85:
            strengths.append("Distances entre postes adaptées")

        if breakdown.variety_score >= 80:
            strengths.append("Circuit varié avec de nombreux choix")

        if breakdown.balance_score >= 85:
            strengths.append("Bon équilibre général du circuit")

        if breakdown.safety_score >= 80:
            strengths.append("Aspect sécurité respecté")

        return strengths


# =============================================
# Comparaison de circuits
# =============================================
def compare_circuits(circuits: List[Dict]) -> Dict:
    """
    Compare plusieurs circuits.

    Args:
        circuits: Liste de circuits à comparer

    Returns:
        Comparaison
    """
    if len(circuits) < 2:
        return {"error": "Il faut au moins 2 circuits"}

    scorer = CircuitScorer()

    results = []
    for circuit in circuits:
        score = scorer.score(
            circuit.get("controls", []),
            target_length=circuit.get("length_meters"),
            target_climb=circuit.get("climb_meters"),
        )
        results.append(
            {
                "id": circuit.get("id", "unknown"),
                "score": score.total_score,
                "grade": score.grade,
            }
        )

    # Trier par score
    results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "circuits": results,
        "best": results[0] if results else None,
    }
