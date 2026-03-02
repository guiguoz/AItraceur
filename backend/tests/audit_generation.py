"""
Audit de génération - AItraceur
Génère 3 circuits test et les score directement (sans serveur HTTP).
Usage : cd backend && python tests/audit_generation.py
"""

import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.generation.ai_generator import AIGenerator, GenerationRequest
from src.services.generation.scorer import CircuitScorer

# ══════════════════════════════════════════════════════
# 3 configurations de test (WGS84, zone ~49.19°N 5.50°E)
# ══════════════════════════════════════════════════════
CONFIGS = [
    {
        # Sprint : 2km, 8 postes → jambes ~286m → bbox ~700m×700m
        # 0.010° lng ≈ 726m,  0.006° lat ≈ 667m  (à 49°N)
        "name": "Sprint TD2",
        "category": "D21",
        "technical_level": "TD2",
        "target_length_m": 2000,
        "target_climb_m": 60,
        "target_controls": 8,
        "winning_time_minutes": 15,
        "bounding_box": {
            "min_x": 5.495, "min_y": 49.187,
            "max_x": 5.505, "max_y": 49.193,
        },
    },
    {
        # Classique : 4km, 12 postes → jambes ~364m → bbox ~1.2km×1km
        # 0.017° lng ≈ 1234m,  0.010° lat ≈ 1110m
        "name": "Classique TD3",
        "category": "H21",
        "technical_level": "TD3",
        "target_length_m": 4000,
        "target_climb_m": 150,
        "target_controls": 12,
        "winning_time_minutes": 30,
        "bounding_box": {
            "min_x": 5.491, "min_y": 49.185,
            "max_x": 5.508, "max_y": 49.195,
        },
    },
    {
        # Long : 7km, 15 postes → jambes ~500m → bbox ~2km×1.8km
        # 0.028° lng ≈ 2033m,  0.016° lat ≈ 1776m
        "name": "Long TD4",
        "category": "H21E",
        "technical_level": "TD4",
        "target_length_m": 7000,
        "target_climb_m": 300,
        "target_controls": 15,
        "winning_time_minutes": 50,
        "bounding_box": {
            "min_x": 5.486, "min_y": 49.182,
            "max_x": 5.514, "max_y": 49.198,
        },
    },
]


def run_audit():
    print("\n" + "=" * 55)
    print(f"  Audit Generation AItraceur -- {date.today()}")
    print("=" * 55)

    gen = AIGenerator()
    scorer = CircuitScorer()

    all_scores = []
    results = []

    for i, cfg in enumerate(CONFIGS, 1):
        cible_km = cfg["target_length_m"] / 1000
        print(f"\nCircuit {i} : {cfg['name']} ({cible_km:.0f}km, {cfg['target_controls']} postes)")
        print("  Generation en cours...")

        request = GenerationRequest(
            bounding_box=cfg["bounding_box"],
            category=cfg["category"],
            technical_level=cfg["technical_level"],
            target_length_m=cfg["target_length_m"],
            target_climb_m=cfg["target_climb_m"],
            target_controls=cfg["target_controls"],
            winning_time_minutes=cfg["winning_time_minutes"],
        )

        try:
            circuits = gen.generate(request, method="genetic", num_variants=1)
            if not circuits:
                print("  [ERREUR] Aucun circuit genere")
                continue

            circuit = circuits[0]
            controls = circuit.controls

            score_result = scorer.score(
                controls,
                target_length=cfg["target_length_m"],
                target_climb=cfg["target_climb_m"],
                category=cfg["category"],
            )

            all_scores.append(score_result.total_score)

            ecart = (circuit.total_length_m - cfg["target_length_m"]) / cfg["target_length_m"] * 100
            ecart_str = f"+{ecart:.1f}%" if ecart >= 0 else f"{ecart:.1f}%"

            print(f"  Score global   : {score_result.total_score:.1f} / 100  [{score_result.grade}]")
            print(f"  TD : {score_result.iof.td_label:<27} PD : {score_result.iof.pd_label}")
            print(f"  Longueur       : {circuit.total_length_m:.0f}m  (cible {cfg['target_length_m']}m, ecart {ecart_str})")
            print(f"  Postes generes : {len(controls)}  (cible {cfg['target_controls']})")
            print(f"  Dog-legs       : {score_result.iof.dog_legs:<5}          Trop proches : {score_result.iof.too_close_controls}")
            print(f"  IOF valide     : {'OK' if score_result.iof.iof_valid else 'NON'}")

            if score_result.strengths:
                print(f"  Points forts   : {', '.join(score_result.strengths[:2])}")
            if score_result.suggestions:
                print(f"  A ameliorer    : {score_result.suggestions[0]}")

            results.append({
                "name": cfg["name"],
                "score": score_result.total_score,
                "grade": score_result.grade,
                "td": score_result.iof.td_label,
                "pd": score_result.iof.pd_label,
                "iof_valid": score_result.iof.iof_valid,
                "dog_legs": score_result.iof.dog_legs,
                "too_close": score_result.iof.too_close_controls,
                "length": circuit.total_length_m,
                "target_length": cfg["target_length_m"],
                "suggestions": score_result.suggestions,
                "breakdown": score_result.breakdown,
            })

        except Exception as e:
            print(f"  [ERREUR] {e}")
            import traceback
            traceback.print_exc()

    # ── Conclusions ──
    print("\n" + "=" * 55)
    print("  Conclusions")
    print("=" * 55)

    if all_scores:
        avg = sum(all_scores) / len(all_scores)
        print(f"  Score moyen    : {avg:.1f} / 100")

        dog_leg_total = sum(r["dog_legs"] for r in results)
        too_close_total = sum(r["too_close"] for r in results)
        invalid_count = sum(1 for r in results if not r["iof_valid"])

        if dog_leg_total > 0:
            print(f"  [!] Dog-legs     : {dog_leg_total} au total (postes consecutifs en ligne droite)")
        if too_close_total > 0:
            print(f"  [!] Trop proches : {too_close_total} paires de postes < 60m")
        if invalid_count > 0:
            print(f"  [!] Non-conformes IOF : {invalid_count}/{len(results)} circuits")

        if results:
            print("\n  Detail des sous-scores (moyenne) :")
            bd_fields = ["length_score", "variety_score", "balance_score",
                         "control_distance_score", "climb_score", "safety_score"]
            for field in bd_fields:
                vals = [getattr(r["breakdown"], field, 0) for r in results]
                avg_val = sum(vals) / len(vals)
                bar = "#" * int(avg_val / 5)
                print(f"    {field:<25} : {avg_val:5.1f}  {bar}")

        all_suggestions = []
        for r in results:
            for s in r.get("suggestions", []):
                if s not in all_suggestions:
                    all_suggestions.append(s)

        if all_suggestions:
            print(f"\n  Suggestions prioritaires :")
            for s in all_suggestions[:4]:
                print(f"    - {s}")

    print("")
    return results


if __name__ == "__main__":
    run_audit()
