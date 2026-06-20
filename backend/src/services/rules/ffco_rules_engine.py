"""
FFCORulesEngine — Source de vérité unique pour toutes les règles IOF/FFCO.

Charge les 3 fichiers JSON de règles et expose des accesseurs typés
utilisés par le GA (genetic_algo.py) et le Contrôleur (controleur.py).

Usage :
    engine = FFCORulesEngine()
    params = engine.get_category_params("sprint", "H21E")
    weights = engine.get_ga_weights("sprint", td_level=3)
    thresholds = engine.get_fitness_thresholds("sprint", td_level=3)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# Chemins des fichiers JSON (relatifs à ce fichier)
_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
_FFCO_CATEGORIES_PATH = _DATA_DIR / "ffco_categories.json"
_PLACEMENT_RULES_PATH = _DATA_DIR / "placement_rules.json"  # dans knowledge_base/
_CONTROLEUR_RULES_PATH = (
    Path(__file__).parent.parent / "controleur" / "controleur_rules.json"
)
# placement_rules.json est dans knowledge_base/ par convention historique
_PLACEMENT_RULES_ALT = Path(__file__).parent.parent / "knowledge_base" / "placement_rules.json"


# ---------------------------------------------------------------------------
# Dataclasses de sortie
# ---------------------------------------------------------------------------

@dataclass
class CategoryParams:
    """Paramètres officiels FFCO pour un type de circuit + catégorie."""
    circuit_type: str
    category: str
    min_m: float
    max_m: float
    target_m: float          # milieu de fourchette = valeur cible GA
    td: str                  # "TD1" … "TD5"
    td_level: int            # 1 … 5
    winning_min_lo: float    # temps gagnant min (minutes)
    winning_min_hi: float    # temps gagnant max (minutes)
    target_controls: int
    max_climb_pct: float = 4.0   # pourcentage D+ / distance (défaut IOF)


@dataclass
class GAWeights:
    """Pondérations des critères de fitness dans _default_scoring()."""
    w_length: float     = 0.18
    w_climb: float      = 0.10
    w_td: float         = 0.11
    w_angle: float      = 0.15
    w_equity: float     = 0.12
    w_safety: float     = 0.07
    w_terrain: float    = 0.09
    w_monotony: float   = 0.07
    w_alternation: float = 0.07
    w_coverage: float   = 0.05   # couverture carte (std dev postes / bbox map)
    w_variety: float    = 0.04   # variété terrain CNN par jambe (std midpoints)
    # Sprint uniquement
    w_sprint_leg: float = 0.00   # remplace w_climb en sprint
    w_cluster: float    = 0.00


@dataclass
class FitnessThresholds:
    """Seuils utilisés dans evaluate_fitness() et _default_scoring()."""
    min_leg_m: float            = 60.0
    max_leg_m: float            = 1500.0
    min_control_separation_m: float = 60.0
    dog_leg_angle_deg: float    = 25.0
    max_climb_ratio: float      = 0.04   # 4 %
    angle_penalty_pts: float    = 20.0   # pts déduits par dog-leg
    density_penalty_mult: float = 50.0   # multiplicateur pénalité densité
    w_ai: float                 = 30.0   # poids HeatmapCache dans evaluate_fitness
    w_dist: float               = 40.0   # poids distance
    w_angle: float              = 1.0    # multiplicateur angle
    w_rhythm: float             = 15.0   # poids rythme


# ---------------------------------------------------------------------------
# FFCORulesEngine
# ---------------------------------------------------------------------------

class FFCORulesEngine:
    """
    Source de vérité unique pour les règles IOF/FFCO.
    Chargée une fois au démarrage via le singleton `get_engine()`.
    """

    def __init__(self) -> None:
        self._categories: Dict = {}
        self._placement: Dict = {}
        self._controleur: Dict = {}
        self._load()

    # ------------------------------------------------------------------
    # Chargement des JSON
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            self._categories = json.loads(_FFCO_CATEGORIES_PATH.read_text("utf-8"))
        except Exception as exc:
            log.warning("ffco_categories.json non chargé : %s", exc)

        placement_path = (
            _PLACEMENT_RULES_PATH if _PLACEMENT_RULES_PATH.exists()
            else _PLACEMENT_RULES_ALT
        )
        try:
            self._placement = json.loads(placement_path.read_text("utf-8"))
        except Exception as exc:
            log.warning("placement_rules.json non chargé : %s", exc)

        try:
            self._controleur = json.loads(_CONTROLEUR_RULES_PATH.read_text("utf-8"))
        except Exception as exc:
            log.warning("controleur_rules.json non chargé : %s", exc)

    # ------------------------------------------------------------------
    # API publique — Catégories
    # ------------------------------------------------------------------

    def get_category_params(self, circuit_type: str, category: str) -> CategoryParams:
        """
        Retourne les paramètres officiels FFCO pour (circuit_type, category).
        Fallback gracieux si la catégorie est inconnue.

        Exemples :
            get_category_params("sprint", "H21E")
            get_category_params("couleur", "Bleu")
        """
        ct = circuit_type.lower()
        section = self._categories.get(ct, {})
        data = section.get(category)

        if data is None:
            # Fallback : chercher la catégorie sans le préfixe sexe
            stripped = category.lstrip("HD")
            for k, v in section.items():
                if k.startswith("_"):
                    continue
                if k.lstrip("HD") == stripped:
                    data = v
                    break

        if data is None:
            log.warning("Catégorie inconnue : %s/%s — valeurs par défaut", ct, category)
            data = self._default_category_data(ct)

        td_str = data.get("td", "TD3")
        td_level = int(td_str.replace("TD", "")) if td_str.startswith("TD") else 3
        min_m = float(data.get("min_m", 2000))
        max_m = float(data.get("max_m", 3000))
        winning = data.get("winning_min", [12, 15])

        return CategoryParams(
            circuit_type=ct,
            category=category,
            min_m=min_m,
            max_m=max_m,
            target_m=(min_m + max_m) / 2,
            td=td_str,
            td_level=td_level,
            winning_min_lo=float(winning[0]),
            winning_min_hi=float(winning[1]),
            target_controls=int(data.get("target_controls", 12)),
            max_climb_pct=float(data.get("max_climb_pct", 4.0)),
        )

    def list_categories(self, circuit_type: str) -> List[str]:
        """Retourne toutes les catégories disponibles pour un type de circuit."""
        section = self._categories.get(circuit_type.lower(), {})
        return [k for k in section if not k.startswith("_")]

    # ------------------------------------------------------------------
    # API publique — GA Weights
    # ------------------------------------------------------------------

    def get_ga_weights(self, circuit_type: str, td_level: int = 3) -> GAWeights:
        """
        Retourne les pondérations GA selon le type de circuit.
        Les valeurs correspondent aux constantes historiques de _default_scoring().
        """
        ct = circuit_type.lower()
        if ct == "sprint":
            return GAWeights(
                w_length=0.20,
                w_climb=0.00,       # remplacé par w_sprint_leg en sprint
                w_td=0.10,
                w_angle=0.15,
                w_equity=0.07,
                w_safety=0.05,
                w_terrain=0.09,
                w_monotony=0.07,
                w_alternation=0.02,
                w_coverage=0.20,
                w_variety=0.01,
                w_sprint_leg=0.13,
                w_cluster=0.08,
            )
        # Forêt, MD, LD, Couleur — pondérations standard
        return GAWeights(
            w_length=0.17,
            w_climb=0.09,
            w_td=0.10,
            w_angle=0.13,
            w_equity=0.12,
            w_safety=0.07,
            w_terrain=0.09,
            w_monotony=0.07,
            w_alternation=0.05,
            w_coverage=0.09,
            w_variety=0.02,
        )

    # ------------------------------------------------------------------
    # API publique — Fitness Thresholds
    # ------------------------------------------------------------------

    def get_fitness_thresholds(
        self, circuit_type: str, td_level: int = 3
    ) -> FitnessThresholds:
        """
        Retourne les seuils de fitness depuis placement_rules.json.
        Fallback sur les valeurs historiques hardcodées si le JSON est absent.
        """
        ct = circuit_type.lower()
        td_key = f"TD{td_level}"
        section = self._placement.get(ct, self._placement.get("_defaults", {}))
        rules = section.get(td_key, section.get("_defaults", {}))

        return FitnessThresholds(
            min_leg_m=float(rules.get("min_leg_m", 30 if ct == "sprint" else 60)),
            max_leg_m=float(rules.get("max_leg_m", 400 if ct == "sprint" else 1500)),
            min_control_separation_m=float(rules.get("min_control_separation_m", 30 if ct == "sprint" else 60)),
            dog_leg_angle_deg=float(rules.get("dog_leg_angle_deg", 25.0)),
            max_climb_ratio=float(rules.get("max_climb_ratio", 0.03 if ct == "sprint" else 0.04)),
            # Constantes de fitness (inchangées — tuning empirique)
            angle_penalty_pts=20.0,
            density_penalty_mult=50.0,
            w_ai=30.0,
            w_dist=40.0,
            w_angle=1.0,
            w_rhythm=15.0,
        )

    # ------------------------------------------------------------------
    # API publique — Règles Contrôleur
    # ------------------------------------------------------------------

    def get_controleur_rules(self, circuit_type: str) -> Dict:
        """Retourne le contenu brut de controleur_rules.json pour un type de circuit."""
        ct = circuit_type.lower()
        return self._controleur.get(ct, self._controleur.get("sprint", {}))

    # ------------------------------------------------------------------
    # Privé — Fallbacks
    # ------------------------------------------------------------------

    @staticmethod
    def _default_category_data(circuit_type: str) -> Dict:
        defaults = {
            "sprint": {"min_m": 2000, "max_m": 3000, "td": "TD3", "winning_min": [12, 15], "target_controls": 14},
            "md":     {"min_m": 5000, "max_m": 8000, "td": "TD4", "winning_min": [30, 35], "target_controls": 16},
            "ld":     {"min_m": 10000,"max_m": 15000,"td": "TD5", "winning_min": [80, 100],"target_controls": 22},
            "couleur":{"min_m": 3000, "max_m": 6000, "td": "TD3", "winning_min": [30, 45], "target_controls": 12},
        }
        return defaults.get(circuit_type, defaults["md"])


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[FFCORulesEngine] = None


def get_engine() -> FFCORulesEngine:
    """Retourne l'instance singleton de FFCORulesEngine (chargée une seule fois)."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = FFCORulesEngine()
    return _engine_instance
