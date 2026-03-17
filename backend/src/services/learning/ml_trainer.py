# =============================================
# Entraîneur ML — Random Forest
# Apprentissage depuis les contributions
# =============================================
#
# Versioning : conserve les 3 derniers modèles
# Format : backend/data/models/control_quality_YYYY-MM-DD_HH-MM.pkl
# Modèle actif : backend/data/models/latest.json (pointeur)
# =============================================

import json
import os
import glob
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from sqlalchemy.orm import Session

from src.models.contribution import ControlFeature, Contribution

# Répertoire des modèles
MODELS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "models"
LATEST_PTR = MODELS_DIR / "latest.json"
MAX_MODELS_KEPT = 3

FEATURE_COLS = [
    "leg_distance_m",
    "leg_bearing_change",
    "control_position_ratio",
    "td_grade",
    "pd_grade",
    "terrain_symbol_density",
    "nearest_path_dist_m",
    "attractiveness_score",
    # Contexte ML (encodage numérique)
    "map_type_enc",        # urban=0, forest=1
    "circuit_type_enc",    # sprint=0, middle=1, long=2
    "age_group_enc",       # âge numérique (10,12,14...80) ou 21
    "gender_enc",          # H/M=0, D/W=1, Open=2
]
LABEL_COL = "quality_score"

# Encodages constants
_MAP_TYPE_ENC = {"urban": 0, "forest": 1}
_CIRCUIT_TYPE_ENC = {"sprint": 0, "middle": 1, "long": 2, "classic": 1}


_COLOR_CATS = {"jaune", "orange", "vert", "bleu", "violet", "rouge", "marron", "blanc", "noir"}


def _encode_ffco_category(cat: Optional[str]):
    """Décode H21E, D16, H45, Open, Bleu… → (age_group, gender). Retourne (21, 0) par défaut."""
    if not cat:
        return 21, 0
    if cat.strip().lower() in _COLOR_CATS:
        return 21, 2   # Catégorie couleur — même encodage que Open
    cat = cat.strip().upper()
    if cat in ("OPEN", "MIXTE"):
        return 21, 2
    import re
    m = re.match(r'^([HDWM])(\d+)([EAB])?$', cat)
    if not m:
        return 21, 0
    gender_char = m.group(1)
    age = int(m.group(2))
    gender = 0 if gender_char in ('H', 'M') else 1
    return age, gender


class MLTrainer:
    """
    Entraîne un RandomForestRegressor sur les features ML collectées.
    Gère le versioning (3 derniers .pkl conservés).
    """

    def __init__(self, db: Session):
        self.db = db
        MODELS_DIR.mkdir(parents=True, exist_ok=True)

    def _load_data(self) -> pd.DataFrame:
        """Charge toutes les features depuis la DB en DataFrame."""
        rows = (
            self.db.query(ControlFeature, Contribution)
            .join(Contribution, ControlFeature.contribution_id == Contribution.id)
            .all()
        )
        records = []
        for cf, contrib in rows:
            age_enc, gender_enc = _encode_ffco_category(contrib.ffco_category)
            records.append({
                "leg_distance_m": cf.leg_distance_m,
                "leg_bearing_change": cf.leg_bearing_change,
                "control_position_ratio": cf.control_position_ratio,
                "td_grade": cf.td_grade or contrib.td_grade,
                "pd_grade": cf.pd_grade or contrib.pd_grade,
                "terrain_symbol_density": cf.terrain_symbol_density,
                "nearest_path_dist_m": cf.nearest_path_dist_m,
                "attractiveness_score": cf.attractiveness_score,
                "quality_score": cf.quality_score,
                # Contexte encodé
                "map_type_enc": _MAP_TYPE_ENC.get(contrib.map_type or "", 0),
                "circuit_type_enc": _CIRCUIT_TYPE_ENC.get(contrib.circuit_type or "", 0),
                "age_group_enc": age_enc,
                "gender_enc": gender_enc,
            })
        return pd.DataFrame(records)

    def train(self) -> Dict[str, Any]:
        """
        Entraîne le modèle et sauvegarde avec versioning.
        Retourne les métriques d'évaluation.
        """
        df = self._load_data()

        # Garder les lignes avec label valide
        df = df.dropna(subset=[LABEL_COL])
        if len(df) < 10:
            return {"status": "error", "message": "Données insuffisantes après nettoyage."}

        # Imputer les features manquantes par la médiane
        for col in FEATURE_COLS:
            if col in df.columns:
                df[col] = df[col].fillna(df[col].median())

        X = df[FEATURE_COLS].fillna(0)
        y = df[LABEL_COL]

        # Split train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # Entraînement
        model = RandomForestRegressor(
            n_estimators=100,
            max_depth=8,
            min_samples_leaf=3,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_train, y_train)

        # Métriques
        y_pred = model.predict(X_test)
        mae = float(mean_absolute_error(y_test, y_pred))
        r2 = float(r2_score(y_test, y_pred))

        # Feature importances
        importances = dict(zip(FEATURE_COLS, model.feature_importances_.tolist()))

        # Sauvegarder avec horodatage
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
        version = datetime.utcnow().strftime("%Y-%m-%d")
        model_path = MODELS_DIR / f"control_quality_{ts}.pkl"
        joblib.dump(model, model_path)

        # SHA256 pour vérification d'intégrité lors de la distribution
        import hashlib
        sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()

        # Mettre à jour le pointeur latest (format compatible model_updater)
        LATEST_PTR.write_text(json.dumps({
            "version": version,
            "path": str(model_path),
            "url": f"https://aitraceur.vikazim.fr/model/control_quality_{ts}.pkl",
            "sha256": sha256,
            "trained_at": ts,
            "n_samples": len(df),
            "mae": mae,
            "r2": r2,
        }))
        print(f"[ML] Modèle entraîné : v{version}, {len(df)} circuits, MAE={mae:.4f}")
        print(f"[ML] Pour distribuer : uploader {model_path.name} + latest.json sur Ionos /model/")

        # Nettoyer les anciens modèles (garder MAX_MODELS_KEPT)
        self._cleanup_old_models()

        return {
            "model_path": str(model_path),
            "n_samples": len(df),
            "mae": round(mae, 4),
            "r2": round(r2, 4),
            "feature_importances": {k: round(v, 4) for k, v in importances.items()},
        }

    def _cleanup_old_models(self):
        """Conserve uniquement les MAX_MODELS_KEPT derniers .pkl."""
        pkls = sorted(
            glob.glob(str(MODELS_DIR / "control_quality_*.pkl")),
            reverse=True,  # du plus récent au plus ancien
        )
        for old in pkls[MAX_MODELS_KEPT:]:
            try:
                os.remove(old)
            except OSError:
                pass


class MLScorer:
    """
    Charge le modèle actif et prédit un score de qualité (0–1) pour un poste.
    Fallback silencieux si le modèle n'existe pas encore.
    """

    _model: Optional[Any] = None
    _model_path: Optional[str] = None

    @classmethod
    def _load(cls):
        """Charge le modèle depuis latest.json (cache en mémoire de classe)."""
        if not LATEST_PTR.exists():
            return
        try:
            ptr = json.loads(LATEST_PTR.read_text())
            path = ptr.get("path")
            if path and path != cls._model_path and os.path.exists(path):
                cls._model = joblib.load(path)
                cls._model_path = path
        except Exception:
            cls._model = None

    @classmethod
    def predict(
        cls,
        features: Dict[str, Any],
        circuit_type: Optional[str] = None,
        map_type: Optional[str] = None,
        ffco_category: Optional[str] = None,
    ) -> Optional[float]:
        """
        Prédit un score de qualité (0–1) pour un poste.
        Passer le contexte (circuit_type, map_type, ffco_category)
        pour que la prédiction soit cohérente avec l'entraînement.
        Retourne None si le modèle n'est pas disponible.
        """
        cls._load()
        if cls._model is None:
            return None
        try:
            age_enc, gender_enc = _encode_ffco_category(ffco_category)
            ctx = {
                "map_type_enc":     _MAP_TYPE_ENC.get(map_type or "", 0),
                "circuit_type_enc": _CIRCUIT_TYPE_ENC.get(circuit_type or "", 0),
                "age_group_enc":    age_enc,
                "gender_enc":       gender_enc,
            }
            merged = {**features, **ctx}
            row = [[merged.get(col, 0) or 0 for col in FEATURE_COLS]]
            score = float(cls._model.predict(row)[0])
            return max(0.0, min(1.0, score))
        except Exception:
            return None

    @classmethod
    def is_available(cls) -> bool:
        cls._load()
        return cls._model is not None
