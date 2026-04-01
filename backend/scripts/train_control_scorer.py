"""
train_control_scorer.py — Entraînement du classificateur visuel de postes CO

Usage:
    # Phase 1 — XGBoost (rapide, CPU only)
    python train_control_scorer.py --phase xgboost

    # Phase 2 — CNN MobileNetV3-Small + export ONNX (GPU recommandé)
    python train_control_scorer.py --phase cnn --epochs 30 --batch-size 32

    # Merge RG2 + Vikazimut
    python train_control_scorer.py --phase cnn \
        --dataset-dir data/rg2/dataset \
        --extra-dataset-dir output/vikazimut_patches

    # Auto (xgboost si torch absent, sinon cnn)
    python train_control_scorer.py

Input:
    data/rg2/dataset/train/pos/*.png  (label=1)
    data/rg2/dataset/train/neg/*.png  (label=0)
    data/rg2/dataset/metadata.csv

Output:
    data/models/patch_scorer_v2.pkl         (xgboost)
    data/models/control_scorer_cnn.onnx     (cnn — inference prod)
    data/models/best_model.pth              (cnn — checkpoint PyTorch)
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from PIL import Image

# ---------------------------------------------------------------------------
# Feature extraction — source unique de vérité dans patch_feature_extractor.py
# ---------------------------------------------------------------------------
# Ajout du répertoire src/ au path pour l'import depuis scripts/
_SRC_DIR = str(Path(__file__).parents[1] / "src")
sys.path.insert(0, _SRC_DIR)
from services.learning.patch_feature_extractor import (  # noqa: E402
    ISOM_PALETTE, FEATURE_NAMES, extract_features,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s[%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker parallèle — doit être au niveau module pour Windows (spawn)
# ---------------------------------------------------------------------------

def _extract_features_worker(args: tuple[str, int, float, float, float]) -> tuple[np.ndarray, int, float] | None:
    """Extrait les features d'un patch dans un sous-processus."""
    img_path_str, label, lat, lon, weight = args
    # Réinjecter src/ dans le path du sous-processus (Windows spawn)
    import sys as _sys
    if _SRC_DIR not in _sys.path:
        _sys.path.insert(0, _SRC_DIR)
    from services.learning.patch_feature_extractor import extract_features as _ef
    from PIL import Image as _Image
    try:
        img = _Image.open(img_path_str)
        feats = _ef(img, lon, lat)
        return (feats, int(label), weight)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Phase 1 — XGBoost
# ---------------------------------------------------------------------------

def _load_dataset_features(
    metadata_csv: Path, dataset_dir: Path
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load patches, extract ISOM features en parallèle, return (X, y, w)."""
    df = pd.read_csv(metadata_csv)

    # --- FIX RÉTROCOMPATIBILITÉ ANCIEN DATASET ---
    if "lat" not in df.columns:
        df["lat"] = 0.0
    if "lon" not in df.columns:
        df["lon"] = 0.0
    # ---------------------------------------------

    df = df.dropna(subset=["img_path", "label", "lat", "lon"])
    df = df.drop_duplicates(subset=["img_path"])
    df["label"] = df["label"].astype(int)

    if "course_type" in df.columns:
        df["_weight"] = np.where(df["course_type"] == "sprint", 2.0, 1.0)
    else:
        df["_weight"] = 1.0

    # Filtrage vectorisé des fichiers existants
    df["_abs"] = df["img_path"].apply(lambda p: str(dataset_dir / p))
    df = df[df["_abs"].apply(os.path.exists)].reset_index(drop=True)

    n_pos = int((df["label"] == 1).sum())
    n_neg = int((df["label"] == 0).sum())
    log.info("Dataset: %d unique patches (%d pos, %d neg)", len(df), n_pos, n_neg)

    rows: list[tuple[str, int, float, float, float]] = list(zip(
        df["_abs"], df["label"], df["lat"], df["lon"], df["_weight"]
    ))
    n_workers = multiprocessing.cpu_count()
    log.info("Extraction parallèle — %d workers, chunksize=500…", n_workers)

    X_rows: list[np.ndarray] = []
    y_rows: list[int] = []
    w_rows: list[float] =[]
    skipped = 0
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        for i, result in enumerate(executor.map(_extract_features_worker, rows, chunksize=500)):
            if result is not None:
                feats, label, weight = result
                X_rows.append(feats)
                y_rows.append(label)
                w_rows.append(weight)
            else:
                skipped += 1

            if (i + 1) % 10_000 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                remaining = (len(rows) - i - 1) / max(rate, 1)
                log.info("  %d/%d — %.0f patch/s — %.1f min restant",
                         i + 1, len(rows), rate, remaining / 60)

    if skipped:
        log.warning("Skipped %d patches (fichier corrompu ou manquant)", skipped)

    return np.array(X_rows, dtype=np.float32), np.array(y_rows, dtype=np.int32), np.array(w_rows, dtype=np.float32)


def train_xgboost(dataset_dir: Path, output_dir: Path, output_name: str = "patch_scorer_v2") -> Path:
    """Phase 1 — XGBoost sur 17 features enrichies (ISOM global+centre + Edge/Corner/Entropy)."""
    try:
        from xgboost import XGBClassifier
    except ImportError:
        log.error("xgboost not installed. Run: pip install xgboost")
        sys.exit(1)

    from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score
    from sklearn.model_selection import train_test_split
    import joblib

    metadata_csv = dataset_dir / "metadata.csv"
    if not metadata_csv.exists():
        log.error("metadata.csv not found at %s", metadata_csv)
        sys.exit(1)

    log.info("=== Phase 1 — XGBoost v2 (18 features) ===")
    log.info("Extracting features from patches (ISOM global+centre + Edge/Corner/Entropy + Urban)...")
    t0 = time.time()
    X, y, w = _load_dataset_features(metadata_csv, dataset_dir)
    log.info("Feature extraction done in %.1fs — X shape: %s", time.time() - t0, X.shape)

    assert X.shape[1] == 18, f"Erreur : dimension inattendue pour X. Attendue: 18, Obtenue: {X.shape[1]}"

    if len(X) < 50:
        log.error("Not enough patches (%d). Run scrape_rg2.py --generate-dataset first.", len(X))
        sys.exit(1)

    n_pos = y.sum()
    n_neg = len(y) - n_pos
    scale_pos_weight = n_neg / max(n_pos, 1)
    log.info("Class balance: %d pos / %d neg → scale_pos_weight=%.2f", n_pos, n_neg, scale_pos_weight)

    X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
        X, y, w, test_size=0.2, random_state=42, stratify=y
    )

    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )

    log.info("Training XGBoost (n_estimators=300, max_depth=6)...")
    t0 = time.time()
    model.fit(
        X_train, y_train,
        sample_weight=w_train,
        eval_set=[(X_val, y_val)],
        sample_weight_eval_set=[w_val],
        verbose=50,
    )
    log.info("Training done in %.1fs", time.time() - t0)

    # Metrics
    y_pred = model.predict(X_val)
    y_prob = model.predict_proba(X_val)[:, 1]

    auc = roc_auc_score(y_val, y_prob)
    f1 = f1_score(y_val, y_pred)
    prec = precision_score(y_val, y_pred)
    rec = recall_score(y_val, y_pred)

    log.info("=== Validation metrics ===")
    log.info("  AUC-ROC  : %.4f", auc)
    log.info("  F1       : %.4f", f1)
    log.info("  Precision: %.4f", prec)
    log.info("  Recall   : %.4f", rec)

    # Feature importance
    log.info("Feature importances:")
    for name, imp in sorted(zip(FEATURE_NAMES, model.feature_importances_),
                             key=lambda x: -x[1]):
        log.info("  %-20s %.4f", name, imp)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{output_name}.pkl"
    joblib.dump(model, out_path)
    log.info("Model saved: %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Phase 2 — CNN ResNet18 (PyTorch)
# ---------------------------------------------------------------------------

# Globals partagés avec ControlPatchDataset (nécessaire pour multiprocessing Windows)
_DATASET_IN_CHANNELS: int = 3
_DATASET_SRTM_DATA = None
_DATASET_MEAN_3CH = [0.485, 0.456, 0.406]
_DATASET_STD_3CH  = [0.229, 0.224, 0.225]
_DATASET_MEAN_5CH = [0.485, 0.456, 0.406, 0.5,  0.1 ]
_DATASET_STD_5CH  = [0.229, 0.224, 0.225, 0.25, 0.15]


class ControlPatchDataset:
    """Dataset patches CO — picklable pour multiprocessing Windows (num_workers>0)."""

    def __init__(self, df: pd.DataFrame, transform=None):
        self.df = df.reset_index(drop=True)
        self.transform = transform

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, idx: int):
        import torch
        from torchvision import transforms as _transforms
        row = self.df.iloc[idx]
        img = Image.open(row["img_path"]).convert("RGB")
        label = float(row["label"])

        if _DATASET_IN_CHANNELS == 5 and _DATASET_SRTM_DATA is not None:
            lat   = float(row.get("lat",   0.0) or 0.0)
            lon   = float(row.get("lon",   0.0) or 0.0)
            fov_m = float(row.get("fov_m", 128.0) or 128.0)
            if self.transform:
                rgb_t = self.transform(img)
            else:
                rgb_t = _transforms.Compose([
                    _transforms.Resize((224, 224), interpolation=_transforms.InterpolationMode.BILINEAR),
                    _transforms.ToTensor(),
                    _transforms.Normalize(mean=_DATASET_MEAN_3CH, std=_DATASET_STD_3CH),
                ])(img)
            if lat != 0.0 and lon != 0.0:
                elev, slope = _get_dem_channels_fast(lat, lon, fov_m, _DATASET_SRTM_DATA)
            else:
                elev = slope = np.zeros((224, 224), dtype=np.float32)
            elev_n  = (elev  - _DATASET_MEAN_5CH[3]) / _DATASET_STD_5CH[3]
            slope_n = (slope - _DATASET_MEAN_5CH[4]) / _DATASET_STD_5CH[4]
            dem_t = torch.from_numpy(np.stack([elev_n, slope_n], axis=0).astype(np.float32))
            tensor = torch.cat([rgb_t, dem_t], dim=0)
        else:
            if self.transform:
                tensor = self.transform(img)
            else:
                tensor = _transforms.Compose([
                    _transforms.Resize((224, 224), interpolation=_transforms.InterpolationMode.BILINEAR),
                    _transforms.ToTensor(),
                    _transforms.Normalize(mean=_DATASET_MEAN_3CH, std=_DATASET_STD_3CH),
                ])(img)
        return tensor, torch.tensor(label, dtype=torch.float32)


def _get_dem_channels_fast(lat: float, lon: float, fov_m: float,
                           srtm_data: object, out_px: int = 224):
    """
    Retourne (elev_norm, slope_norm) float32 (out_px, out_px).

    Stratégie vectorisée : grille 16×16 d'appels SRTM puis resize bilinéaire.
    Coût : ~256 appels au lieu de 224×224.
    """
    import math as _math
    half_lat = (fov_m / 2.0) / 111320.0
    half_lon = (fov_m / 2.0) / (111320.0 * _math.cos(_math.radians(lat)))
    SAMPLE = 16
    lats = np.linspace(lat + half_lat, lat - half_lat, SAMPLE)
    lons = np.linspace(lon - half_lon, lon + half_lon, SAMPLE)
    grid = np.zeros((SAMPLE, SAMPLE), dtype=np.float32)
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            try:
                grid[i, j] = srtm_data.get_elevation(la, lo) or 0.0
            except (ValueError, Exception):
                grid[i, j] = 0.0
    grid_img = Image.fromarray(grid).resize((out_px, out_px), Image.BILINEAR)
    elev = np.array(grid_img, dtype=np.float32)
    elev_norm = np.clip(elev / 3000.0, 0.0, 1.0)
    gy, gx = np.gradient(elev)
    cell_m = 30.0 * out_px / SAMPLE
    slope_deg = np.degrees(np.arctan(np.sqrt(gx**2 + gy**2) / cell_m))
    slope_norm = np.clip(slope_deg / 45.0, 0.0, 1.0)
    return elev_norm, slope_norm


def train_cnn(
    dataset_dir: Path,
    output_dir: Path,
    epochs: int = 30,
    batch_size: int = 32,
    extra_dataset_dirs: Optional[list] = None,
    resume: bool = False,
) -> Path:
    """Phase 2 — MobileNetV3-Small 5 canaux (RGB+DEM) fine-tuning + export ONNX."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
        from torchvision import models, transforms
        from sklearn.metrics import f1_score, recall_score
    except ImportError as e:
        log.error("Missing package: %s. Run: pip install torch torchvision", e)
        sys.exit(1)

    # Chargement SRTM (facultatif — fallback 3 canaux si absent)
    global _DATASET_SRTM_DATA, _DATASET_IN_CHANNELS
    try:
        import srtm  # type: ignore[import]
        import tempfile as _tmpmod
        _srtm_cache = _tmpmod.gettempdir() + "/srtm_cache"
        import os as _os; _os.makedirs(_srtm_cache, exist_ok=True)
        _DATASET_SRTM_DATA = srtm.SrtmService(data_dir=_srtm_cache)
        log.info("SRTM chargé — entraînement 5 canaux (RGB + altitude + pente)")
    except ImportError:
        log.warning("srtm.py absent (pip install srtm.py) — entraînement 3 canaux RGB uniquement")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("=== Phase 2 — CNN MobileNetV3-Small + ONNX === (device: %s)", device)

    # ------------------------------------------------------------------
    # Dataset — supporte les chemins absolus (merge multi-datasets)
    # ------------------------------------------------------------------
    _DATASET_IN_CHANNELS = 5 if _DATASET_SRTM_DATA is not None else 3
    IN_CHANNELS = _DATASET_IN_CHANNELS  # alias local pour build_model

    # ControlPatchDataset définie au niveau module (requis pour multiprocessing Windows)

    # Augmentation — cartes CO rotation-invariantes + resize 224 pour MobileNetV3
    # NOTE : ColorJitter uniquement sur RGB (appliqué avant concat DEM)
    train_transform = transforms.Compose([
        transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.RandomApply([transforms.RandomRotation(degrees=(90, 90))], p=0.33),
        transforms.RandomApply([transforms.RandomRotation(degrees=(180, 180))], p=0.33),
        transforms.RandomApply([transforms.RandomRotation(degrees=(270, 270))], p=0.33),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
        transforms.ToTensor(),
        transforms.Normalize(mean=_DATASET_MEAN_3CH, std=_DATASET_STD_3CH),
    ])

    val_transform = transforms.Compose([
        transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.ToTensor(),
        transforms.Normalize(mean=_DATASET_MEAN_3CH, std=_DATASET_STD_3CH),
    ])

    # ------------------------------------------------------------------
    # Chargement + merge datasets (RG2 + Vikazimut éventuellement)
    # ------------------------------------------------------------------
    def _load_csv(ddir: Path) -> pd.DataFrame:
        csv = ddir / "metadata.csv"
        if not csv.exists():
            log.error("metadata.csv non trouvé : %s", csv)
            sys.exit(1)
        _df = pd.read_csv(csv)
        if "lat" not in _df.columns:
            _df["lat"] = 0.0
        if "lon" not in _df.columns:
            _df["lon"] = 0.0
        _df = _df.dropna(subset=["img_path", "label"])
        _df = _df.drop_duplicates(subset=["img_path"])
        _df["label"] = _df["label"].astype(int)
        # Résoudre les chemins relatifs en absolus (nécessaire pour merge)
        _df["img_path"] = _df["img_path"].apply(
            lambda p: str(ddir / p) if not Path(p).is_absolute() else p
        )
        # Filtrer les patches inexistants
        _df = _df[_df["img_path"].apply(lambda p: Path(p).exists())]
        log.info("  %s : %d patches (%d pos, %d neg)",
                 ddir.name, len(_df), (_df["label"] == 1).sum(), (_df["label"] == 0).sum())
        return _df

    all_dfs = [_load_csv(dataset_dir)]
    for extra in (extra_dataset_dirs or []):
        all_dfs.append(_load_csv(Path(extra)))

    df = pd.concat(all_dfs, ignore_index=True)
    log.info("Dataset fusionné : %d patches (%d pos, %d neg)",
             len(df), (df["label"] == 1).sum(), (df["label"] == 0).sum())

    if len(df) < 100:
        log.error("Pas assez de patches (%d).", len(df))
        sys.exit(1)

    # Stratified split
    from sklearn.model_selection import train_test_split
    df_train, df_val = train_test_split(df, test_size=0.2, random_state=42, stratify=df["label"])

    train_ds = ControlPatchDataset(df_train, transform=train_transform)
    val_ds = ControlPatchDataset(df_val, transform=val_transform)

    # Weighted sampler to handle class imbalance during training
    n_pos = (df_train["label"] == 1).sum()
    n_neg = (df_train["label"] == 0).sum()
    class_weights = {1: n_neg / n_pos, 0: 1.0}
    sample_weights =[class_weights[int(lbl)] for lbl in df_train["label"]]
    sampler = WeightedRandomSampler(sample_weights, num_samples=len(sample_weights), replacement=True)

    train_loader = DataLoader(train_ds, batch_size=batch_size, sampler=sampler,
                              num_workers=4, pin_memory=(device.type == "cuda"),
                              persistent_workers=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=4, pin_memory=(device.type == "cuda"),
                            persistent_workers=True)

    # ------------------------------------------------------------------
    # Model — MobileNetV3-Small, dégeler features[-2:] + classifier
    # ------------------------------------------------------------------
    def build_model() -> nn.Module:
        model = models.mobilenet_v3_small(
            weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        )
        if IN_CHANNELS != 3:
            # Remplacer le 1er conv (3→16) par (IN_CHANNELS→16), initialiser les poids DEM
            old_conv = model.features[0][0]
            new_conv = nn.Conv2d(
                IN_CHANNELS, old_conv.out_channels,
                kernel_size=old_conv.kernel_size, stride=old_conv.stride,
                padding=old_conv.padding, bias=False,
            )
            with torch.no_grad():
                new_conv.weight[:, :3] = old_conv.weight
                # Canaux DEM initialisés à la moyenne des poids RGB (transfert doux)
                mean_rgb = old_conv.weight.mean(dim=1, keepdim=True)
                for c in range(3, IN_CHANNELS):
                    new_conv.weight[:, c:c+1] = mean_rgb
            model.features[0][0] = new_conv
        # Geler tout
        for param in model.parameters():
            param.requires_grad = False
        # Dégeler les 2 derniers blocs features + classifier (+ 1er conv si 5ch)
        unfreeze = (list(model.features[-2].parameters()) +
                    list(model.features[-1].parameters()) +
                    list(model.classifier.parameters()))
        if IN_CHANNELS != 3:
            unfreeze += list(model.features[0].parameters())
        for param in unfreeze:
            param.requires_grad = True
        # Remplacer la tête (1000 classes → 1 sortie binaire)
        model.classifier[3] = nn.Linear(1024, 1)
        return model

    model = build_model().to(device)

    # ------------------------------------------------------------------
    # Loss, optimizer, scheduler
    # ------------------------------------------------------------------
    pos_weight = torch.tensor([n_neg / max(n_pos, 1)], dtype=torch.float32).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()), lr=1e-4
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", patience=3, factor=0.5
    )

    # ------------------------------------------------------------------
    # Resume support
    # ------------------------------------------------------------------
    resume_path = output_dir / "checkpoint_resume.pth"
    start_epoch = 1
    best_val_loss_resume = float("inf")
    history_resume: list = []
    if resume and resume_path.exists():
        ckpt = torch.load(resume_path, map_location=device)
        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        scheduler.load_state_dict(ckpt["scheduler"])
        start_epoch = ckpt["epoch"] + 1
        best_val_loss_resume = ckpt.get("best_val_loss", float("inf"))
        history_resume = ckpt.get("history", [])
        log.info("Reprise depuis epoch %d (best_val_loss=%.4f)", start_epoch, best_val_loss_resume)
    elif resume:
        log.warning("--resume demandé mais checkpoint_resume.pth introuvable — démarrage from scratch")

    # ------------------------------------------------------------------
    # Training loop
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    best_path = output_dir / "best_model.pth"
    best_val_loss = best_val_loss_resume
    history = history_resume

    log.info("Training for %d epochs (train=%d val=%d batch=%d)...",
             epochs, len(train_ds), len(val_ds), batch_size)

    for epoch in range(start_epoch, epochs + 1):
        # --- Train ---
        model.train()
        train_loss = 0.0
        for imgs, labels in train_loader:
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad()
            logits = model(imgs).squeeze(1)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(imgs)
        train_loss /= len(train_ds)

        # --- Validate ---
        model.eval()
        val_loss = 0.0
        all_preds, all_probs, all_labels = [], [], []
        with torch.no_grad():
            for imgs, labels in val_loader:
                imgs, labels = imgs.to(device), labels.to(device)
                logits = model(imgs).squeeze(1)
                loss = criterion(logits, labels)
                val_loss += loss.item() * len(imgs)
                probs = torch.sigmoid(logits).cpu().numpy()
                preds = (probs >= 0.5).astype(int)
                all_probs.extend(probs)
                all_preds.extend(preds)
                all_labels.extend(labels.cpu().numpy().astype(int))
        val_loss /= len(val_ds)

        acc = np.mean(np.array(all_preds) == np.array(all_labels))
        f1 = f1_score(all_labels, all_preds, zero_division=0)
        rec = recall_score(all_labels, all_preds, zero_division=0)

        log.info(
            "Epoch %2d/%d | train_loss=%.4f val_loss=%.4f acc=%.3f F1=%.3f Recall=%.3f",
            epoch, epochs, train_loss, val_loss, acc, f1, rec,
        )
        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss,
                        "acc": acc, "f1": f1, "recall": rec})

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), best_path)
            log.info("  → Best model saved (val_loss=%.4f)", val_loss)

        # Checkpoint resume après chaque epoch
        torch.save({
            "epoch": epoch,
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "best_val_loss": best_val_loss,
            "history": history,
        }, resume_path)
        log.info("  → Checkpoint saved (epoch %d)", epoch)

    # Save final model (checkpoint PyTorch)
    out_path = output_dir / "control_scorer_cnn.pt"
    torch.save(model.state_dict(), out_path)
    log.info("Final model saved: %s", out_path)
    log.info("Best model saved : %s", best_path)

    # Training summary
    best_epoch = min(history, key=lambda r: r["val_loss"])
    log.info("=== Training summary ===")
    log.info("  Best epoch     : %d", best_epoch["epoch"])
    log.info("  Best val_loss  : %.4f", best_epoch["val_loss"])
    log.info("  Best F1        : %.4f", best_epoch["f1"])
    log.info("  Best Recall    : %.4f", best_epoch["recall"])

    # ------------------------------------------------------------------
    # Export ONNX depuis le meilleur checkpoint
    # ------------------------------------------------------------------
    best_model = build_model().to(device)
    best_model.load_state_dict(torch.load(best_path, map_location=device))
    best_model.eval()

    onnx_path = output_dir / "control_scorer_cnn.onnx"
    dummy = torch.randn(1, IN_CHANNELS, 224, 224, device=device)
    torch.onnx.export(
        best_model,
        dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=12,
    )
    log.info("ONNX exporté : %s  (%d canaux, prod inference via onnxruntime)", onnx_path, IN_CHANNELS)

    return onnx_path


# ---------------------------------------------------------------------------
# Inference helper (used by Phase C scorer.py)
# ---------------------------------------------------------------------------

def score_patch_xgboost(img: Image.Image, lng: float, lat: float, model_path: Path) -> float:
    """Score a 256×256 patch with the XGBoost model. Returns probability[0..1]."""
    import joblib
    model = joblib.load(model_path)
    feats = extract_features(img, lng, lat).reshape(1, -1)
    return float(model.predict_proba(feats)[0, 1])


def score_patch_cnn(img: Image.Image, model_path: Path) -> float:
    """Score a patch with the MobileNetV3-Small model (.pt). Returns probability [0..1]."""
    import torch
    import torch.nn as nn
    from torchvision import models, transforms

    transform = transforms.Compose([
        transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    net = models.mobilenet_v3_small(weights=None)
    net.classifier[3] = nn.Linear(1024, 1)
    net.load_state_dict(torch.load(model_path, map_location="cpu"))
    net.eval()

    tensor = transform(img.convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        logit = net(tensor).squeeze()
        return float(torch.sigmoid(logit).item())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_paths(dataset_dir_arg: Optional[str], output_dir_arg: Optional[str]):
    """Resolve dataset and output dirs relative to this script's location."""
    script_dir = Path(__file__).parent
    backend_dir = script_dir.parent

    if dataset_dir_arg:
        dataset_dir = Path(dataset_dir_arg)
    else:
        dataset_dir = backend_dir / "data" / "rg2" / "dataset"

    if output_dir_arg:
        output_dir = Path(output_dir_arg)
    else:
        output_dir = backend_dir / "data" / "models"

    return dataset_dir, output_dir


def main():
    parser = argparse.ArgumentParser(
        description="Train visual control placement scorer for AItraceur",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--phase",
        choices=["auto", "xgboost", "cnn"],
        default="auto",
        help="Training phase: auto selects xgboost if torch is absent (default: auto)",
    )
    parser.add_argument(
        "--dataset-dir",
        default=None,
        help="Path to dataset dir containing metadata.csv and train/pos, train/neg folders",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Where to save trained models (default: ../data/models)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=30,
        help="CNN: number of training epochs (default: 30)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="CNN: batch size (default: 32)",
    )
    parser.add_argument(
        "--output",
        default="patch_scorer_v2",
        help="Nom du fichier modèle sans extension (default: patch_scorer_v2)",
    )
    parser.add_argument(
        "--extra-dataset-dir",
        default=None,
        help="Dataset supplémentaire à fusionner (ex: output/vikazimut_patches)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reprendre depuis checkpoint_resume.pth si disponible",
    )
    args = parser.parse_args()

    dataset_dir, output_dir = _resolve_paths(args.dataset_dir, args.output_dir)

    log.info("Dataset dir : %s", dataset_dir)
    log.info("Output dir  : %s", output_dir)

    phase = args.phase
    if phase == "auto":
        try:
            import torch  # noqa: F401
            phase = "cnn"
            log.info("torch found → CNN MobileNetV3-Small + ONNX export")
        except ImportError:
            phase = "xgboost"
            log.info("torch non trouvé → XGBoost baseline")

    extra_dirs = [Path(args.extra_dataset_dir)] if args.extra_dataset_dir else None

    if phase == "xgboost":
        train_xgboost(dataset_dir, output_dir, output_name=args.output)
    else:
        train_cnn(dataset_dir, output_dir, epochs=args.epochs, batch_size=args.batch_size,
                  extra_dataset_dirs=extra_dirs, resume=args.resume)


if __name__ == "__main__":
    main()