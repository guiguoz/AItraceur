# ARCHITECTURE.md — Architecture technique de AItraceur

## 1. Vue d'ensemble

AItraceur est une **web app full-stack à 3 services** pour la génération assistée par IA de parcours de course d'orientation.

```
Navigateur (5173)
    │
    ▼
Frontend React + Vite
    │  REST / polling
    ▼
Backend FastAPI (8000) ←──────→ Tile Service Node.js (8089)
    │                                    │
    ├── aitraceur/ (lib core, ~7500 LOC) │  OCAD .ocd → PNG tiles
    ├── services/ (terrain, ML, export)  │
    └── SQLite                           │
```

---

## 2. Services

| Service | Port | Techno | Démarrage | Rôle |
|---------|------|--------|-----------|------|
| Backend FastAPI | 8000 | Python 3.11+ | `cd backend && uvicorn src.main:app --reload` | API REST, génération, ML |
| Frontend | 5173 | React 18 + Vite | `cd frontend && npm run dev` | Interface utilisateur |
| Tile Service | 8089 | Node.js | `cd backend/tile-service && node server.js` | Rendu OCAD `.ocd` → PNG/tiles |

---

## 3. Backend — Structure détaillée

### 3.1. Point d'entrée

`backend/src/main.py` — application FastAPI principale, ~47 endpoints.

Endpoints principaux :
| Endpoint | Méthode | Rôle |
|----------|---------|------|
| `/api/v1/generation/generate-sprint` | POST | Lance génération sprint (retourne `task_id`) |
| `/api/v1/generation/sprint-status/{task_id}` | GET | Poll statut (pattern Task-Status) |
| `/api/v1/generation/generate` | POST | Génération forêt/MD/LD (async) |
| `/api/v1/categories` | GET | Règles FFCO/IOF par catégorie |
| `/api/v1/knowledge/ingest-docs` | POST | Ingère PDF IOF/FFCO dans RAG |
| `/upload` *(tile service)* | POST | Upload `.ocd` → rendu tiles |
| `/export/iof-xml`, `/export/gpx`, `/export/pdf`, `/export/kml` | POST | Exports |

### 3.2. Pattern Task-Status (async)

La génération de circuits prend 35-40 s. Le pattern évite les timeouts HTTP :

```
POST /generate-sprint  →  {task_id, status: "processing"}  <100ms
                               │
                    Background ThreadPool (max 3 workers)
                    ── OSM fetch (8s)
                    ── OCAD/MapAnt heatmap (6s)
                    ── Algorithme génétique (7s)
                    ── Boucle contrôleur (5s)
                    ── Résultat stocké en mémoire (_sprint_tasks)
                               │
GET /sprint-status/{task_id}  →  {status, controls, dialogue, …}   polling 2s
```

### 3.3. Librairie core `aitraceur/` (~7 500 LOC)

Bibliothèque Python autonome, indépendante de FastAPI. Encapsule tout le pipeline de génération.

```
backend/src/aitraceur/
├── controls/          # ControlCandidate, enrichissement, parseur OCAD, carte symboles ISOM
├── matrix/            # CostMatrix (Tobler A* parallèle), LegCache (thread-safe), SpatialFilter
├── model/             # Leg, Course — objets immuables
├── navigation/        # TerrainMovementCost, ElevationProvider, modèle Tobler, graph OSM
├── generation/        # GeneticAlgorithm, SA (recuit simulé), greedy NN, local_opt
├── scoring/           # score_course(), CourseScoreBreakdown, anti-patterns, flow, variety
├── calibration/       # CalibrationEngine L-BFGS-B (11 params, régularisation L2)
└── profiles.py        # ScoringWeights — 4 profils (Forêt Blanc→Noir, Sprint urbain)
```

### 3.4. Couche services `services/`

| Répertoire | Fichiers clés | Rôle |
|-----------|---------------|------|
| `generation/` | `genetic_algo.py`, `ai_generator.py`, `scorer.py` | GA FastAPI-facing, ISOM KDTree Phase 2 |
| `controleur/` | `controleur.py`, `traceur_corrections.py` | Validation C01–C12 IOF/FFCO, corrections auto |
| `learning/` | `ocad_patch_scorer.py`, `patch_feature_extractor.py`, `style_normalizer.py` | XGBoost V3, HeatmapCache, normalisation OCAD→MapAnt |
| `terrain/` | `osm_fetcher.py`, `elevation_fetcher.py`, `mapant_fetcher.py` | OSM Overpass, IGN LIDAR, MapAnt fallback |
| `optimization/` | `route_analyzer.py`, `route_calculator.py`, `detector.py` | NetworkX A*, diversité Jaccard, dog-legs |
| `rules/` | `ffco_rules_engine.py` | Source de vérité FFCO/IOF (distances, TD, temps gagnants) |
| `export/` | `iof_exporter.py`, `gpx_exporter.py`, `pdf_exporter.py`, `kml_exporter.py` | IOF XML 3.0, GPX, PDF, KML/KMZ |
| `knowledge_base/` | `local_rag.py`, `ai_assistant.py`, `course_rules_retriever.py` | RAG local (22 PDF indexés), chaîne LLM |
| `ocad/` | `parser.py`, `geojson_extractor.py`, `terrain_descriptor.py` | Lecture binaire OCAD, extraction GeoJSON |
| `analysis/` | `gpx_parser.py`, `multi_gpx_analyzer.py` | Import/analyse traces GPS |
| `importers/` | `livelox_client.py`, `iof_importer.py` | Import LiveLox, IOF XML |

### 3.5. Base de données

**SQLite** (pas PostgreSQL). Fichier `aitraceur.db`, accès via SQLAlchemy.
- Entités : circuits, contrôles, événements
- Pas de Redis, pas de Celery, pas de migrations Alembic actives
- Configuration : `backend/src/core/config.py`

---

## 4. Frontend — Structure détaillée

### 4.1. Stack réelle

| Composant | Techno | Note |
|-----------|--------|------|
| Framework | React 18 + Vite | **JSX** (pas TypeScript) |
| Carte | Leaflet + react-leaflet | **Pas Mapbox** |
| Style | Tailwind CSS | Pas shadcn/Zustand/TanStack |
| État | useState/useCallback | Pas de store global |
| Build | Vite | Sortie `frontend/dist/` |

### 4.2. Composants

```
frontend/src/
├── App.jsx                    # Composant racine — état global, orchestration
├── main.jsx                   # Point d'entrée
├── index.css                  # Styles globaux
│
├── components/
│   ├── MapViewer.jsx          # Carte Leaflet, tiles, polygones, polyline IOF magenta
│   ├── OcadUploader.jsx       # Drag & drop fichier .ocd
│   ├── OcadAnalysisPanel.jsx  # Analyse des features ISOM chargées
│   ├── AISuggestionPanel.jsx  # Validation/refus des postes suggérés
│   ├── DialogueLog.jsx        # Échanges traceur↔contrôleur + rapport IOF/FFCO
│   ├── CircuitCreationModal.jsx # Création circuit (type, catégorie, TD, force_mode)
│   ├── CircuitSelector.jsx    # Sélecteur circuits multi (sidebar)
│   ├── ControlsList.jsx       # Liste postes avec icônes IOF
│   ├── GpxImporter.jsx        # Import traces GPX
│   ├── TerrainPanel.jsx       # Overlay runnability heatmap
│   ├── AiChatPanel.jsx        # Chat LLM (RAG IOF/FFCO)
│   ├── ContributeForm.jsx     # Contribution données
│   └── AISuggestionPanel.jsx  # Panneau suggestions IA
│
└── services/
    ├── api.js                 # Appels backend + tile service
    ├── ocadCrs.js             # Reprojection CRS OCAD → WGS84
    └── mapContext.js          # Contexte carte Leaflet
```

### 4.3. Flux de données principal

```
Utilisateur pose départ/arrivée sur la carte
    │
    ▼
CircuitCreationModal → paramètres (catégorie, TD, force_mode)
    │
    ▼
App.jsx → generateSprint() / generateCircuitAsync()
    │  POST → task_id
    ▼
_pollSprintStatus() → polling GET /sprint-status (2s)
    │  {controls, dialogue, controleur_report, warning, distance_ratio}
    ▼
aiSuggestions[] → AISuggestionPanel (validation/refus poste par poste)
    │
    ▼
MapViewer → Polyline IOF magenta (départ→postes→arrivée)
DialogueLog → échanges traceur↔contrôleur + rapport C01–C12
```

---

## 5. Tile Service — Pipeline OCAD

```
Upload .ocd  →  ocad-tiler parse  →  PNG pleine carte + GeoJSON vecteurs
                     │
                     ├── GeoJSON vecteurs (sym 709/527) → forbidden zones
                     └── PNG → normalisation histogramme → domaine MapAnt
                                    │
                                    ▼
                         HeatmapCache XGBoost V3
```

**Coordonnées :** le tile service opère en Lambert-93 (mètres). Le frontend extrait les bounds WGS84 depuis le GeoJSON → envoyées avec le `.ocd` lors de l'upload. Le serveur fait une projection linéaire WGS84→Lambert-93 (valide sur ~6 km).

---

## 6. Pipeline ML — Scorer XGBoost V3

```
Données RG2 (scrape_rg2.py)
    │  370k postes géoréférencés (88 clubs UK)
    ▼
Patches MapAnt 256×256 → 18 features (patch_feature_extractor.py)
    │  [ISOM_global×7, ISOM_centre×7, edge, corner, entropy, is_urban]
    ▼
XGBoost V3 (train_control_scorer.py)  →  patch_scorer_v2.pkl (AUC=0.807)
    │
    ▼
build_heatmap_cache(img, bbox, mpp)
    │  Grille 40×40, source : OCAD PNG (priorité) ou MapAnt (fallback)
    │  OOB mask : vecteurs OCAD sym 709/527 rasterisés (dilation 15m)
    ▼
HeatmapCache passé au GA → lookups O(1) pendant l'évolution
```

**Normalisation OCAD→MapAnt :** `style_normalizer.py` — `match_histograms()` RGB pour aligner la distribution de couleurs OCAD vers le domaine d'entraînement MapAnt.

---

## 7. Algorithme génétique — Patterns clés

### 7.1. Fitness multicritère

```
fitness = w_dist × dist_score
        + w_ml   × heatmap_score       ← XGBoost V3 (O(1) lookup)
        + w_rythm × rhythm_score
        - w_dog  × dogleg_penalty       ← A* NetworkX OSM (C01)
        - w_clust × clustering_penalty
        + IOFCompliance (TD1-5, PD1-5)
```

### 7.2. ISOM KDTree Phase 2

Lors de l'initialisation du GA, un `scipy.spatial.KDTree` est construit sur les features ISOM du fichier OCAD. À chaque mutation (~90% du temps), le poste est snapé sur la feature ISOM la plus proche (O(log N)). Pénalité si distance > 40m (sprint) / 80m (forêt).

### 7.3. Boucle Traceur ↔ Contrôleur

```
GA génère circuit
    │
    ▼
ControleurSprint.check(circuit)  →  rapport C01–C12
    │  corrections automatiques si C01/C02/C08/C10
    ▼
apply_corrections(circuit, rapport)
    │
    └── répéter max 5 fois si non conforme
    │
    ▼
Circuit final + dialogue JSON [{role, step, message}]
```

---

## 8. Dataset Vikazimut

3 486 parcours French (XML IOF 3.0 + KML géoréférencement) + 13 264 traces GPX + 4 405 cartes JPG, téléchargés depuis Vikazimut.fr.

Script d'indexation : `backend/scripts/index_vikazimut.py`
- Parse tous les XML (discipline, distance, postes WGS84)
- Filtre VTT-O/MTBO (discipline, course_type, distance > 20 km)
- Associe les traces GPX par parcours
- Produit `vikazimut/index.json` (2 851 parcours foot-O conservés)

Usage futur : patches d'entraînement XGBoost FR, heatmaps de pénétrabilité réelle depuis GPX.

---

## 9. Dépendances externes clés

| Lib | Usage |
|-----|-------|
| `ocad2geojson` / `ocad-tiler` | Lecture et rendu fichiers `.ocd` (Node.js) |
| `scipy.spatial.KDTree` | Snap postes sur features ISOM (O(log N)) |
| `networkx` | Graphe OSM pour A* (RouteAnalyzer, dog-legs) |
| `xgboost` | Classificateur patch scorer V3 |
| `shapely` / `pyproj` | Géométrie, reprojections |
| `rasterio` / `Pillow` | Traitement rasters (LIDAR, tiles) |
| `ollama` (optionnel) | LLM local (Llama 3, fallback RAG) |
| `react-leaflet` | Carte interactive frontend |
| `tailwindcss` | Style frontend |
