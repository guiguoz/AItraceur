# =============================================
# Algorithme génétique pour génération de circuits
# Sprint 7: Génération de circuits (Forêt)
# =============================================

import random
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime


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


@dataclass
class GenerationResult:
    """Résultat de la génération."""

    circuits: List[Circuit]
    best_circuit: Circuit
    generations_run: int
    time_elapsed_seconds: float
    config: GenerationConfig


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
        start_time = datetime.now()
        forbidden_zones = forbidden_zones or []

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

        # Boucle évolutionnaire
        for gen in range(self.config.generations):
            self.generation = gen + 1

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
        """
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
        """Effectue le croisement OX."""
        offspring = []

        for i in range(0, len(parents) - 1, 2):
            parent1 = parents[i]
            parent2 = parents[i + 1]

            if random.random() < self.config.crossover_rate:
                child1, child2 = self._ox_crossover(parent1, parent2)
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
        # 40% snap vers feature OCAD attractif le plus proche
        if random.random() < 0.40:
            cp = self._find_nearest_cp(x, y, leg_m * 2.0)
            if cp:
                x, y = cp
        if not self._is_in_forbidden_zone(x, y, forbidden_zones):
            controls[idx] = (x, y)
        return controls

    def _default_scoring(
        self,
        circuit: Circuit,
        config: GenerationConfig,
    ) -> float:
        """
        Fitness multi-objectifs IOF (6 critères pondérés).
        Remplace le scoring mono-objectif précédent.
        """
        controls = circuit.controls
        if len(controls) < 2:
            return 0.0

        total_length = self._calculate_total_length(controls)
        leg_lengths = [
            self._haversine_m(controls[i], controls[i+1])
            for i in range(len(controls) - 1)
        ]

        # --- 1. Longueur (20%) : tolérance ±15% par rapport à la cible (IOF AA12) ---
        if config.target_length_m > 0 and total_length > 0:
            ratio = total_length / config.target_length_m
            if 0.85 <= ratio <= 1.15:
                length_score = 100.0
            else:
                deviation = abs(ratio - 1.0) - 0.15
                length_score = max(0.0, 100.0 - deviation * 400)
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

        # --- 5. Équité (20%) : pas de dog-legs (<20°), séparation minimale (IOF AA16.8.1 + AA3.5.5) ---
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
                if diff < 20:
                    dog_legs += 1
        for i in range(len(controls)):
            for j in range(i + 1, len(controls)):
                d = self._haversine_m(controls[i], controls[j])
                if d < config.min_control_distance:
                    too_close += 1
        equity_score = max(0.0, 100.0 - dog_legs * 15 - too_close * 20)

        # --- 6. Sécurité (10%) : pénalité si nb postes incorrect ---
        control_diff = abs(len(controls) - config.target_controls)
        safety_score = max(0.0, 100.0 - control_diff * 10)

        # --- 7. Sprint : pénaliser les jambes > 200m (remplace la part climb en sprint) ---
        if config.sprint_mode and leg_lengths:
            max_leg_m = 200.0
            long_legs = sum(1 for l in leg_lengths if l > max_leg_m)
            sprint_leg_score = max(0.0, 100.0 - long_legs * 25)
            # En sprint, le dénivelé est négligeable — on le remplace par ce critère
            return (
                length_score  * 0.25
                + sprint_leg_score * 0.20
                + td_score    * 0.15
                + angle_score * 0.25
                + equity_score * 0.10
                + safety_score * 0.05
            )

        return (
            length_score * 0.20
            + climb_score * 0.15
            + td_score   * 0.15
            + angle_score * 0.20
            + equity_score * 0.20
            + safety_score * 0.10
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
        """Arrêt si le meilleur fitness n'a pas progressé depuis 20 générations."""
        current_best = self.population[0].fitness if self.population else 0.0
        if abs(current_best - self._last_best_fitness) < 0.01:
            self._stagnation_count += 1
        else:
            self._stagnation_count = 0
            self._last_best_fitness = current_best
        return self._stagnation_count >= 20
