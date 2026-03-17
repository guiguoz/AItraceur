"""
inspect_data.py — Diagnostic extraction ML d'AItraceur
=======================================================
Usage : cd backend && python inspect_data.py

Affiche un rapport lisible de toutes les contributions stockées en DB :
  - Features extraites par circuit (distances, angles, TD, score qualité)
  - Distribution globale
  - Alertes sur valeurs aberrantes
"""

import math
import sys
import os

# Ajouter le dossier backend au path
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.models.contribution import Contribution, ControlFeature


def fmt(val, unit="", decimals=1):
    if val is None:
        return "—"
    return f"{val:.{decimals}f}{unit}"


def check_ok(val, lo, hi, label):
    if val is None:
        return f"  {label}: — (aucune donnée)"
    ok = "✓" if lo <= val <= hi else "!"
    return f"  [{ok}] {label}: {val:.1f}  (attendu {lo}–{hi})"


def run():
    engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()

    contributions = db.query(Contribution).order_by(Contribution.id).all()

    if not contributions:
        print("=== AItraceur — Diagnostic extraction ML ===")
        print()
        print("Aucune contribution trouvée.")
        print()
        print("Pour uploader un XML :")
        print('  curl.exe -X POST http://localhost:8000/api/v1/contribute \\')
        print('    -F "xml_file=@mon_circuit.xml" \\')
        print('    -F "consent_aitraceur=true" \\')
        print('    -F "circuit_type=sprint"')
        return

    print("=== AItraceur — Diagnostic extraction ML ===")
    print(f"\nContributions : {len(contributions)} circuit(s)\n")

    all_legs = []
    all_angles = []
    all_scores = []
    all_dogleg_ratios = []
    all_terrain_counts = []
    warnings = []

    for contrib in contributions:
        features = (
            db.query(ControlFeature)
            .filter(ControlFeature.contribution_id == contrib.id)
            .order_by(ControlFeature.id)
            .all()
        )
        n = len(features)

        legs = [f.leg_distance_m for f in features if f.leg_distance_m is not None]
        angles = [f.leg_bearing_change for f in features if f.leg_bearing_change is not None]
        scores = [f.quality_score for f in features if f.quality_score is not None]
        terrain_count = sum(1 for f in features if f.attractiveness_score is not None)
        dog_legs = sum(1 for a in angles if a < 25)

        circuit_label = f"{contrib.circuit_type or '?'} | TD{contrib.td_grade or '?'} | {contrib.n_controls} postes | {fmt(contrib.length_m, 'm', 0)}"
        print(f"Circuit #{contrib.id} | {circuit_label}")

        if legs:
            print(f"  Jambes : min={fmt(min(legs), 'm', 0)}  max={fmt(max(legs), 'm', 0)}  moy={fmt(sum(legs)/len(legs), 'm', 0)}  ±{fmt(math.sqrt(sum((x-sum(legs)/len(legs))**2 for x in legs)/len(legs)), 'm', 0)}")
        else:
            print("  Jambes : — (premier poste = départ, pas de jambe entrante)")

        if angles:
            dog_pct = dog_legs / len(angles) * 100
            print(f"  Angles : min={fmt(min(angles), '°', 0)}  max={fmt(max(angles), '°', 0)}  moy={fmt(sum(angles)/len(angles), '°', 0)}   dog-legs={dog_legs}/{len(angles)} ({dog_pct:.0f}%)")
        else:
            print("  Angles : —")

        score_moy = sum(scores) / len(scores) if scores else None
        print(f"  Score qualité : {fmt(score_moy, '/1.0', 2)}")
        print(f"  Terrain OCAD  : {terrain_count}/{n} postes avec features GeoJSON")
        print()

        # Accumuler pour stats globales
        all_legs.extend(legs)
        all_angles.extend(angles)
        all_scores.extend(scores)
        if angles:
            all_dogleg_ratios.append(dog_legs / len(angles))
        all_terrain_counts.append(terrain_count)

        # Alertes
        if legs and max(legs) > 3000:
            warnings.append(f"Circuit #{contrib.id} : jambe max = {max(legs):.0f}m — vérifier unités XML (mm vs m ?)")
        if legs and min(legs) < 20 and len(legs) > 1:
            warnings.append(f"Circuit #{contrib.id} : jambe min = {min(legs):.0f}m — postes quasi-identiques ?")
        if angles and dog_legs / len(angles) > 0.35:
            warnings.append(f"Circuit #{contrib.id} : {dog_legs}/{len(angles)} dog-legs ({dog_legs/len(angles)*100:.0f}%) — circuit atypique ?")
        if score_moy is not None and score_moy < 0.1:
            warnings.append(f"Circuit #{contrib.id} : score qualité très bas ({score_moy:.2f}) — circuit très court ou mal formé ?")
        if contrib.td_grade == 5 and contrib.length_m and contrib.length_m < 5000:
            warnings.append(f"Circuit #{contrib.id} : TD5 mais seulement {contrib.length_m:.0f}m — TD mal détecté ?")

    # Distribution globale
    n_total = sum(len(db.query(ControlFeature).filter(ControlFeature.contribution_id == c.id).all()) for c in contributions)
    print(f"=== Distribution globale ({len(contributions)} circuits, {n_total} postes) ===")

    if all_legs:
        moy_leg = sum(all_legs) / len(all_legs)
        print(check_ok(moy_leg, 80, 600, "Distance jambe moyenne"))
    if all_angles:
        moy_angle = sum(all_angles) / len(all_angles)
        print(check_ok(moy_angle, 50, 130, "Angle moyen"))
    if all_dogleg_ratios:
        moy_dl = sum(all_dogleg_ratios) / len(all_dogleg_ratios) * 100
        ok = "✓" if moy_dl < 20 else "!"
        print(f"  [{ok}] Dog-legs moyens : {moy_dl:.1f}%  (attendu <20%)")
    if all_scores:
        moy_score = sum(all_scores) / len(all_scores)
        print(f"  Score qualité moyen : {moy_score:.2f}/1.0")
    terrain_pct = sum(all_terrain_counts) / max(1, n_total) * 100
    ok = "✓" if terrain_pct > 0 else "—"
    print(f"  [{ok}] Features OCAD : {terrain_pct:.0f}% des postes ont des données terrain")
    print()

    if warnings:
        print("=== Alertes ===")
        for w in warnings:
            print(f"  [!] {w}")
        print()
    else:
        print("=== Aucune anomalie détectée ===")
        print()

    # Conseil selon nombre de circuits
    n = len(contributions)
    print("=== Prochaine étape ===")
    if n < 5:
        print(f"  {n}/5 circuits — continue d'uploader des XMLs pour avoir un premier aperçu.")
    elif n < 10:
        print(f"  {n} circuits — tu peux tester le retrain avec force=true :")
        print("  curl.exe -X POST \"http://localhost:8000/api/v1/admin/retrain?admin_key=aitraceur-admin-2026&force=true\"")
    elif n < 50:
        print(f"  {n} circuits — le modèle commence à apprendre. R² attendu : 0.2–0.5 avec ces données.")
    else:
        print(f"  {n} circuits — lancer le retrain normal (sans force) pour entraîner le modèle complet.")

    db.close()


if __name__ == "__main__":
    run()
