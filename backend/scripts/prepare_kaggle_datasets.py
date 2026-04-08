"""
prepare_kaggle_datasets.py — Prépare 4 dossiers pour upload Kaggle (split pos/neg × rg2/vikazimut)

Les patches sont déjà dans train/pos/ et train/neg/ — on copie chaque sous-dossier séparément
pour créer 4 datasets Kaggle indépendants (chacun < 20 GB).

Usage (depuis la racine du projet) :
    py -3.13 backend/scripts/prepare_kaggle_datasets.py [--username KAGGLE_USERNAME]

Résultat :
    e:/tmp/kaggle_datasets/
        aitraceur-rg2-pos/        train/pos/*.png + metadata.csv
        aitraceur-rg2-neg/        train/neg/*.png + metadata.csv
        aitraceur-vikazimut-pos/  train/pos/*.png + metadata.csv
        aitraceur-vikazimut-neg/  train/neg/*.png + metadata.csv

Upload ensuite :
    cd e:/tmp/kaggle_datasets
    for d in aitraceur-rg2-pos aitraceur-rg2-neg aitraceur-vikazimut-pos aitraceur-vikazimut-neg; do
        kaggle datasets create -p $d --dir-mode zip
    done
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SOURCES: dict[str, Path] = {
    "rg2":       Path("backend/data/rg2/dataset"),
    "vikazimut": Path("vikazimut/patches"),
}
OUT_BASE = Path("e:/tmp/kaggle_datasets")


def prepare(username: str) -> None:
    OUT_BASE.mkdir(parents=True, exist_ok=True)

    for name, src in SOURCES.items():
        if not src.exists():
            print(f"[SKIP] {src} introuvable", file=sys.stderr)
            continue

        csv_path = src / "metadata.csv"
        if not csv_path.exists():
            print(f"[SKIP] metadata.csv absent dans {src}", file=sys.stderr)
            continue

        df = pd.read_csv(csv_path)
        # Normalise les colonnes optionnelles
        for col in ("lat", "lon"):
            if col not in df.columns:
                df[col] = 0.0
        df = df.dropna(subset=["img_path", "label"])
        df["label"] = df["label"].astype(int)

        for label_int, label_name in [(1, "pos"), (0, "neg")]:
            dataset_name = f"aitraceur-{name}-{label_name}"
            out_dir = OUT_BASE / dataset_name

            # Ne pas refaire si déjà présent
            if out_dir.exists():
                n_existing = sum(1 for _ in out_dir.rglob("*.png"))
                print(f"[SKIP] {out_dir} existe déjà ({n_existing} PNG)")
                continue

            print(f"\n{'='*60}")
            print(f"Préparation : {dataset_name}")

            subset = df[df["label"] == label_int].copy()
            print(f"  {len(subset)} patches à copier...")

            # Destination des images
            img_src_dir = src / "train" / label_name
            img_dst_dir = out_dir / "train" / label_name
            img_dst_dir.mkdir(parents=True, exist_ok=True)

            if not img_src_dir.exists():
                print(f"  [WARN] {img_src_dir} introuvable — copie fichier par fichier depuis CSV")
                _copy_from_csv(subset, src, img_dst_dir, out_dir, label_name)
            else:
                # Copie rapide du dossier entier
                t0 = time.time()
                shutil.copytree(img_src_dir, img_dst_dir, dirs_exist_ok=True)
                elapsed = time.time() - t0
                n_copied = sum(1 for _ in img_dst_dir.iterdir())
                print(f"  Copié {n_copied} fichiers en {elapsed:.0f}s")

            # metadata.csv filtré avec chemins relatifs au dataset
            subset = subset.copy()
            subset["img_path"] = subset["img_path"].apply(
                lambda p: f"train/{label_name}/{Path(p).name}"
            )
            out_csv = subset[["img_path", "label", "lat", "lon"]]
            out_csv.to_csv(out_dir / "metadata.csv", index=False)
            print(f"  metadata.csv : {len(out_csv)} lignes -> {out_dir / 'metadata.csv'}")

            # dataset-metadata.json pour Kaggle CLI
            meta = {
                "title": f"AItraceur {name.upper()} {label_name}",
                "id": f"{username}/aitraceur-{name}-{label_name}",
                "licenses": [{"name": "other"}],
            }
            (out_dir / "dataset-metadata.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
            print(f"  dataset-metadata.json : id = {meta['id']}")

    print(f"\n{'='*60}")
    print(f"Terminé. Dossiers dans {OUT_BASE}")
    print()
    print("Pour uploader sur Kaggle :")
    print("  pip install kaggle")
    print("  # Placer kaggle.json dans ~/.kaggle/")
    print(f"  cd {OUT_BASE}")
    for name in SOURCES:
        for lbl in ("pos", "neg"):
            print(f"  kaggle datasets create -p aitraceur-{name}-{lbl} --dir-mode zip")


def _copy_from_csv(
    subset: pd.DataFrame,
    src_root: Path,
    img_dst_dir: Path,
    out_dir: Path,
    label_name: str,
) -> None:
    """Fallback : copie fichier par fichier quand le dossier source n'est pas structuré."""
    copied = 0
    for _, row in subset.iterrows():
        p = Path(row["img_path"])
        abs_p = p if p.is_absolute() else src_root / p
        if abs_p.exists():
            shutil.copy2(abs_p, img_dst_dir / abs_p.name)
            copied += 1
    print(f"  Copié {copied} fichiers (fallback)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username",
        default="VOTRE_USERNAME",
        help="Ton username Kaggle (pour dataset-metadata.json)",
    )
    args = parser.parse_args()

    if args.username == "VOTRE_USERNAME":
        print("[WARN] Passe --username TON_USERNAME_KAGGLE pour avoir les bons IDs")

    prepare(args.username)
