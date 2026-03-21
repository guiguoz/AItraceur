#!/usr/bin/env python3
"""
Ingestion batch Livelox → ML features (sprint urbain).

Usage:
    python ingest_livelox.py --from 2025-01-01 --to 2025-12-31
    python ingest_livelox.py --from 2024-01-01 --to 2024-12-31 --country SE
    python ingest_livelox.py --event 180528
    python ingest_livelox.py --from 2025-01-01 --to 2025-12-31 --dry-run
    python ingest_livelox.py --from 2025-01-01 --to 2025-12-31 --api-key YOUR_KEY

Options:
    --from DATE       Date de début (YYYY-MM-DD)
    --to DATE         Date de fin (YYYY-MM-DD)
    --event ID        Ingérer un événement unique (test)
    --country CODE    Code pays Livelox : SE=752, NO=578, FR=250, DE=276, AU=36, GB=826
    --all-types       Inclure tous les types (pas seulement sprint)
    --dry-run         Parser sans stocker en DB
    --max N           Limiter à N événements (test)
    --api-key KEY     Clé API Livelox (optionnel pour données publiques)

Pays Livelox (codes numériques) :
    SE=752  NO=578  FR=250  DE=276  FI=246  DK=208
    CH=756  AT=40   CZ=203  GB=826  AU=36   US=840
"""

import argparse
import os
import sys
from datetime import datetime

# Ajout du répertoire backend au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

COUNTRY_CODES = {
    "SE": 752, "NO": 578, "FR": 250, "DE": 276, "FI": 246,
    "DK": 208, "CH": 756, "AT": 40, "CZ": 203, "GB": 826,
    "AU": 36, "US": 840, "NZ": 554, "JP": 392,
}


def parse_args():
    p = argparse.ArgumentParser(description="Ingestion Livelox → ML features sprint urbain")
    p.add_argument("--from", dest="from_date", help="Date début YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", help="Date fin YYYY-MM-DD")
    p.add_argument("--event", type=int, help="ID événement unique (test)")
    p.add_argument("--country", help="Code pays (ex: SE, FR, NO)")
    p.add_argument("--all-types", action="store_true", help="Tous types (pas seulement sprint)")
    p.add_argument("--dry-run", action="store_true", help="Parser sans stocker")
    p.add_argument("--max", type=int, dest="max_events", help="Limite N événements")
    p.add_argument("--api-key", dest="api_key", help="Clé API Livelox")
    p.add_argument("--username", dest="username", help="Identifiant livelox.com")
    p.add_argument("--password", dest="password", help="Mot de passe livelox.com")
    return p.parse_args()


def main():
    args = parse_args()

    if not args.event and not (args.from_date and args.to_date):
        print("Erreur : spécifier --event ID ou --from DATE --to DATE")
        print(__doc__)
        sys.exit(1)

    # Résolution du code pays
    country_id = None
    if args.country:
        country_id = COUNTRY_CODES.get(args.country.upper())
        if country_id is None:
            try:
                country_id = int(args.country)
            except ValueError:
                print(f"Pays inconnu : {args.country}. Codes : {list(COUNTRY_CODES.keys())}")
                sys.exit(1)

    api_key = args.api_key or os.getenv("LIVELOX_API_KEY")
    username = args.username or os.getenv("LIVELOX_USERNAME")
    password = args.password or os.getenv("LIVELOX_PASSWORD")

    print(f"\n{'='*60}")
    print(f"Pipeline Livelox → ML (sprint urbain)")
    if args.event:
        print(f"Événement : {args.event}")
    else:
        print(f"Période : {args.from_date} → {args.to_date}")
    if country_id:
        print(f"Pays     : {args.country} (id={country_id})")
    print(f"Mode     : {'DRY RUN' if args.dry_run else 'STOCKAGE DB'}")
    auth_mode = "clé API" if api_key else ("compte web" if username else "non authentifié")
    print(f"Auth     : {auth_mode}")
    print(f"{'='*60}\n")

    # Initialisation DB
    db = None
    if not args.dry_run:
        try:
            from src.core.database import SessionLocal
            db = SessionLocal()
        except Exception as e:
            print(f"Erreur DB : {e}")
            sys.exit(1)

    # Client + importer
    from src.services.importers.livelox_client import LiveloxClient
    from src.services.importers.livelox_importer import LiveloxImporter

    client = LiveloxClient(api_key=api_key)
    if username and password:
        ok = client.login(username, password)
        if not ok:
            print("Erreur : authentification Livelox échouée")
            sys.exit(1)
    importer = LiveloxImporter(client=client, db=db)

    try:
        if args.event:
            stats = importer.ingest_event(
                event_id=args.event,
                sprint_only=not args.all_types,
                dry_run=args.dry_run,
            )
        else:
            from_dt = f"{args.from_date}T00:00:00Z"
            to_dt = f"{args.to_date}T23:59:59Z"
            stats = importer.ingest(
                from_dt=from_dt,
                to_dt=to_dt,
                country_id=country_id,
                sprint_only=not args.all_types,
                dry_run=args.dry_run,
                max_events=args.max_events,
            )
    finally:
        if db:
            db.close()

    print(f"\nFini. Circuits stockés : {stats.get('stored', 0)}")


if __name__ == "__main__":
    main()
