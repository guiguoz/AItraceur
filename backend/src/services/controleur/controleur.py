"""
ControleurSprint — Validation automatique IOF/FFCO poste par poste.

Reproduit le rôle du contrôleur officiel : vérifie que chaque poste
et chaque jambe d'un circuit sprint respectent les règles IOF et FFCO.

Sources:
- IOF Sprint Course Planning Guidelines, Jun 2020
- ISSprOM 2019 (International Specification for Sprint Orienteering Maps)
- FFCO Règles Techniques et de Sécurité, Ed. juin 2023
- Mémento du Corps Arbitral FFCO, Ed. 2023
"""

import json
import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, TYPE_CHECKING

try:
    from src.services.optimization.route_analyzer import RouteAnalyzer
    _HAS_ROUTE_ANALYZER = True
except ImportError:
    _HAS_ROUTE_ANALYZER = False
    RouteAnalyzer = None  # type: ignore


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ControleurIssue:
    code: str                      # "C01" … "C12"
    severity: str                  # "ERROR" | "WARNING" | "INFO"
    control_index: int             # index du poste concerné (-1 = global)
    leg_from: int                  # jambe départ (-1 si pas de jambe)
    leg_to: int                    # jambe arrivée (-1 si pas de jambe)
    message: str                   # description lisible
    suggestion: str                # correction recommandée
    rule_reference: str            # article/doc source


@dataclass
class ControleurReport:
    is_valid: bool
    error_count: int
    warning_count: int
    info_count: int
    issues: List[ControleurIssue]
    global_score: float            # 0–100
    iof_compliant: bool
    ffco_compliant: bool
    summary: str
    iterations_used: int = 0       # rempli par la boucle traceur↔contrôleur


# ── Géométrie utilitaire ──────────────────────────────────────────────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux points WGS84."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing (azimut) en degrés depuis (lat1,lon1) vers (lat2,lon2). [0, 360["""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _angle_between_bearings(b1: float, b2: float) -> float:
    """Angle entre deux bearings, dans [0, 180]."""
    diff = abs(b1 - b2) % 360
    return diff if diff <= 180 else 360 - diff


def _point_to_segment_distance_m(
    lat: float, lon: float,
    lat1: float, lon1: float,
    lat2: float, lon2: float
) -> float:
    """Distance approximative d'un point à un segment (en mètres, projection planaire locale)."""
    # Convert to local Cartesian (metres)
    cos_lat = math.cos(math.radians((lat1 + lat2) / 2))
    R = 6_371_000
    ax = math.radians(lon1) * R * cos_lat
    ay = math.radians(lat1) * R
    bx = math.radians(lon2) * R * cos_lat
    by = math.radians(lat2) * R
    px = math.radians(lon) * R * cos_lat
    py = math.radians(lat) * R

    ab = (bx - ax, by - ay)
    ap = (px - ax, py - ay)
    ab_sq = ab[0] ** 2 + ab[1] ** 2
    if ab_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1]) / ab_sq))
    proj = (ax + t * ab[0], ay + t * ab[1])
    return math.hypot(px - proj[0], py - proj[1])


def _point_in_polygon(lat: float, lon: float, polygon: List[List[float]]) -> bool:
    """
    Ray-casting point-in-polygon.
    polygon: [[lon, lat], ...] (format GeoJSON WGS84).
    """
    x, y = lon, lat
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ── Classe principale ─────────────────────────────────────────────────────────

class ControleurSprint:
    """
    Valide un circuit sprint poste par poste selon les normes IOF/FFCO.
    Retourne un rapport structuré avec issues C01–C12.
    """

    def __init__(self, rules_path: Optional[str] = None):
        if rules_path is None:
            rules_path = os.path.join(os.path.dirname(__file__), "controleur_rules.json")
        with open(rules_path, encoding="utf-8") as f:
            all_rules = json.load(f)
        self.rules = all_rules.get("sprint", {})

    # ── Point d'entrée ────────────────────────────────────────────────────────

    def validate(
        self,
        controls: List[Dict],
        oob_polygons: Optional[List[List[List[float]]]] = None,
        circuit_config: Optional[Dict] = None,
        osm_ways: Optional[List[Dict]] = None,
        route_analyzer=None,
    ) -> ControleurReport:
        """
        Lance tous les checks C01–C12 sur la liste de postes.

        controls: [{"lat": float, "lng": float, "type": "start"|"control"|"finish",
                    "order": int, "feature_type": str (optionnel)}, ...]
        oob_polygons: zones interdites [[lon, lat], ...]
        circuit_config: {"category": "elite"|"junior"|"training", "circuit_type": "sprint"}
        route_analyzer: instance RouteAnalyzer (optionnel) — active C01 réel + C11
        """
        issues: List[ControleurIssue] = []
        ordered = sorted(
            [c for c in controls if c.get("type") in ("start", "control", "finish")],
            key=lambda c: c.get("order", 0)
        )

        if len(ordered) < 2:
            return ControleurReport(
                is_valid=False, error_count=1, warning_count=0, info_count=0,
                issues=[ControleurIssue(
                    code="C00", severity="ERROR", control_index=-1,
                    leg_from=-1, leg_to=-1,
                    message="Circuit vide ou insuffisant (< 2 postes)",
                    suggestion="Ajoutez au moins un départ et un poste.",
                    rule_reference="IOF Sprint §3.1"
                )],
                global_score=0.0, iof_compliant=False, ffco_compliant=False,
                summary="Circuit invalide : trop peu de postes."
            )

        issues += self._check_c02_too_close(ordered)
        issues += self._check_c01_dogleg(ordered, route_analyzer=route_analyzer)
        issues += self._check_c03_leg_too_long(ordered)
        issues += self._check_c04_leg_too_short(ordered)
        issues += self._check_c05_control_count(ordered)
        issues += self._check_c06_estimated_time(ordered, circuit_config)
        issues += self._check_c07_climb(ordered)
        issues += self._check_c08_forbidden_zone(ordered, oob_polygons or [])
        issues += self._check_c10_feature_type(ordered)
        issues += self._check_c11_route_choice(ordered, route_analyzer=route_analyzer)
        issues += self._check_c12_parallel_legs(ordered)
        issues += self._check_c13_undescribable(ordered)

        error_count = sum(1 for i in issues if i.severity == "ERROR")
        warning_count = sum(1 for i in issues if i.severity == "WARNING")
        info_count = sum(1 for i in issues if i.severity == "INFO")

        # Score: 100 - 15×ERROR - 5×WARNING - 1×INFO, min 0
        score = max(0.0, 100.0 - error_count * 15 - warning_count * 5 - info_count * 1)

        iof_compliant = error_count == 0 and warning_count <= 2
        ffco_compliant = error_count == 0

        if error_count == 0 and warning_count == 0:
            summary = f"Circuit conforme IOF + FFCO. Score {score:.0f}/100."
        elif error_count > 0:
            summary = f"{error_count} erreur(s) bloquante(s). Score {score:.0f}/100."
        else:
            summary = f"Acceptable avec {warning_count} avertissement(s). Score {score:.0f}/100."

        return ControleurReport(
            is_valid=error_count == 0,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            issues=sorted(issues, key=lambda i: (0 if i.severity == "ERROR" else 1 if i.severity == "WARNING" else 2)),
            global_score=score,
            iof_compliant=iof_compliant,
            ffco_compliant=ffco_compliant,
            summary=summary,
        )

    # ── Checks C01–C12 ───────────────────────────────────────────────────────

    def _check_c01_dogleg(self, controls: List[Dict], route_analyzer=None) -> List[ControleurIssue]:
        """
        C01 — Dog-leg.

        Avec RouteAnalyzer : dog-leg réel (A* P_n-1→P_n+1 passe à <30m de P_n).
        Sans RouteAnalyzer : fallback bearing haversine (angle < seuil).
        """
        legs_rules = self.rules.get("legs", {})
        angle_threshold = legs_rules.get("dog_leg_angle_deg", 25)
        proximity_m = legs_rules.get("dog_leg_proximity_m", 30)
        issues = []

        for i in range(1, len(controls) - 1):
            prev, mid, nxt = controls[i - 1], controls[i], controls[i + 1]

            if route_analyzer is not None:
                # Dog-leg réel via A*
                is_dl, dist_m = route_analyzer.detect_dogleg(prev, mid, nxt, proximity_m=proximity_m)
                if is_dl:
                    issues.append(ControleurIssue(
                        code="C01", severity="ERROR",
                        control_index=i, leg_from=i - 1, leg_to=i + 1,
                        message=(
                            f"Dog-leg réel au poste {i + 1} : la route optimale "
                            f"{i}→{i + 2} passe à {dist_m:.0f}m du poste "
                            f"(seuil {proximity_m}m). Le coureur voit le poste en passant."
                        ),
                        suggestion=f"Déplacer le poste {i + 1} perpendiculairement à la jambe {i}→{i + 2}.",
                        rule_reference="IOF Sprint Guidelines §4.3 / OCAD Route Analyzer"
                    ))
            else:
                # Fallback : bearing haversine
                b_in = _bearing_deg(prev["lat"], prev["lng"], mid["lat"], mid["lng"])
                b_out = _bearing_deg(mid["lat"], mid["lng"], nxt["lat"], nxt["lng"])
                angle = _angle_between_bearings(b_in, (b_out + 180) % 360)
                if angle < angle_threshold:
                    issues.append(ControleurIssue(
                        code="C01", severity="ERROR",
                        control_index=i, leg_from=i - 1, leg_to=i + 1,
                        message=f"Dog-leg détecté au poste {i + 1} (angle {angle:.0f}° < {angle_threshold}°). Le coureur rebrousse chemin.",
                        suggestion=f"Déplacer le poste {i + 1} perpendiculairement à la jambe {i}→{i + 2}.",
                        rule_reference="IOF Sprint Guidelines §4.3"
                    ))
        return issues

    def _check_c11_route_choice(self, controls: List[Dict], route_analyzer=None) -> List[ControleurIssue]:
        """
        C11 — Choix d'itinéraire.

        Pour les jambes > 80m, le score de diversité Jaccard doit dépasser
        route_choice_diversity_min (défaut 0.25).
        Sans RouteAnalyzer : check non effectué (retourne []).
        """
        if route_analyzer is None:
            return []

        min_diversity = self.rules.get("legs", {}).get("route_choice_diversity_min", 0.25)
        min_leg_m = 80  # jambes courtes : couloir acceptable
        issues = []

        for i in range(len(controls) - 1):
            a, b = controls[i], controls[i + 1]
            leg_dist = _haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
            if leg_dist < min_leg_m:
                continue

            score = route_analyzer.route_diversity_score(a["lng"], a["lat"], b["lng"], b["lat"])
            if score < min_diversity:
                issues.append(ControleurIssue(
                    code="C11", severity="WARNING",
                    control_index=i + 1, leg_from=i, leg_to=i + 1,
                    message=(
                        f"Jambe {i + 1}→{i + 2} ({leg_dist:.0f}m) sans choix d'itinéraire "
                        f"(diversité {score:.2f} < {min_diversity}). Couloir unique."
                    ),
                    suggestion=(
                        f"Repositionner le poste {i + 1} ou {i + 2} pour offrir "
                        "au moins deux routes viables de longueur similaire."
                    ),
                    rule_reference="IOF Sprint Guidelines §4.3 — route choice"
                ))
        return issues

    def _check_c02_too_close(self, controls: List[Dict]) -> List[ControleurIssue]:
        """C02 — Postes consécutifs trop proches."""
        min_dist = self.rules.get("control_placement", {}).get("min_separation_m", 30)
        issues = []
        for i in range(len(controls) - 1):
            a, b = controls[i], controls[i + 1]
            dist = _haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
            if dist < min_dist:
                issues.append(ControleurIssue(
                    code="C02", severity="ERROR",
                    control_index=i + 1, leg_from=i, leg_to=i + 1,
                    message=f"Postes {i + 1}→{i + 2} trop proches ({dist:.0f}m < {min_dist}m minimum).",
                    suggestion=f"Éloigner le poste {i + 2} d'au moins {min_dist - dist:.0f}m supplémentaires.",
                    rule_reference="ISSprOM 2019 §6.1"
                ))
        return issues

    def _check_c03_leg_too_long(self, controls: List[Dict]) -> List[ControleurIssue]:
        """C03 — Jambe trop longue pour le sprint."""
        max_leg = self.rules.get("legs", {}).get("max_leg_m", 400)
        issues = []
        for i in range(len(controls) - 1):
            a, b = controls[i], controls[i + 1]
            dist = _haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
            if dist > max_leg:
                issues.append(ControleurIssue(
                    code="C03", severity="WARNING",
                    control_index=i + 1, leg_from=i, leg_to=i + 1,
                    message=f"Jambe {i + 1}→{i + 2} trop longue ({dist:.0f}m > {max_leg}m recommandé sprint).",
                    suggestion=f"Insérer un poste intermédiaire ou rapprocher {i + 1} et {i + 2}.",
                    rule_reference="IOF Sprint Guidelines §3 (distances sprint urbain)"
                ))
        return issues

    def _check_c04_leg_too_short(self, controls: List[Dict]) -> List[ControleurIssue]:
        """C04 — Jambe trop courte."""
        min_leg = self.rules.get("legs", {}).get("min_leg_m", 30)
        issues = []
        for i in range(len(controls) - 1):
            a, b = controls[i], controls[i + 1]
            dist = _haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
            if dist < min_leg:
                issues.append(ControleurIssue(
                    code="C04", severity="WARNING",
                    control_index=i + 1, leg_from=i, leg_to=i + 1,
                    message=f"Jambe {i + 1}→{i + 2} très courte ({dist:.0f}m < {min_leg}m).",
                    suggestion="Revoir le placement des postes pour allonger cette jambe.",
                    rule_reference="IOF Sprint Guidelines §4"
                ))
        return issues

    def _check_c05_control_count(self, controls: List[Dict]) -> List[ControleurIssue]:
        """C05 — Nombre de postes hors plage IOF sprint."""
        ctrl_count = len([c for c in controls if c.get("type") == "control"])
        min_c = self.rules.get("circuit", {}).get("min_controls", 12)
        max_c = self.rules.get("circuit", {}).get("max_controls", 28)
        issues = []
        if ctrl_count < min_c:
            issues.append(ControleurIssue(
                code="C05", severity="WARNING",
                control_index=-1, leg_from=-1, leg_to=-1,
                message=f"Trop peu de postes ({ctrl_count} < {min_c} minimum sprint).",
                suggestion=f"Ajouter {min_c - ctrl_count} poste(s) pour atteindre le minimum.",
                rule_reference="IOF Sprint Guidelines §3.1"
            ))
        elif ctrl_count > max_c:
            issues.append(ControleurIssue(
                code="C05", severity="WARNING",
                control_index=-1, leg_from=-1, leg_to=-1,
                message=f"Trop de postes ({ctrl_count} > {max_c} maximum sprint).",
                suggestion=f"Supprimer {ctrl_count - max_c} poste(s).",
                rule_reference="IOF Sprint Guidelines §3.1"
            ))
        return issues

    def _check_c06_estimated_time(
        self, controls: List[Dict], config: Optional[Dict]
    ) -> List[ControleurIssue]:
        """C06 — Temps estimé hors cible (Tobler simplifié : 3.5 m/s en sprint)."""
        category = (config or {}).get("category", "elite")
        targets = self.rules.get("circuit", {}).get("winning_time_targets", {})
        target = targets.get(category, targets.get("elite", {"min_min": 12, "max_min": 15}))

        total_dist = sum(
            _haversine_m(controls[i]["lat"], controls[i]["lng"],
                         controls[i + 1]["lat"], controls[i + 1]["lng"])
            for i in range(len(controls) - 1)
        )
        sprint_speed_ms = 3.5  # m/s, vitesse élite sprint IOF
        estimated_min = total_dist / sprint_speed_ms / 60

        issues = []
        if estimated_min < target["min_min"] * 0.8:
            issues.append(ControleurIssue(
                code="C06", severity="WARNING",
                control_index=-1, leg_from=-1, leg_to=-1,
                message=f"Circuit trop court : ~{estimated_min:.1f} min estimé (cible {target['min_min']}–{target['max_min']} min).",
                suggestion="Allonger le circuit ou ajouter des postes.",
                rule_reference="IOF Sprint Guidelines §3.1"
            ))
        elif estimated_min > target["max_min"] * 1.2:
            issues.append(ControleurIssue(
                code="C06", severity="WARNING",
                control_index=-1, leg_from=-1, leg_to=-1,
                message=f"Circuit trop long : ~{estimated_min:.1f} min estimé (cible {target['min_min']}–{target['max_min']} min).",
                suggestion="Réduire la distance totale.",
                rule_reference="IOF Sprint Guidelines §3.1"
            ))
        return issues

    def _check_c07_climb(self, controls: List[Dict]) -> List[ControleurIssue]:
        """C07 — Montée totale estimée > 3% (si élévation disponible)."""
        max_climb_pct = self.rules.get("circuit", {}).get("max_climb_pct", 3.0)
        elev_values = [c.get("elevation") for c in controls if c.get("elevation") is not None]
        if len(elev_values) < 2:
            return []  # pas de données d'élévation

        total_climb = sum(
            max(0, elev_values[i + 1] - elev_values[i])
            for i in range(len(elev_values) - 1)
        )
        total_dist = sum(
            _haversine_m(controls[i]["lat"], controls[i]["lng"],
                         controls[i + 1]["lat"], controls[i + 1]["lng"])
            for i in range(len(controls) - 1)
        )
        if total_dist == 0:
            return []
        climb_pct = total_climb / total_dist * 100

        if climb_pct > max_climb_pct:
            return [ControleurIssue(
                code="C07", severity="WARNING",
                control_index=-1, leg_from=-1, leg_to=-1,
                message=f"Montée totale {climb_pct:.1f}% > {max_climb_pct}% recommandé sprint.",
                suggestion="Choisir un tracé plus plat ou déplacer des postes vers des zones planes.",
                rule_reference="IOF Sprint Guidelines §3.2"
            )]
        return []

    def _check_c08_forbidden_zone(
        self, controls: List[Dict], oob_polygons: List[List[List[float]]]
    ) -> List[ControleurIssue]:
        """C08 — Poste dans une zone interdite (bâtiment OSM ou zone OOB)."""
        issues = []
        for i, ctrl in enumerate(controls):
            for poly in oob_polygons:
                if _point_in_polygon(ctrl["lat"], ctrl["lng"], poly):
                    issues.append(ControleurIssue(
                        code="C08", severity="ERROR",
                        control_index=i, leg_from=-1, leg_to=-1,
                        message=f"Poste {i + 1} dans une zone interdite (bâtiment ou zone OOB).",
                        suggestion=f"Déplacer le poste {i + 1} hors de la zone interdite.",
                        rule_reference="FFCO Règles Sécurité §12, ISSprOM 2019"
                    ))
                    break
        return issues

    def _check_c10_feature_type(self, controls: List[Dict]) -> List[ControleurIssue]:
        """C10 — Type de feature non recommandé pour le sprint."""
        avoid_types = set(
            self.rules.get("control_placement", {}).get("feature_quality", {}).get("avoid", [])
        )
        preferred_types = set(
            self.rules.get("control_placement", {}).get("feature_quality", {}).get("preferred", [])
        )
        issues = []
        for i, ctrl in enumerate(controls):
            ft = ctrl.get("feature_type") or ctrl.get("type_feature", "")
            if not ft:
                continue
            if ft in avoid_types:
                issues.append(ControleurIssue(
                    code="C10", severity="WARNING",
                    control_index=i, leg_from=-1, leg_to=-1,
                    message=f"Poste {i + 1} sur feature '{ft}' à éviter en sprint.",
                    suggestion=f"Déplacer vers un élément plus précis : {', '.join(list(preferred_types)[:3])}.",
                    rule_reference="ISSprOM 2019 §6.1"
                ))
        return issues

    def _check_c12_parallel_legs(self, controls: List[Dict]) -> List[ControleurIssue]:
        """C12 — Jambes parallèles (bearings similaires sur 3+ jambes consécutives)."""
        threshold = self.rules.get("legs", {}).get("parallel_bearing_threshold_deg", 20)
        issues = []
        if len(controls) < 3:
            return issues

        bearings = [
            _bearing_deg(controls[i]["lat"], controls[i]["lng"],
                         controls[i + 1]["lat"], controls[i + 1]["lng"])
            for i in range(len(controls) - 1)
        ]

        for i in range(len(bearings) - 1):
            angle_diff = _angle_between_bearings(bearings[i], bearings[i + 1])
            if angle_diff < threshold:
                issues.append(ControleurIssue(
                    code="C12", severity="WARNING",
                    control_index=i + 1, leg_from=i, leg_to=i + 2,
                    message=f"Jambes {i + 1}→{i + 2} et {i + 2}→{i + 3} presque parallèles (diff {angle_diff:.0f}°).",
                    suggestion="Varier la direction pour éviter les jambes en couloir successives.",
                    rule_reference="IOF Sprint Guidelines §4.3"
                ))
        return issues

    def _check_c13_undescribable(self, controls: List[Dict]) -> List[ControleurIssue]:
        """C13 — Poste sans feature IOF descriptible (Description des postes FFCO 2018).

        Un poste doit être placé sur un élément de terrain identifiable et descriptible
        selon la colonne D IOF. Un poste en 'Position libre' ou sur 'terrain ouvert (4.1)'
        n'est pas conforme (impossible à décrire précisément sur la feuille de postes).
        """
        NON_DESCRIPTIBLE = {
            "Position libre",
            "terrain ouvert (4.1)",
            "terrain semi-ouvert (4.2)",
            "Terrain ouvert (4.1)",
            "Terrain semi-ouvert (4.2)",
        }
        issues = []
        for i, ctrl in enumerate(controls):
            if ctrl.get("type") in ("start", "finish"):
                continue
            desc = ctrl.get("description", "")
            if not desc or desc in NON_DESCRIPTIBLE or desc.startswith("ISOM "):
                issues.append(ControleurIssue(
                    code="C13", severity="WARNING",
                    control_index=i, leg_from=-1, leg_to=-1,
                    message=(
                        f"Poste {ctrl.get('order', i + 1)} sans feature IOF descriptible "
                        f"(description : '{desc or 'aucune'}')."
                    ),
                    suggestion=(
                        "Déplacer le poste sur un élément précis : jonction de chemins (10.2), "
                        "coin de bâtiment (5.11), dépression (1.10), bloc (2.4)… "
                        "La feuille de description des postes (FFCO 2018) requiert une colonne D définie."
                    ),
                    rule_reference="IOF Control Descriptions 2018 §Col.D / FFCO Description des postes 2018"
                ))
        return issues

    # ── Méthodes utilitaires ──────────────────────────────────────────────────

    def to_dict(self, report: ControleurReport) -> Dict:
        """Sérialise un ControleurReport en dictionnaire JSON-compatible."""
        return {
            "is_valid": report.is_valid,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "info_count": report.info_count,
            "global_score": report.global_score,
            "iof_compliant": report.iof_compliant,
            "ffco_compliant": report.ffco_compliant,
            "summary": report.summary,
            "iterations_used": report.iterations_used,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "control_index": issue.control_index,
                    "leg_from": issue.leg_from,
                    "leg_to": issue.leg_to,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                    "rule_reference": issue.rule_reference,
                }
                for issue in report.issues
            ],
        }
