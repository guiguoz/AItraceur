"""
train_control_scorer_kaggle.py — CNN MobileNetV3-Small pour Kaggle
Optimisé pour GPU T4 avec données RG2 + Vikazimut

Usage (depuis Kaggle notebook) :
    exec(open('/kaggle/working/train_control_scorer_kaggle.py').read())
    onnx_path = train_cnn_kaggle()
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from torchvision import models, transforms
from sklearn.metrics import f1_score, recall_score
from sklearn.model_selection import train_test_split
from tqdm.auto import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s[%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# =============================================================================
# Feature extraction — Simplifié pour Kaggle (sans ISOM)
# =============================================================================

def extract_features_simple(img: Image.Image) -> np.ndarray:
    """
    Extracteur 18-dim simplifié pour Kaggle.
    Utilisé UNIQUEMENT pour XGBoost fallback (CNN = end-to-end RGB).
    """
    arr = np.array(img.convert('RGB'), dtype=np.float32) / 255.0
    h, w = arr.shape[:2]

    # Global mean per channel
    global_mean = arr.reshape(-1, 3).mean(axis=0)

    # Center crop mean
    cy1, cy2 = h // 4, 3 * h // 4
    cx1, cx2 = w // 4, 3 * w // 4
    center_mean = arr[cy1:cy2, cx1:cx2].reshape(-1, 3).mean(axis=0)

    # Edge detection (Sobel X/Y)
    gy = arr[1:, :] - arr[:-1, :]
    gx = arr[:, 1:] - arr[:, :-1]
    edge_mag = np.sqrt(gx[:, :-1] ** 2 + gy[:-1, :] ** 2).mean()

    # Corner detection (Harris corner strength)
    corner_str = (gx[:, :-1] ** 2 * gy[:-1, :] ** 2 - (gx[:, :-1] * gy[:-1, :]) ** 2).mean()

    # Entropy
    hist, _ = np.histogram(arr.mean(axis=2).flatten(), bins=256, range=[0, 1])
    p = hist / hist.sum()
    entropy = -np.sum(p[p > 0] * np.log2(p[p > 0]))

    # Buildout: 18 dim (3+3+1+1+1+1+1+1+1+1+1+1+1)
    return np.concatenate([
        global_mean,
        center_mean,
        [edge_mag],
        [corner_str],
        [entropy],
        [0.5] * 9,  # Padding (unused in CNN path)
    ], dtype=np.float32)


# =============================================================================
# Dataset
# =============================================================================

class ControlPatchDataset(Dataset):
    """Dataset patches CO pour Kaggle."""

    def __init__(self, df: pd.DataFrame, transform=None):
        self.df = df.reset_index(drop=True)
        self.transform = transform

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, idx: int):
        row = self.df.iloc[idx]
        img = Image.open(row["img_path"]).convert("RGB")
        label = float(row["label"])

        if self.transform:
            tensor = self.transform(img)
        else:
            tensor = transforms.Compose([
                transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BILINEAR),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])(img)

        return tensor, torch.tensor(label, dtype=torch.float32)


# =============================================================================
# Training
# =============================================================================

def train_cnn_kaggle(
    extra_dirs: list[Path] | None = None,
    output_dir: Path = None,
    epochs: int = 30,
    batch_size: int = 128,
    resume: bool = False,
    # Anciens params conservés pour compatibilité ascendante
    dataset_dir: Path = None,
    vikazimut_dir: Path = None,
) -> Path:
    """
    Entraîner CNN MobileNetV3-Small sur Kaggle GPU.

    Paramètres par défaut pour Kaggle (4 datasets split pos/neg) :
    - extra_dirs: les 4 dossiers /kaggle/input/aitraceur-*
    - output_dir: /kaggle/working/models
    - resume: reprendre depuis checkpoint_resume.pth si disponible

    Compatibilité : dataset_dir et vikazimut_dir sont encore acceptés mais
    ignorés si extra_dirs est fourni.
    """

    # Chemins par défaut (Kaggle — 4 datasets split pos/neg)
    if extra_dirs is None:
        extra_dirs = [
            Path("/kaggle/input/aitraceur-rg2-pos"),
            Path("/kaggle/input/aitraceur-rg2-neg"),
            Path("/kaggle/input/aitraceur-vikazimut-pos"),
            Path("/kaggle/input/aitraceur-vikazimut-neg"),
        ]
        # Fallback ancienne structure (1 ou 2 dirs)
        if not any(d.exists() for d in extra_dirs):
            fallbacks = []
            if dataset_dir is not None:
                fallbacks.append(Path(dataset_dir))
            elif Path("/kaggle/working/data/rg2/dataset").exists():
                fallbacks.append(Path("/kaggle/working/data/rg2/dataset"))
            if vikazimut_dir is not None:
                fallbacks.append(Path(vikazimut_dir))
            elif Path("/kaggle/working/data/vikazimut/patches").exists():
                fallbacks.append(Path("/kaggle/working/data/vikazimut/patches"))
            if fallbacks:
                extra_dirs = fallbacks

    extra_dirs = [Path(d) for d in extra_dirs]
    if output_dir is None:
        output_dir = Path("/kaggle/working/models")
    output_dir = Path(output_dir)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("=== CNN MobileNetV3-Small on Kaggle === (device: %s)", device)

    # -----------------------------------------------------------------------
    # Load + merge datasets
    # -----------------------------------------------------------------------
    def _load_csv(ddir: Path) -> pd.DataFrame:
        csv = ddir / "metadata.csv"
        if not csv.exists():
            log.error("metadata.csv not found: %s", csv)
            sys.exit(1)

        _df = pd.read_csv(csv)
        if "lat" not in _df.columns:
            _df["lat"] = 0.0
        if "lon" not in _df.columns:
            _df["lon"] = 0.0
        _df = _df.dropna(subset=["img_path", "label"])
        _df = _df.drop_duplicates(subset=["img_path"])
        _df["label"] = _df["label"].astype(int)

        # Resolve relative paths
        _df["img_path"] = _df["img_path"].apply(
            lambda p: str(ddir / p) if not Path(p).is_absolute() else p
        )
        _df = _df[_df["img_path"].apply(lambda p: Path(p).exists())]

        log.info("  %s: %d patches (%d pos, %d neg)",
                 ddir.name, len(_df), (_df["label"] == 1).sum(), (_df["label"] == 0).sum())
        return _df

    all_dfs = []
    for d in extra_dirs:
        if d.exists():
            all_dfs.append(_load_csv(d))
        else:
            log.warning("Dataset dir not found (skipped): %s", d)

    if not all_dfs:
        log.error("Aucun dataset trouvé dans : %s", extra_dirs)
        sys.exit(1)

    df = pd.concat(all_dfs, ignore_index=True)
    log.info("Merged dataset: %d patches (%d pos, %d neg)",
             len(df), (df["label"] == 1).sum(), (df["label"] == 0).sum())

    if len(df) < 100:
        log.error("Not enough patches (%d).", len(df))
        sys.exit(1)

    # Stratified split
    df_train, df_val = train_test_split(df, test_size=0.2, random_state=42, stratify=df["label"])

    # Augmentation
    train_transform = transforms.Compose([
        transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.RandomApply([transforms.RandomRotation(degrees=(90, 90))], p=0.33),
        transforms.RandomApply([transforms.RandomRotation(degrees=(180, 180))], p=0.33),
        transforms.RandomApply([transforms.RandomRotation(degrees=(270, 270))], p=0.33),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    val_transform = transforms.Compose([
        transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    train_ds = ControlPatchDataset(df_train, transform=train_transform)
    val_ds = ControlPatchDataset(df_val, transform=val_transform)

    # Class balance
    n_pos = (df_train["label"] == 1).sum()
    n_neg = (df_train["label"] == 0).sum()
    class_weights = {1: n_neg / n_pos, 0: 1.0}
    sample_weights = [class_weights[int(lbl)] for lbl in df_train["label"]]
    sampler = WeightedRandomSampler(sample_weights, num_samples=len(sample_weights), replacement=True)

    train_loader = DataLoader(train_ds, batch_size=batch_size, sampler=sampler,
                              num_workers=4, pin_memory=True, prefetch_factor=2,
                              persistent_workers=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=4, pin_memory=True, prefetch_factor=2,
                            persistent_workers=True)

    # -----------------------------------------------------------------------
    # Model
    # -----------------------------------------------------------------------
    def build_model() -> nn.Module:
        model = models.mobilenet_v3_small(
            weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        )
        # Freeze all
        for param in model.parameters():
            param.requires_grad = False
        # Unfreeze last 2 blocks + classifier
        unfreeze = (list(model.features[-2].parameters()) +
                    list(model.features[-1].parameters()) +
                    list(model.classifier.parameters()))
        for param in unfreeze:
            param.requires_grad = True
        # Replace head
        model.classifier[3] = nn.Linear(1024, 1)
        return model

    model = build_model().to(device)

    # Loss, optimizer, scheduler
    pos_weight = torch.tensor([n_neg / max(n_pos, 1)], dtype=torch.float32).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(
        filter(lambda p: p.requires_grad, model.parameters()), lr=1e-4
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", patience=3, factor=0.5
    )

    # -----------------------------------------------------------------------
    # Training loop
    # -----------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    best_path = output_dir / "best_model.pth"
    resume_path = output_dir / "checkpoint_resume.pth"
    best_val_loss = float("inf")
    history = []
    start_epoch = 1

    # Resume depuis checkpoint si demandé
    if resume and resume_path.exists():
        ckpt = torch.load(resume_path, map_location=device)
        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        scheduler.load_state_dict(ckpt["scheduler"])
        start_epoch = ckpt["epoch"] + 1
        best_val_loss = ckpt.get("best_val_loss", float("inf"))
        history = ckpt.get("history", [])
        log.info("Reprise depuis epoch %d (best_val_loss=%.4f)", start_epoch, best_val_loss)
    elif resume:
        log.warning("--resume demandé mais checkpoint_resume.pth introuvable — démarrage from scratch")

    log.info("Training for %d epochs (train=%d val=%d batch=%d)...",
             epochs, len(train_ds), len(val_ds), batch_size)

    for epoch in range(start_epoch, epochs + 1):
        log.info("=" * 80)
        log.info("Epoch %d/%d", epoch, epochs)

        # Train
        model.train()
        train_loss = 0.0
        pbar = tqdm(train_loader, desc=f"E{epoch}/{epochs} [train]", leave=True)
        for imgs, labels in pbar:
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad()
            logits = model(imgs).squeeze(1)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(imgs)
            pbar.set_postfix(loss=f"{loss.item():.4f}")
        train_loss /= len(train_ds)

        # Validate
        model.eval()
        val_loss = 0.0
        all_preds, all_probs, all_labels = [], [], []
        with torch.no_grad():
            for imgs, labels in tqdm(val_loader, desc=f"E{epoch}/{epochs} [val]  ", leave=False):
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
        log.info("  → Checkpoint saved (epoch %d/%d)", epoch, epochs)

    # Save final model
    out_path = output_dir / "control_scorer_cnn.pt"
    torch.save(model.state_dict(), out_path)
    log.info("Final model saved: %s", out_path)

    # Summary
    best_epoch = min(history, key=lambda r: r["val_loss"])
    log.info("=== Training summary ===")
    log.info("  Best epoch: %d", best_epoch["epoch"])
    log.info("  Best val_loss: %.4f", best_epoch["val_loss"])
    log.info("  Best F1: %.4f", best_epoch["f1"])
    log.info("  Best Recall: %.4f", best_epoch["recall"])

    # -----------------------------------------------------------------------
    # Export ONNX
    # -----------------------------------------------------------------------
    best_model = build_model().to(device)
    best_model.load_state_dict(torch.load(best_path, map_location=device))
    best_model.eval()

    onnx_path = output_dir / "control_scorer_cnn.onnx"
    dummy = torch.randn(1, 3, 224, 224, device=device)
    torch.onnx.export(
        best_model,
        dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=12,
    )
    log.info("ONNX exported: %s", onnx_path)

    return onnx_path


# =============================================================================
# Entry point for Kaggle
# =============================================================================

if __name__ == "__main__":
    onnx = train_cnn_kaggle()
    log.info("✓✓✓ SUCCESS! Download from: /kaggle/working/models/")
