# AItraceur — Générateur IA de tracés d'orientation

> Outil web d'aide à la conception de circuits d'orientation (CO), assisté par intelligence artificielle.
> Web tool for AI-assisted orienteering course design.

---

## Fonctionnalités

- **Génération automatique** de circuits sprint (urbain) et forêt via algorithme génétique multi-objectifs
- **Sprint asynchrone** : POST retourne `task_id` en <100ms, pipeline en arrière-plan (~35s), polling GET `/sprint-status`
- **Contexte terrain manuel** : sélecteur [Auto / Urbain / Forêt] pour forcer le mode détection IA
- **Fitness multicritère V2** : IA Score (HeatmapCache XGBoost), pénalité distance, détection dog-legs, bonus rythme
- **Pipeline OCAD natif** : le fichier `.ocd` uploadé alimente directement l'IA — zones interdites extraites des vecteurs (sym 709/527 ISSprOM/ISOM), image rasterisée normalisée vers la distribution MapAnt d'entraînement
- **HeatmapCache** : grille de scores V2 précomputée (O(1) lookups GA), Smart Seeding population initiale — source : OCAD tile service (priorité) ou MapAnt (fallback forêt/LD)
- **Forbidden mask vectoriel** : polygones OOB extraits directement depuis les symboles OCAD (100 % fiable) ; requête Overpass bâtiments skippée → gain ~50s
- **Ancrage vectoriel ISOM Phase 2** : postes ancrés sur les features OCAD réelles via `scipy.spatial.KDTree` (O(log N)) — pénalité si poste trop loin (rayon 40 m sprint / 80 m forêt), attractivité sémantique `ISOM_ATT` transmise depuis le frontend
- **Contrôleur IOF/FFCO** : validation automatique des règles (dog-legs, jambes C01–C12, TD1-5/PD1-5)
- **Boucle traceur ↔ contrôleur** : dialogue IA avec corrections automatiques (jusqu'à 5 itérations)
- **FFCORulesEngine** : source de vérité unique pour les seuils FFCO/IOF — distances, TD, temps gagnants par catégorie exposés via `GET /api/v1/categories` ; seuils injectés dans le GA (remplace les constantes hardcodées)
- **Détection circuit impossible** : score GA < -5000 → erreur explicite ; distance < 70 % cible → `warning` dans la réponse
- **Analyse de routes** : NetworkX A*, diversité des itinéraires (Jaccard), détection dog-legs, Re-Ranker Top-3 (budget 15s)
- **Scorer XGBoost V3** : 18-dim bi-mode (`is_urban` feat[17]), `patch_scorer_v2.pkl` — 370k patches RG2 (88 clubs UK), entraîné sur images MapAnt
- **Carte OCAD** : rendu haute-fidélité des fichiers `.ocd` via tile service Node.js
- **Terrain OSM** : enrichissement automatique depuis Overpass API (highways pour RouteAnalyzer)
- **Export** : IOF XML 3.0, GPX, PDF, KML/KMZ — à importer dans OCAD pour le tracé final
- **RAG local** : 22 PDF IOF/FFCO indexés, chaîne LLM (OpenAI → fallback local)

---

## Architecture

| Service | Port | Technologie |
|---------|------|-------------|
| Backend FastAPI | 8000 | Python 3.11+ |
| Frontend | 5173 | React + Vite |
| Tile Service | 8089 | Node.js |

---

## Installation

### Prérequis
- Python 3.11+
- Node.js 18+
- (Optionnel) Ollama pour le LLM local

### Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # puis éditer si besoin
uvicorn src.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Tile Service (requis pour cartes OCAD)
```bash
cd backend/tile-service
npm install
node server.js
```

Ouvrir [http://localhost:5173](http://localhost:5173)

---

## Configuration

Copier `backend/.env.example` en `backend/.env` et configurer :

```env
# Optionnel : LLM OpenAI (sinon fallback local Ollama)
# OPENAI_API_KEY=sk-...

# Base de données (SQLite par défaut, pas de config nécessaire)
# DATABASE_URL=sqlite:///./aitraceur.db
```

---

## Pipeline ML — Scorer de postes (XGBoost V3)

### Vue d'ensemble

Le composant `patch_scorer_v2.pkl` est un classificateur XGBoost entraîné pour évaluer visuellement la qualité d'un emplacement de poste à partir d'une tuile de carte CO.

### 1. Scraping du dataset (RG2)

Le script `backend/scripts/scrape_rg2.py` collecte automatiquement des postes géoréférencés depuis les clubs d'orientation utilisant [RouteGadget 2](https://www.routegadget.co.uk) :

```bash
cd backend && python scripts/scrape_rg2.py
```

**Résultats (session 2026-03-23) :**
- 102 instances RG2 sondées, 88 avec des données exploitables
- **370 213 postes positifs** (WGS84, géoréférencés)
- **740 378 non-postes** (points négatifs générés aléatoirement)
- Métadonnées : `lat`, `lon`, `course_type` (sprint/score/forest...), `mpp`, `event_name`

Chaque poste génère un **patch PNG 256×256** extrait depuis les tuiles MapAnt au bon niveau de zoom.

### 2. Extraction de features (18-dim)

Module `backend/src/services/learning/patch_feature_extractor.py` :

| Dimension | Feature | Description |
|-----------|---------|-------------|
| [0:7] | ISOM global | Fraction de pixels par couleur ISOM (brun/vert dense/vert clair/jaune/bleu/noir/blanc) sur le patch 256×256 |
| [7:14] | ISOM centre | Mêmes 7 couleurs sur le crop central 64×64 (zone du poste) |
| [14] | `edge_density` | Fraction pixels gradient Sobel > 20 (complexité géométrique) |
| [15] | `corner_density` | Fraction pixels réponse Harris > 1% du max (intersections, angles) |
| [16] | `entropy` | Entropie Shannon normalisée [0,1] (richesse visuelle) |
| [17] | `is_urban` | 1 si coordonnées dans une zone urbaine dense (bbox hardcodées UK/FR), 0 sinon |

### 3. Entraînement XGBoost V3 (bi-mode)

```bash
cd backend && python scripts/train_control_scorer.py --phase xgboost
```

**Paramètres clés :**
- `n_estimators=300`, `max_depth=6`, `scale_pos_weight=2.0` (déséquilibre 1:2)
- **Sample weighting** : patches `course_type=sprint` → poids 2.0×, autres → 1.0× (biais vers sprint urbain)
- Extraction parallèle (6 workers) via `ProcessPoolExecutor`

**Métriques V3 (238k patches, 88 clubs) :**
| Métrique | Valeur |
|---------|--------|
| AUC-ROC | 0.807 |
| F1 | 0.645 |
| Precision | 0.545 |
| Recall | **0.789** |

Le Recall supérieur (+4% vs V2) signifie moins de postes légitimes manqués. L'AUC légèrement inférieure reflète la diversité accrue du dataset (forêt + score + sprint).

### 4. Intégration : HeatmapCache + Pipeline OCAD

À l'appel de `/generate-sprint`, le backend :
1. **Si `.ocd` uploadé (`map_id` fourni)** :
   - Extrait les zones OOB depuis les vecteurs OCAD (`GET /map/:mapId/forbidden-zones`, sym 709/527) → `forbidden_mask` fiable à 100%
   - Récupère le PNG pleine-carte rendu par le tile service (`GET /renders/{mapId}.png`)
   - Normalise les couleurs OCAD → distribution MapAnt (`style_normalizer.py`, `match_histograms`)
   - Skip la requête Overpass bâtiments (zones OOB déjà connues) → gain ~50s
2. **Sinon (fallback forêt/LD/MD)** : récupère l'image MapAnt (`_fetch_mapant_bbox_image`)
3. Précompute une grille de scores V3 (`scorer.build_heatmap_cache(img, bbox, mpp)`)
4. Interpole `lng/lat` depuis la `bbox` WGS84 pour activer la feature `is_urban`
5. Passe le `HeatmapCache` à l'algorithme génétique → lookups O(1) pendant l'évolution

**Séparation entraînement / inférence :**
- `train_control_scorer.py` — entraîné exclusivement sur patches MapAnt/RG2 (source de vérité terrain uniforme)
- `ocad_pipeline.py` — adapte les cartes OCAD pour l'inférence (normalisation histogramme → domaine MapAnt)
- `style_normalizer.py` — `match_histograms` RGB pour aligner la distribution de couleurs

---

## Moteur `aitraceur` — Bibliothèque core (standalone)

Le répertoire `backend/src/aitraceur/` est une bibliothèque Python autonome (~7 500 lignes) qui encapsule tout le pipeline de génération de tracés en dehors de FastAPI.

### Modules

| Package | Rôle |
|---------|------|
| `controls/` | `ControlCandidate`, enrichissement, parseur OCAD, carte symboles |
| `matrix/` | `CostMatrix` (Tobler A* parallèle), `LegCache` (thread-safe), `SpatialFilter` |
| `model/` | `Leg`, `Course` — objets métier immuables |
| `navigation/` | `TerrainMovementCost`, `ElevationProvider`, modèle Tobler, graph OSM |
| `generation/` | `GeneticAlgorithm`, SA (recuit simulé), constructif (greedy NN), local_opt |
| `scoring/` | `score_course()`, `CourseScoreBreakdown`, anti-patterns, flow, variety |
| `calibration/` | `CalibrationEngine` L-BFGS-B (11 paramètres, régularisation L2) |
| `profiles.py` | `ScoringWeights`, 4 profils (forêt Blanc→Noir, sprint urbain) |

### Scripts standalone (sans API)

```bash
cd backend

# Générer des candidats de test
python scripts/generate_test_candidates.py --num 20 --output data/candidates.json

# Pipeline SA complet (recuit simulé + export GeoJSON)
python scripts/run_generator.py --candidates data/candidates.json --output output/course.geojson

# Tests visuels terrain 3D (Tobler — génère 3 PNG)
python scripts/run_visual_tests.py

# Visualiser un chemin A* (PNG headless)
python scripts/visualize_leg.py --map path/to/elev.tif --from 50,50 --to 450,450
```

**Résultats typiques `run_generator.py` (20 candidats synthétiques plats) :**
- Score : 81/100 (Grade B), early stop iter 127/2 000
- Export : 29 features GeoJSON (15 postes + 14 jambes avec métriques 3D)

**Résultats `run_visual_tests.py` (GeoTIFF synthétiques) :**

| Scénario | Détour A* | Dénivelé |
|----------|-----------|----------|
| Colline gaussienne | +21.7 % | 10.3 m |
| Mur végétation (passage) | +28.5 % | — |
| Falaise 133 % pente | +146.9 % | — |

---

## Références & Crédits

Ce projet s'est inspiré des outils et standards suivants :

- **[Streeto](https://streeto.co.uk)** — logiciel de génération de circuits sprint en milieu urbain
- **[IOF XML 3.0](https://orienteering.sport/iof/it/data-standard-3-0/)** — standard international d'échange de données pour l'orientation
- **Normes IOF/FFCO de tracé** — règles officielles de conception de circuits (TD1-5, PD1-5, contrôle des dog-legs, distances, dénivelé)
- **[ocad2geojson / ocad-tiler](https://github.com/openlayers/ocad-tiler)** — lecture et rendu des fichiers cartographiques OCAD `.ocd`
- **[OpenStreetMap](https://www.openstreetmap.org) / [Overpass API](https://overpass-api.de)** — données géographiques terrain (bâtiments, routes, obstacles)
- **[Ollama](https://ollama.ai)** — moteur LLM local (Llama 3)
- **[Leaflet](https://leafletjs.com) / [react-leaflet](https://react-leaflet.js.org)** — cartographie interactive

---

## ⚖️ Licence & Usage

Ce projet est sous licence **GNU Affero General Public License v3.0 (AGPL-3.0)** — voir le fichier [LICENSE](./LICENSE).

- **Open Source** : Utilisation, modification et distribution libres sous réserve de publier les modifications du code source, y compris en mode SaaS (utilisation via réseau).
- **Usage commercial propriétaire** : Si vous souhaitez intégrer AItraceur dans un produit commercial fermé sans publier vos modifications, contactez l'auteur pour un accord de licence commerciale.

AItraceur est un projet de recherche. Toute appropriation commerciale sans respect des termes de l'AGPL est interdite.

Copyright (c) 2026 Guillaume Lemiègre
