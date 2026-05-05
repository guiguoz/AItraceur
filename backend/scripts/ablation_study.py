"""
ablation_study.py — Mesure l'impact des termes E (route diversity OSM) et M (leg diversity)
sur le fitness GA.

Usage :
    cd backend
    python scripts/ablation_study.py [--n 10] [--td 3] [--circuit-type sprint]
    python scripts/ablation_study.py --benchmark data/benchmark_legs.json

Stratégie :
    Évalue le fitness d'un circuit sous 4 configurations :
      - full_low/med/high : MockRouteAnalyzer(jaccard=0.10/0.35/0.60)
      - no_E  : route_analyzer=None → Term E désactivé
      - no_M  : ablation_disable_leg_diversity=True
      - no_EM : les deux désactivés
    Delta < 2% → terme sans effet mesurable sur ce corpus.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


# ── Haversine ────────────────────────────────────────────────────────────────

def _haversine(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ── MockRouteAnalyzer ────────────────────────────────────────────────────────

class _MockGraph:
    """Graphe vide — _osm_coverage_ratio() retournera 0 → pas de couverture OSM."""
    def number_of_edges(self) -> int:
        return 0


class MockRouteAnalyzer:
    """
    Simule un RouteAnalyzer pour l'ablation study.

    count_decision_points : distance-based (~1 DP tous les 120m) — évite le biais d'un constant=1.
    route_diversity_info  : retourne le jaccard fixé à la construction.
    """
    graph = _MockGraph()

    def __init__(self, jaccard: float = 0.35):
        self._jaccard = jaccard

    def route_diversity_info(self, *args, **kwargs):
        return {"jaccard": self._jaccard, "credible_routes": 2}

    def find_optimal_route(self, *args, **kwargs):
        return []

    def count_decision_points(
        self, slng: float, slat: float, elng: float, elat: float
    ) -> int:
        dist = _haversine(slng, slat, elng, elat)
        return max(0, int(dist / 120))

    def get_decision_point_coords(self, *args, **kwargs):
        return []

    def get_cache_stats(self):
        return {"hit_rate": 0.0, "total_calls": 0, "avg_time_ms": 0.0}


# ── Chargement circuits ──────────────────────────────────────────────────────

def _load_vikazimut_circuits(index_path: Path, n: int, td: int, circuit_type: str) -> List[dict]:
    """Charge N circuits depuis vikazimut/index.json."""
    if not index_path.exists():
        print(f"[INFO] {index_path} absent — génération de circuits synthétiques")
        return []

    with open(index_path, encoding="utf-8") as f:
        all_courses = json.load(f)

    usable = [
        c for c in all_courses
        if c.get("is_foot_o")
        and c.get("controls")
        and c.get("bounds")
        and len([x for x in c.get("controls", []) if x.get("type") == "Control"]) >= 6
    ]

    if circuit_type == "sprint":
        usable = [c for c in usable if c.get("discipline") in ("urbano", "sprint")]
    elif circuit_type in ("forest", "md"):
        usable = [c for c in usable if c.get("discipline") not in ("urbano", "sprint")]

    sample = usable[:n]
    print(f"Pool Vikazimut : {len(usable)} circuits usables → {len(sample)} sélectionnés")

    circuits = []
    for course in sample:
        controls_raw = [c for c in course.get("controls", []) if c.get("type") == "Control"]
        if len(controls_raw) < 3:
            continue
        controls = [(c["lng"], c["lat"]) for c in controls_raw]
        bounds = course.get("bounds", {})
        bbox = {
            "min_x": bounds.get("west", 0),
            "min_y": bounds.get("south", 0),
            "max_x": bounds.get("east", 0),
            "max_y": bounds.get("north", 0),
        }
        circuits.append({
            "id": course.get("id"),
            "controls": controls,
            "bbox": bbox,
            "td_level": td,
            "circuit_type": circuit_type,
        })
    return circuits


def _load_benchmark_circuits(benchmark_path: Path) -> List[dict]:
    """Charge les circuits annotés depuis benchmark_legs.json."""
    with open(benchmark_path, encoding="utf-8") as f:
        data = json.load(f)

    circuits = []
    for entry in data:
        legs = entry.get("legs", [])
        if not legs:
            continue
        # Reconstituer les contrôles depuis bearing+dist n'est pas possible
        # → on skip et on avertit l'utilisateur
        print(f"[INFO] Circuit {entry['circuit_id']} : benchmark_legs.json ne contient pas "
              "les coordonnées — utiliser vikazimut/index.json pour les contrôles.")
    return circuits


def _synthetic_circuits(n: int, circuit_type: str, td: int) -> List[dict]:
    """Génère N circuits synthétiques en grille rectangulaire (fallback sans Vikazimut)."""
    circuits = []
    # Paris 48.85–48.87, 2.33–2.37 — sprint
    lat_c, lng_c = 48.860, 2.350
    step = 0.0005
    import random
    rng = random.Random(42)
    for i in range(n):
        n_ctrl = rng.randint(6, 12)
        controls = [
            (lng_c + rng.uniform(-step * 10, step * 10),
             lat_c + rng.uniform(-step * 10, step * 10))
            for _ in range(n_ctrl)
        ]
        bbox = {
            "min_x": lng_c - 0.02, "min_y": lat_c - 0.02,
            "max_x": lng_c + 0.02, "max_y": lat_c + 0.02,
        }
        circuits.append({
            "id": f"synthetic_{i}",
            "controls": controls,
            "bbox": bbox,
            "td_level": td,
            "circuit_type": circuit_type,
        })
    return circuits


# ── Évaluation ablation ──────────────────────────────────────────────────────

def _evaluate(controls: List[Tuple], bbox: dict, td: int, ct: str,
              route_analyzer=None, disable_leg_div: bool = False) -> float:
    """Évalue le fitness d'un circuit sous une configuration donnée."""
    from src.services.generation.genetic_algo import GeneticAlgorithm, GenerationConfig

    config = GenerationConfig(
        target_length_m=sum(
            _haversine(controls[i][0], controls[i][1], controls[i+1][0], controls[i+1][1])
            for i in range(len(controls) - 1)
        ),
        target_controls=max(1, len(controls) - 2),
        bounding_box=bbox,
        circuit_type=ct,
        technical_level=td,
        route_analyzer=route_analyzer,
        ablation_disable_leg_diversity=disable_leg_div,
        generations=1,       # pas de génération — on évalue un individu fixe
        population_size=1,
    )

    ga = GeneticAlgorithm(config=config)
    return ga.evaluate_fitness(controls, config)


def run_ablation(
    circuits: List[dict],
    jaccard_levels: Tuple[float, float, float] = (0.10, 0.35, 0.60),
) -> None:
    """Lance l'ablation study et affiche le rapport."""
    if not circuits:
        print("[ERREUR] Aucun circuit disponible.")
        return

    all_deltas_e = []
    all_deltas_m = []

    print(f"\n{'='*72}")
    print(f"ABLATION STUDY — {len(circuits)} circuits")
    print(f"Jaccard levels: {jaccard_levels}")
    print(f"{'='*72}\n")

    for circ in circuits:
        cid = circ["id"]
        controls = circ["controls"]
        bbox = circ["bbox"]
        td = circ["td_level"]
        ct = circ["circuit_type"]

        if len(controls) < 3:
            continue

        print(f"[{cid}] {ct} TD{td} — {len(controls)} contrôles", flush=True)

        # Config full (jaccard médian = 0.35 comme référence)
        mock_med = MockRouteAnalyzer(jaccard=jaccard_levels[1])
        score_full = _evaluate(controls, bbox, td, ct, route_analyzer=mock_med)

        # Sensibilité Term E aux 3 niveaux Jaccard
        scores_e = {}
        for jac in jaccard_levels:
            mock = MockRouteAnalyzer(jaccard=jac)
            scores_e[jac] = _evaluate(controls, bbox, td, ct, route_analyzer=mock)

        # No E
        score_no_e = _evaluate(controls, bbox, td, ct, route_analyzer=None)

        # No M (avec routeAnalyzer)
        score_no_m = _evaluate(controls, bbox, td, ct,
                                route_analyzer=mock_med, disable_leg_div=True)

        # No E + No M
        score_no_em = _evaluate(controls, bbox, td, ct,
                                 route_analyzer=None, disable_leg_div=True)

        # Calcul deltas
        def _delta(a, b) -> float:
            return (a - b) / abs(a) * 100 if abs(a) > 1e-6 else 0.0

        delta_e = _delta(score_full, score_no_e)
        delta_m = _delta(score_full, score_no_m)
        delta_em = _delta(score_full, score_no_em)

        if not math.isnan(delta_e):
            all_deltas_e.append(delta_e)
        if not math.isnan(delta_m):
            all_deltas_m.append(delta_m)

        print(f"  full(jac=0.35): {score_full:+.2f}")
        print(f"  full(jac=0.10): {scores_e[jaccard_levels[0]]:+.2f}  "
              f"full(jac=0.60): {scores_e[jaccard_levels[2]]:+.2f}")
        print(f"  no_E:    {score_no_e:+.2f}  delta_E={delta_e:+.1f}%")
        print(f"  no_M:    {score_no_m:+.2f}  delta_M={delta_m:+.1f}%")
        print(f"  no_EM:   {score_no_em:+.2f}  delta_EM={delta_em:+.1f}%")
        print()

    # ── Rapport final ────────────────────────────────────────────────────────
    print("=" * 72)
    print("RAPPORT FINAL")
    print("=" * 72)

    import statistics
    if all_deltas_e:
        mean_e = statistics.mean(all_deltas_e)
        print(f"Terme E (route diversity) — delta moyen : {mean_e:+.2f}%")
        if abs(mean_e) < 2.0:
            print("  → FAIBLE : delta < 2% — envisager de réduire W_E ou désactiver le terme")
        else:
            print("  → SIGNIFICATIF : Term E a un impact mesurable")
    else:
        print("Terme E : aucune donnée")

    if all_deltas_m:
        mean_m = statistics.mean(all_deltas_m)
        print(f"Terme M (leg diversity)   — delta moyen : {mean_m:+.2f}%")
        if abs(mean_m) < 2.0:
            print("  → FAIBLE : delta < 2% — envisager de réduire W_LEG_DIVERSITY")
        else:
            print("  → SIGNIFICATIF : Term M a un impact mesurable")
    else:
        print("Terme M : aucune donnée")

    print()
    print("Seuils de calibration à ajuster : backend/src/services/knowledge_base/placement_rules.json")
    print("  → route_choice_leg_min_m, leg_type_thresholds")
    print("Contrôleur  : backend/src/services/controleur/controleur_rules.json")
    print("  → C18.min_route_choice_legs, C19.max_handrail_ratio, C20.max_route_choice_ratio")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ablation study — impact des termes E et M sur le fitness GA"
    )
    parser.add_argument("--n", type=int, default=10,
                        help="Nombre de circuits Vikazimut (défaut: 10)")
    parser.add_argument("--td", type=int, default=3, choices=[1, 2, 3, 4, 5],
                        help="Niveau technique TD (défaut: 3)")
    parser.add_argument("--circuit-type", default="sprint",
                        choices=["sprint", "forest", "md", "ld"],
                        help="Type de circuit (défaut: sprint)")
    parser.add_argument("--benchmark",
                        help="Chemin vers benchmark_legs.json (priorité sur Vikazimut)")
    parser.add_argument("--jaccard", nargs=3, type=float, default=[0.10, 0.35, 0.60],
                        metavar=("LOW", "MED", "HIGH"),
                        help="3 niveaux Jaccard à tester (défaut: 0.10 0.35 0.60)")
    args = parser.parse_args()

    # ── Chargement circuits ──────────────────────────────────────────────────
    circuits: List[dict] = []

    if args.benchmark and Path(args.benchmark).exists():
        circuits = _load_benchmark_circuits(Path(args.benchmark))

    if not circuits:
        index_path = BACKEND_DIR.parent / "vikazimut" / "index.json"
        circuits = _load_vikazimut_circuits(index_path, args.n, args.td, args.circuit_type)

    if not circuits:
        print(f"Vikazimut absent — génération de {args.n} circuits synthétiques")
        circuits = _synthetic_circuits(args.n, args.circuit_type, args.td)

    run_ablation(circuits, jaccard_levels=tuple(args.jaccard))


if __name__ == "__main__":
    main()
