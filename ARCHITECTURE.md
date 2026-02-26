# ARCHITECTURE.md – Architecture technique de l'application

## 1. Vue d'ensemble

L'application est une **web app full-stack** avec :

- Un **backend** en Python (FastAPI) :
  - API REST + WebSockets pour suivi tâches longues.
  - Traitements géospatiaux (LIDAR, OSM, overlay).
  - Analyse & génération de circuits.
  - Tâches asynchrones (Celery).
  - Intégration IA (RAG + GPT-4/Claude).

- Un **frontend** en React + TypeScript :
  - Upload de fichiers OCAD.
  - Carte interactive (Mapbox GL JS).
  - Panneaux d'analyse, paramètres d'optimisation, génération de circuits.
  - Chat assistant IA.

- Des services annexes :
  - Base de données PostgreSQL + PostGIS.
  - Redis pour le cache et les files Celery.
  - Vector DB (Pinecone ou Chroma) pour la base de connaissances IA.
  - Stockage fichiers (S3-compatible : MinIO local ou Cloudflare R2).

---

## 2. Stack technique détaillée

### 2.1. Backend

| Composant | Technologie | Rôle |
|-----------|-------------|------|
| Langage | **Python 3.11+** | Backend principal |
| Framework web | **FastAPI** | API REST + WebSockets |
| Base de données | **PostgreSQL 15 + PostGIS** | Stockage circuits, utilisateurs, géométries |
| Cache & Queue | **Redis** | Cache données terrain, file Celery |
| Tâches async | **Celery** | Traitement LIDAR, génération circuits |
| ORM | **SQLAlchemy 2.0** | Gestion DB |
| Validation | **Pydantic v2** | Schémas API |
| Traitement LIDAR | **PDAL, laspy, rasterio** | Pipeline LIDAR → rasters |
| Géométrie | **shapely, pyproj, geopandas** | Calculs géospatiaux |
| IA & RAG | **OpenAI (GPT-4), LangChain** | Génération circuits, assistant expert |
| Vector DB | **Pinecone** ou **Chroma** | Base connaissances RAG |
| Export PDF | **ReportLab** ou **WeasyPrint** | Rapports d'analyse |

### 2.2. Frontend

| Composant | Technologie | Rôle |
|-----------|-------------|------|
| Framework | **React 18+** | Interface utilisateur |
| Langage | **TypeScript** | Type safety |
| Carte | **Mapbox GL JS** | Affichage circuits, overlay terrain |
| État global | **Zustand** | Gestion état léger |
| Requêtes API | **TanStack Query (React Query)** | Cache & sync API |
| UI Components | **shadcn/ui + Tailwind CSS** | Design system moderne |
| Formulaires | **React Hook Form + Zod** | Validation formulaires |
| Upload | **React Dropzone** | Upload fichiers OCAD |

### 2.3. DevOps & Infrastructure

| Composant | Technologie | Rôle |
|-----------|-------------|------|
| Conteneurs | **Docker + Docker Compose** | Développement local |
| CI/CD | **GitHub Actions** | Tests auto, déploiement |
| Déploiement MVP | **Fly.io** | Hébergement simple, EU |
| Storage | **Cloudflare R2** ou **MinIO** | Fichiers OCAD, exports |
| CDN | **Cloudflare** | Cache tiles terrain |
| Monitoring | **Sentry** | Tracking erreurs |
| Logs | **structlog** | Logs structurés JSON |

---

## 3. Organisation du code – Backend

### 3.1. Structure des dossiers

```text
backend/
├── src/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── circuits.py           # CRUD circuits
│   │   │   ├── optimization.py       # Endpoints optimisation
│   │   │   ├── generation.py         # Endpoints génération
│   │   │   ├── analysis.py           # Endpoints analyse
│   │   │   ├── uploads.py            # Upload fichiers OCAD
│   │   │   └── ai.py                 # Chat assistant IA
│   │   ├── dependencies.py           # Dépendances FastAPI
│   │   └── websockets.py             # WebSocket handlers
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                 # Configuration (env vars)
│   │   ├── database.py               # Connexion PostgreSQL
│   │   ├── logging_config.py         # Setup logs structurés
│   │   └── security.py               # Auth JWT (futur)
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── circuit.py                # SQLAlchemy models
│   │   ├── user.py
│   │   ├── event.py
│   │   └── task.py                   # Tâches Celery (statut)
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── circuit.py                # Pydantic schemas API
│   │   ├── optimization.py
│   │   ├── generation.py
│   │   ├── analysis.py
│   │   └── common.py                 # Schemas réutilisables
│   │
│   ├── services/
│   │   ├── ocad/
│   │   │   ├── __init__.py
│   │   │   ├── parser.py             # Lecture fichiers .ocd
│   │   │   ├── exporter.py           # Export IOF XML, .ocd
│   │   │   ├── validator.py          # Validation données OCAD
│   │   │   └── binary_reader.py      # Lecture binaire bas niveau
│   │   │
│   │   ├── terrain/
│   │   │   ├── __init__.py
│   │   │   ├── lidar_manager.py      # Gestion LIDAR IGN
│   │   │   ├── osm_fetcher.py        # Requêtes Overpass API
│   │   │   ├── cadastre_fetcher.py   # API cadastre (optionnel)
│   │   │   ├── terrain_analyzer.py   # Calcul runnability
│   │   │   └── overlay_builder.py    # Superposition OCAD+OSM+LIDAR
│   │   │
│   │   ├── environment/
│   │   │   ├── __init__.py
│   │   │   └── detector.py           # Détection forêt/urbain/parc
│   │   │
│   │   ├── optimization/
│   │   │   ├── __init__.py
│   │   │   ├── detector.py           # Détection problèmes
│   │   │   ├── route_calculator.py   # Calcul routes réalistes
│   │   │   ├── optimizer.py          # Optimisation positions postes
│   │   │   └── visibility_analyzer.py # Analyse spoils
│   │   │
│   │   ├── generation/
│   │   │   ├── __init__.py
│   │   │   ├── graph_builder.py      # Graphe navigation
│   │   │   ├── genetic_algo.py       # Algorithme génétique
│   │   │   ├── ai_generator.py       # Génération GPT-4
│   │   │   └── scorer.py             # Scoring variantes
│   │   │
│   │   ├── knowledge_base/
│   │   │   ├── __init__.py
│   │   │   ├── scrapers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── livelox.py        # Scraper Livelox
│   │   │   │   ├── vikazimut.py      # Scraper Vikazimut
│   │   │   │   └── routegadget.py    # Scraper RouteGadget
│   │   │   ├── document_loader.py    # Import PDF/DOC officiels
│   │   │   ├── rag_builder.py        # Construction base RAG
│   │   │   └── ai_assistant.py       # Assistant expert RAG
│   │   │
│   │   └── export/
│   │       ├── __init__.py
│   │       ├── iof_exporter.py       # Export IOF XML 3.0
│   │       ├── pdf_generator.py      # Rapports PDF
│   │       └── gpx_exporter.py       # Export GPX
│   │
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── celery_app.py             # Configuration Celery
│   │   ├── lidar_processing.py       # Task traitement LIDAR
│   │   ├── circuit_generation.py     # Task génération circuit
│   │   └── kb_update.py              # Task MAJ base connaissances
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── geometry.py               # Fonctions géométriques
│   │   ├── cache.py                  # Utilitaires cache Redis
│   │   └── constants.py              # Constantes (TD, vitesses, etc.)
│   │
│   └── main.py                       # Point d'entrée FastAPI
│
├── tests/
│   ├── fixtures/
│   │   ├── forest/                   # Données test forêt
│   │   ├── urban/                    # Données test ville
│   │   └── park/                     # Données test parc
│   ├── unit/
│   ├── integration/
│   └── conftest.py
│
├── alembic/                          # Migrations DB
├── docker/                           # Dockerfiles spécifiques
├── scripts/                          # Scripts utilitaires
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml                    # Config Python (Black, Ruff, etc.)
├── Dockerfile
└── docker-compose.yml
