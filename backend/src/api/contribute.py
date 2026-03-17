# =============================================
# API Collecte de données ML
# POST /api/v1/contribute — dépôt anonyme
# DELETE /api/v1/contribute/{id} — RGPD
# GET /api/v1/admin/export-features — export CSV
# POST /api/v1/admin/retrain — réentraînement ML
# =============================================

import hashlib
import json
import io
import os
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.contribution import Contribution, ControlFeature
from src.services.learning.feature_extractor import FeatureExtractor

router = APIRouter()

# Clé admin simple (à mettre dans .env en production)
ADMIN_KEY = os.getenv("ADMIN_KEY", "aitraceur-admin-2026")


# =============================================
# POST /api/v1/contribute
# =============================================
@router.post("/contribute")
async def contribute(
    xml_file: UploadFile = File(..., description="Fichier IOF XML 3.0 du circuit"),
    ocd_file: Optional[UploadFile] = File(None, description="Fichier OCAD .ocd (optionnel, pour features terrain)"),
    geojson_data: Optional[str] = Form(None, description="Features terrain GeoJSON (JSON string, optionnel)"),
    circuit_type: Optional[str] = Form(None, description="sprint | middle | long"),
    map_type: Optional[str] = Form(None, description="urban | forest"),
    ffco_category: Optional[str] = Form(None, description="H21E, D16, H45, Open..."),
    climb_m: Optional[float] = Form(None),
    consent_aitraceur: bool = Form(..., description="Consentement obligatoire"),
    consent_educational: bool = Form(False, description="Partage éducatif CC BY-NC (optionnel)"),
    db: Session = Depends(get_db),
):
    """
    Reçoit un circuit contribué (XML obligatoire, OCAD optionnel).
    Extrait les features anonymisées, supprime immédiatement les fichiers bruts.

    - XML  → distances jambes, angles, TD/PD, quality_score
    - OCAD → features terrain ISOM (attractiveness, terrain_type) via ocad2geojson
    Aucune coordonnée GPS ni identifiant n'est stocké.
    """
    if not consent_aitraceur:
        raise HTTPException(status_code=400, detail="Consentement obligatoire non coché.")

    if not xml_file.filename or not xml_file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Fichier IOF XML attendu (.xml).")

    # Lire le XML en mémoire
    xml_bytes = await xml_file.read()

    # Déduplication — hash SHA256 du XML (anonyme, non réversible)
    xml_hash = hashlib.sha256(xml_bytes).hexdigest()
    existing = db.query(Contribution).filter(Contribution.xml_hash == xml_hash).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Ce fichier XML a déjà été contribué (id={existing.id}, le {existing.created_at.strftime('%Y-%m-%d')})."
        )

    # Features terrain : priorité OCD > geojson_data string
    geojson_features = None

    if ocd_file and ocd_file.filename and ocd_file.filename.lower().endswith(".ocd"):
        ocd_bytes = await ocd_file.read()
        try:
            from src.services.ocad.geojson_extractor import extract_geojson_from_ocd
            geojson_features = extract_geojson_from_ocd(ocd_bytes)
        except Exception as e:
            print(f"[OCAD] Extraction échouée (ignorée) : {e}")
        # ocd_bytes jamais écrit sur disque — suppression implicite fin de scope

    if geojson_features is None and geojson_data:
        try:
            gj = json.loads(geojson_data)
            geojson_features = gj.get("features", []) if isinstance(gj, dict) else None
        except Exception:
            geojson_features = None

    # Extraction des features (aucune coord absolue stockée)
    # Un XML peut contenir plusieurs circuits (bleu, jaune, orange...) — tous extraits
    extractor = FeatureExtractor()
    try:
        results = extractor.extract_all(
            xml_bytes=xml_bytes,
            geojson_features=geojson_features,
            circuit_type=circuit_type,
            climb_m=climb_m,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction échouée : {e}")

    results = [r for r in results if r.n_controls >= 2]
    if not results:
        raise HTTPException(status_code=422, detail="Circuit invalide ou trop court (< 2 postes).")

    contribution_ids = []
    total_controls = 0

    for result in results:
        contrib = Contribution(
            xml_hash=xml_hash,
            circuit_type=result.circuit_type,
            map_type=map_type,
            ffco_category=ffco_category,
            td_grade=result.td_grade,
            pd_grade=result.pd_grade,
            n_controls=result.n_controls,
            length_m=result.length_m,
            climb_m=result.climb_m,
            consent_educational=consent_educational,
        )
        db.add(contrib)
        db.flush()
        contribution_ids.append(contrib.id)
        total_controls += result.n_controls

        for fv in result.controls:
            cf = ControlFeature(
                contribution_id=contrib.id,
                leg_distance_m=fv.leg_distance_m,
                leg_bearing_change=fv.leg_bearing_change,
                control_position_ratio=fv.control_position_ratio,
                td_grade=fv.td_grade,
                pd_grade=fv.pd_grade,
                terrain_symbol_density=fv.terrain_symbol_density,
                nearest_path_dist_m=fv.nearest_path_dist_m,
                control_feature_type=fv.control_feature_type,
                attractiveness_score=fv.attractiveness_score,
                quality_score=fv.quality_score,
            )
            db.add(cf)

    db.commit()

    # Les fichiers bruts (xml_bytes, geojson_data) ne sont jamais écrits sur disque.
    # Ils ont été traités uniquement en mémoire — suppression implicite.

    first = results[0]
    circuits_info = [
        {
            "name": r.course_name,
            "color_detected": r.color_detected,
            "category_detected": r.category_detected,
            "n_controls": r.n_controls,
            "td_grade": r.td_grade,
            "length_m": round(r.length_m) if r.length_m else None,
        }
        for r in results
    ]
    n = len(results)
    return {
        "contribution_id": contribution_ids[0],
        "contribution_ids": contribution_ids,
        "n_circuits": n,
        "n_controls_extracted": total_controls,
        "td_grade": first.td_grade,
        "circuits": circuits_info,
        "message": f"Merci pour votre contribution ({n} circuit(s)). Vérifiez les couleurs/catégories auto-détectées.",
    }


# =============================================
# DELETE /api/v1/contribute/{contribution_id}
# Droit à l'effacement RGPD
# =============================================
@router.delete("/contribute/{contribution_id}")
def delete_contribution(
    contribution_id: int,
    db: Session = Depends(get_db),
):
    """Supprime toutes les données d'une contribution (droit à l'effacement RGPD)."""
    contrib = db.query(Contribution).filter(Contribution.id == contribution_id).first()
    if not contrib:
        raise HTTPException(status_code=404, detail="Contribution introuvable.")

    db.query(ControlFeature).filter(ControlFeature.contribution_id == contribution_id).delete()
    db.delete(contrib)
    db.commit()

    return {"deleted": contribution_id, "message": "Contribution supprimée conformément au RGPD."}


# =============================================
# GET /api/v1/admin/export-features
# Export CSV pour chercheurs (clé admin requise)
# =============================================
@router.get("/admin/export-features")
def export_features(
    admin_key: str,
    educational_only: bool = True,
    db: Session = Depends(get_db),
):
    """
    Génère un CSV zippé des features anonymisées.
    Uniquement les contributions avec consentement éducatif si educational_only=True.
    Envoi manuel par email au chercheur après vérification.
    """
    if admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Clé admin invalide.")

    query = db.query(ControlFeature, Contribution).join(
        Contribution, ControlFeature.contribution_id == Contribution.id
    )
    if educational_only:
        query = query.filter(Contribution.consent_educational == True)

    rows = query.all()
    if not rows:
        raise HTTPException(status_code=404, detail="Aucune donnée disponible.")

    # Construire le CSV en mémoire
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "circuit_type", "td_grade", "pd_grade", "n_controls",
        "leg_distance_m", "leg_bearing_change", "control_position_ratio",
        "terrain_symbol_density", "nearest_path_dist_m",
        "control_feature_type", "attractiveness_score", "quality_score",
    ])
    for cf, contrib in rows:
        writer.writerow([
            contrib.circuit_type, contrib.td_grade, contrib.pd_grade, contrib.n_controls,
            cf.leg_distance_m, cf.leg_bearing_change, cf.control_position_ratio,
            cf.terrain_symbol_density, cf.nearest_path_dist_m,
            cf.control_feature_type, cf.attractiveness_score, cf.quality_score,
        ])

    # Zipper le CSV
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("aitraceur_features.csv", buf.getvalue())
    zip_buf.seek(0)

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=aitraceur_features.zip"},
    )


# =============================================
# GET /api/v1/admin/inspect
# Diagnostic JSON des features extraites
# =============================================
@router.get("/admin/inspect")
def inspect(
    admin_key: str,
    db: Session = Depends(get_db),
):
    """Retourne un rapport JSON des features extraites — pour vérifier la qualité de l'extraction."""
    if admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Clé admin invalide.")

    import math
    contributions = db.query(Contribution).order_by(Contribution.id).all()
    if not contributions:
        return {"n_contributions": 0, "circuits": [], "summary": {}}

    circuits_out = []
    all_legs, all_angles, all_scores = [], [], []

    for contrib in contributions:
        features = (
            db.query(ControlFeature)
            .filter(ControlFeature.contribution_id == contrib.id)
            .all()
        )
        legs = [f.leg_distance_m for f in features if f.leg_distance_m is not None]
        angles = [f.leg_bearing_change for f in features if f.leg_bearing_change is not None]
        scores = [f.quality_score for f in features if f.quality_score is not None]
        dog_legs = sum(1 for a in angles if a < 25)
        terrain = sum(1 for f in features if f.attractiveness_score is not None)

        circuits_out.append({
            "id": contrib.id,
            "circuit_type": contrib.circuit_type,
            "td_grade": contrib.td_grade,
            "pd_grade": contrib.pd_grade,
            "n_controls": contrib.n_controls,
            "length_m": contrib.length_m,
            "legs": {
                "min": round(min(legs), 1) if legs else None,
                "max": round(max(legs), 1) if legs else None,
                "mean": round(sum(legs) / len(legs), 1) if legs else None,
            },
            "angles": {
                "mean": round(sum(angles) / len(angles), 1) if angles else None,
                "dog_legs": dog_legs,
                "dog_leg_pct": round(dog_legs / len(angles) * 100, 1) if angles else None,
            },
            "quality_score_mean": round(sum(scores) / len(scores), 3) if scores else None,
            "terrain_features_pct": round(terrain / max(1, len(features)) * 100, 1),
        })
        all_legs.extend(legs)
        all_angles.extend(angles)
        all_scores.extend(scores)

    summary = {
        "n_contributions": len(contributions),
        "n_control_features": len(all_legs) + len(contributions),
        "leg_distance_mean_m": round(sum(all_legs) / len(all_legs), 1) if all_legs else None,
        "angle_mean_deg": round(sum(all_angles) / len(all_angles), 1) if all_angles else None,
        "quality_score_mean": round(sum(all_scores) / len(all_scores), 3) if all_scores else None,
    }

    return {"summary": summary, "circuits": circuits_out}


# =============================================
# POST /api/v1/admin/retrain
# Déclenche le réentraînement ML
# =============================================
@router.post("/admin/retrain")
def retrain(
    admin_key: str,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """
    Déclenche le réentraînement du modèle ML.
    force=true : contourne le seuil minimum (pour tests locaux).
    """
    if admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Clé admin invalide.")

    n_contributions = db.query(Contribution).count()
    MIN_CONTRIBUTIONS = 50

    if not force and n_contributions < MIN_CONTRIBUTIONS:
        return {
            "status": "insufficient_data",
            "n_contributions": n_contributions,
            "required": MIN_CONTRIBUTIONS,
            "message": f"Il faut au moins {MIN_CONTRIBUTIONS} circuits ({n_contributions} actuellement). Ajouter ?force=true pour tester avec moins de données.",
        }

    if force and n_contributions < 3:
        return {
            "status": "insufficient_data",
            "n_contributions": n_contributions,
            "required": 3,
            "message": "Minimum absolu : 3 circuits pour entraîner (même en mode force).",
        }

    # Import tardif pour ne pas charger sklearn au démarrage si absent
    try:
        from src.services.learning.ml_trainer import MLTrainer
        trainer = MLTrainer(db)
        result = trainer.train()
        if force:
            result["warning"] = f"Modèle entraîné en mode test ({n_contributions} circuits). Les métriques ne sont pas fiables sous 50 circuits."
        return {"status": "trained", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur entraînement : {e}")
