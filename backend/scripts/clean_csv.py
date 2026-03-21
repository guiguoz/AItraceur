"""
clean_csv.py — Nettoyage de metadata.csv (dédoublonnage)

Usage:
    python scripts/clean_csv.py
    python scripts/clean_csv.py --csv data/rg2/dataset/metadata.csv

Supprime les lignes dupliquées (même img_path) et rapporte les stats.
Les patches orphelins (img_path absent du disque) peuvent aussi être purgés
avec le flag --purge-missing.
"""

import argparse
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("clean_csv")

DEFAULT_CSV = Path(__file__).parent.parent / "data" / "rg2" / "dataset" / "metadata.csv"


def clean(csv_path: Path, purge_missing: bool = False) -> None:
    if not csv_path.exists():
        log.error("Fichier introuvable : %s", csv_path)
        return

    df = pd.read_csv(csv_path)
    n_before = len(df)
    log.info("Lignes lues       : %d", n_before)
    log.info("  pos (label=1)   : %d", (df["label"] == 1).sum())
    log.info("  neg (label=0)   : %d", (df["label"] == 0).sum())

    # 1. Dédoublonnage sur img_path
    df = df.drop_duplicates(subset=["img_path"])
    n_after_dedup = len(df)
    log.info("Après dedup       : %d  (supprimé %d doublons)", n_after_dedup, n_before - n_after_dedup)

    # 2. Purge des patches absents du disque (optionnel)
    if purge_missing:
        dataset_dir = csv_path.parent
        mask_exists = df["img_path"].apply(lambda p: (dataset_dir / p).exists())
        n_missing = (~mask_exists).sum()
        df = df[mask_exists]
        log.info("Patches manquants : %d purgés", n_missing)

    # 3. Sauvegarde
    df.to_csv(csv_path, index=False)
    log.info("Sauvegardé        : %s", csv_path)
    log.info("  pos (label=1)   : %d", (df["label"] == 1).sum())
    log.info("  neg (label=0)   : %d", (df["label"] == 0).sum())
    log.info("  TOTAL           : %d", len(df))


def main():
    parser = argparse.ArgumentParser(description="Nettoyage metadata.csv")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--purge-missing", action="store_true",
                        help="Supprimer les lignes dont le fichier PNG est absent")
    args = parser.parse_args()
    clean(args.csv, purge_missing=args.purge_missing)


if __name__ == "__main__":
    main()
