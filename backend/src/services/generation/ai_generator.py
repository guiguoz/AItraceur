# =============================================
# Générateur IA de circuits
# Sprint 7: Génération de circuits (Forêt)
# =============================================

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Import conditionnel pour OpenAI
try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from .graph_builder import GraphBuilder, NavigationGraph
from .genetic_algo import GeneticAlgorithm, GenerationConfig, GenerationResult


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
    start_position: Optional[Tuple[float, float]] = None
    end_position: Optional[Tuple[float, float]] = None
    forbidden_zones: List[Dict] = field(default_factory=list)
    required_controls: List[Dict] = field(default_factory=list)
    candidate_points: List[Dict] = field(default_factory=list)  # [{x, y, isom}, ...]
    map_context: Optional[str] = None  # ISOM terrain summary from OCAD GeoJSON


@dataclass
class GeneratedCircuit:
    """Un circuit généré."""

    id: str
    controls: List[Dict]  # [{x, y, type, description}, ...]
    total_length_m: float
    total_climb_m: float
    estimated_time_minutes: float
    score: float
    generation_method: str  # "genetic", "ai", "hybrid"
    description: str = ""


# =============================================
# Prompt pour l'IA
# =============================================
CIRCUIT_GENERATION_PROMPT = """Tu es un expert en traçage de circuits de course d'orientation (CO).

Génère {num_circuits} circuit(s) avec les caractéristiques suivantes:

**Paramètres:**
- Catégorie: {category}
- Niveau technique: {technical_level}
- Longueur cible: {target_length}m
- D+ cible: {target_climb}m
- Nombre de postes: {num_controls}
- Temps gagnant: {winning_time} minutes

**Zone géographique (WGS84):**
- Emprise: min_lng={min_x}, min_lat={min_y}, max_lng={max_x}, max_lat={max_y}

**Carte OCAD — éléments présents:**
{terrain_context}

**Instructions de traçage:**
1. Place les postes sur des éléments remarquables: croisements de chemins, lisières forêt/zone ouverte, confluences de cours d'eau, dépressions, rochers
2. Exploite les chemins présents pour créer de vrais choix d'itinéraires (route directe vs chemin)
3. Alterne zones ouvertes et forêt pour varier l'engagement physique
4. Évite les interpostes trop linéaires et les postes dos à dos sans relief
5. Distance minimale entre postes: 60-80m; maximale pour ce niveau: ~500m
6. Les coordonnées x/y doivent être dans l'emprise WGS84 fournie

**Format de réponse (JSON strict):**
{{
  "circuits": [
    {{
      "id": "circuit_1",
      "controls": [
        {{"order": 1, "x": valeur_lng, "y": valeur_lat, "type": "start", "description": "description du point remarquable"}},
        {{"order": 2, "x": valeur_lng, "y": valeur_lat, "type": "control", "description": "..."}},
        {{"order": N, "x": valeur_lng, "y": valeur_lat, "type": "finish", "description": "..."}}
      ],
      "description": "explication des choix de traçage",
      "strengths": ["point fort 1", "point fort 2"]
    }}
  ]
}}

Réponds uniquement en JSON valide, sans autre texte.
"""


# =============================================
# ffco-iof-v7 — guidance ISOM pour placement terrain-aware
# =============================================
FEATURE_GUIDANCE_PROMPT = (
    "Tu es expert en traçage de CO selon les règles IOF/FFCO. "
    "Pour un circuit de catégorie {category} (longueur {length}m, niveau {td}), "
    "liste 4 à 6 types de features ISOM recommandés comme postes de contrôle. "
    'Réponds en JSON uniquement : {{"isom_types": ["depression", "rocher", "talus", ...]}}'
)

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
    """
    Génère des circuits en utilisant l'IA et l'algorithme génétique.

    Trois modes:
    - genetic: Algorithme génétique seul
    - ai: GPT seul
    - hybrid: Combinaison des deux (recommendé)
    """

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, model: str = None):
        """
        Initialise le générateur.

        Args:
            model: Modèle OpenAI à utiliser
        """
        self.model = model or self.DEFAULT_MODEL

        # Initialiser OpenAI
        if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            self.openai_client = None
            print("Attention: OPENAI_API_KEY non défini - mode génétique seul")

    def generate(
        self,
        request: GenerationRequest,
        method: str = "hybrid",
        num_variants: int = 3,
    ) -> List[GeneratedCircuit]:
        """
        Génère des circuits.

        Args:
            request: Paramètres de génération
            method: Méthode (genetic, ai, hybrid)
            num_variants: Nombre de variantes à générer

        Returns:
            Liste de circuits générés
        """
        circuits = []

        if method == "genetic":
            circuits = self._generate_genetic(request, num_variants)
        elif method == "ai":
            circuits = self._generate_ai(request, num_variants)
        elif method == "hybrid":
            # Génétiques + IA
            genetic_circuits = self._generate_genetic(request, num_variants)
            ai_circuits = self._generate_ai(request, num_variants)
            circuits = genetic_circuits + ai_circuits
        else:
            raise ValueError(f"Méthode inconnue: {method}")

        return circuits

    def _generate_genetic(
        self,
        request: GenerationRequest,
        num_variants: int,
    ) -> List[GeneratedCircuit]:
        """Génère avec l'algorithme génétique."""
        # Configuration
        config = GenerationConfig(
            target_length_m=request.target_length_m,
            target_climb_m=request.target_climb_m,
            target_controls=request.target_controls,
            winning_time_min=request.winning_time_minutes,
            population_size=30,
            generations=50,
            bounding_box=request.bounding_box,
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

        # Convertir en circuits générés
        circuits = []

        for i, circuit in enumerate(result.circuits[:num_variants]):
            controls = []
            for j, pos in enumerate(circuit.controls):
                controls.append(
                    {
                        "order": j + 1,
                        "x": pos[0],
                        "y": pos[1],
                        "type": "start"
                        if j == 0
                        else "finish"
                        if j == len(circuit.controls) - 1
                        else "control",
                        "description": f"Poste {j + 1}",
                    }
                )

            total_length = self._calculate_length(circuit.controls)

            generated = GeneratedCircuit(
                id=f"genetic_{i + 1}",
                controls=controls,
                total_length_m=total_length,
                total_climb_m=request.target_climb_m,  # Simplifié
                estimated_time_minutes=request.winning_time_minutes,
                score=circuit.fitness,
                generation_method="genetic",
                description=f"Circuit généré par algorithme génétique (génération {circuit.generation})",
            )
            circuits.append(generated)

        return circuits

    def _generate_ai(
        self,
        request: GenerationRequest,
        num_variants: int,
    ) -> List[GeneratedCircuit]:
        """Génère avec GPT."""
        if not self.openai_client:
            return []

        # Terrain context: use ISOM map summary if available, else generic fallback
        if request.map_context:
            terrain_context = request.map_context
        else:
            import math
            dx = abs(request.bounding_box["max_x"] - request.bounding_box["min_x"])
            dy = abs(request.bounding_box["max_y"] - request.bounding_box["min_y"])
            lat_c = (request.bounding_box["min_y"] + request.bounding_box["max_y"]) / 2
            w_km = round(dx * 111 * math.cos(math.radians(lat_c)), 1)
            h_km = round(dy * 111, 1)
            terrain_context = (
                f"Zone cartographiée: ~{h_km} km × {w_km} km\n"
                f"Type: Forêt mixte (données OCAD non transmises)"
            )

        # Construire le prompt
        prompt = CIRCUIT_GENERATION_PROMPT.format(
            num_circuits=num_variants,
            category=request.category,
            technical_level=request.technical_level,
            target_length=request.target_length_m,
            target_climb=request.target_climb_m,
            num_controls=request.target_controls,
            winning_time=request.winning_time_minutes,
            min_x=request.bounding_box.get("min_x", 0),
            min_y=request.bounding_box.get("min_y", 0),
            max_x=request.bounding_box.get("max_x", 0),
            max_y=request.bounding_box.get("max_y", 0),
            terrain_context=terrain_context,
        )

        try:
            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Tu es un expert en traçage de circuits de CO.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
            )

            content = response.choices[0].message.content

            # Parser le JSON
            import json

            data = json.loads(content)

            circuits = []

            for i, c in enumerate(data.get("circuits", [])):
                controls = []
                for ctrl in c.get("controls", []):
                    controls.append(
                        {
                            "order": ctrl.get("order", 0),
                            "x": ctrl.get("x", 0),
                            "y": ctrl.get("y", 0),
                            "type": ctrl.get("type", "control"),
                            "description": ctrl.get("description", ""),
                        }
                    )

                total_length = self._calculate_length(
                    [(c["x"], c["y"]) for c in controls]
                )

                generated = GeneratedCircuit(
                    id=f"ai_{i + 1}",
                    controls=controls,
                    total_length_m=total_length,
                    total_climb_m=request.target_climb_m,
                    estimated_time_minutes=request.winning_time_minutes,
                    score=85.0,  # Score estimé
                    generation_method="ai",
                    description=c.get("description", ""),
                )
                circuits.append(generated)

            return circuits

        except Exception as e:
            print(f"Erreur génération IA: {e}")
            return []

    def _calculate_length(self, controls: List[Tuple[float, float]]) -> float:
        """Calcule la longueur totale."""
        import math

        total = 0
        for i in range(len(controls) - 1):
            total += math.sqrt(
                (controls[i + 1][0] - controls[i][0]) ** 2
                + (controls[i + 1][1] - controls[i][1]) ** 2
            )
        return total


# =============================================
# Factory
# =============================================
def create_generator(openai_api_key: str = None) -> AIGenerator:
    """
    Crée un générateur configuré.

    Args:
        openai_api_key: Clé API OpenAI

    Returns:
        AIGenerator configuré
    """
    if openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key

    return AIGenerator()
