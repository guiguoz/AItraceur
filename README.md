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
- **Analyse de routes** : NetworkX A*, diversité des itinéraires (Jaccard), détection dog-legs, Re-Ranker Top-3 (budget 15s) ; bouton 🔍 par jambe → k polylines colorées sur la carte (bleu/orange/rouge)
- **DialogueLog** : panneau visuel des échanges traceur↔contrôleur avec score IOF/FFCO par itération
- **Avertissement génération** : si circuit < 70 % de la distance cible → `warning` + `distance_ratio` affichés dans l'interface (fond orange)
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

## Pipeline ML — Scorer de postes (CNN V4)

### Vue d'ensemble

Le scorer visuel évalue la qualité d'un emplacement de poste à partir d'une tuile de carte CO.
- **Prod** : `control_scorer_cnn.onnx` — MobileNetV3-Small (3 canaux RGB), inférence ONNX Runtime
- **Fallback** : `patch_scorer_v2.pkl` — XGBoost 18-dim (si `.onnx` absent)

### 1. Datasets

#### RG2 (226k patches, 88 clubs UK)
```bash
cd backend && python scripts/scrape_rg2.py
```
- 88 instances RouteGadget 2 actives → **226 295 patches** (75k pos / 150k neg)
- Patches PNG 256×256 extraits depuis tuiles MapAnt

#### Vikazimut (201k patches, 2 851 parcours France)
```bash
cd backend
python scripts/index_vikazimut.py       # filtre foot-O → vikazimut/index.json
python scripts/extract_vikazimut_patches.py --resume  # → vikazimut/patches/
```
- **201 902 patches** (70k pos / 131k neg), cartes JPG géoréférencées
- `--resume` reprend depuis le dernier parcours traité

**Dataset fusionné : 428 197 patches** (146k pos / 282k neg)

### 2. Entraînement CNN V4 (MobileNetV3-Small)

```bash
# Lancement (Python 3.13 + PyTorch CUDA)
py -3.13 backend/scripts/train_control_scorer.py \
  --phase cnn --epochs 30 --batch-size 128 \
  --dataset-dir backend/data/rg2/dataset/ \
  --extra-dataset-dir vikazimut/patches/

# Reprendre après interruption
py -3.13 backend/scripts/train_control_scorer.py \
  --phase cnn --epochs 30 --batch-size 128 \
  --dataset-dir backend/data/rg2/dataset/ \
  --extra-dataset-dir vikazimut/patches/ \
  --resume
```

**Architecture :**
- MobileNetV3-Small pré-entraîné ImageNet → fine-tuning (2 derniers blocs + classifier)
- Tête remplacée : 1024 → 1 (classification binaire, BCEWithLogitsLoss)
- `WeightedRandomSampler` pour équilibrer pos/neg + pondération sprint 2×
- Checkpoint automatique après chaque epoch (`checkpoint_resume.pth`) → interruptible

**Métriques epoch 1 (référence) :**
| Métrique | Valeur |
|---------|--------|
| val_loss | 0.5875 |
| Accuracy | 73.9% |
| F1 | 0.710 |
| Recall | **0.934** |

### 3. Export ONNX et déploiement

Le script exporte automatiquement `control_scorer_cnn.onnx` à la fin de l'entraînement.
Copier dans `backend/data/models/` puis redémarrer uvicorn — `CnnPatchScorer` se charge automatiquement.

### 4. Intégration : HeatmapCache + Pipeline OCAD

À l'appel de `/generate-sprint`, le backend :
1. **Si `.ocd` uploadé (`map_id` fourni)** :
   - Extrait les zones OOB depuis les vecteurs OCAD (sym 709/527) → `forbidden_mask` fiable à 100%
   - Récupère le PNG pleine-carte rendu par le tile service
   - Normalise les couleurs OCAD → distribution MapAnt (`style_normalizer.py`)
2. **Sinon** : récupère l'image MapAnt (`_fetch_mapant_bbox_image`)
3. Précompute une grille de scores CNN (`build_heatmap_cache`) — `CnnPatchScorer` si `.onnx` présent, XGBoost sinon
4. Passe le `HeatmapCache` à l'algorithme génétique → lookups O(1)

### 5. XGBoost V3 (fallback)

```bash
cd backend && python scripts/train_control_scorer.py --phase xgboost
```

**Métriques V3 (238k patches) :** AUC=0.807, Recall=0.789, F1=0.645

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

# Indexer le dataset Vikazimut (3486 parcours XML/KML + GPX)
python scripts/index_vikazimut.py
python scripts/index_vikazimut.py --check-speed   # flag traces VTT suspectes (~5 min)
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

## Dataset Vikazimut

3 486 parcours de course d'orientation français téléchargés depuis [Vikazimut.fr](https://vikazimut.vikazim.fr) — données anonymisées, libres de droit.

| Type | Quantité |
|------|---------|
| Parcours XML IOF 3.0 + KML géoréférencement | 3 486 |
| Traces GPX coureurs | 13 264 |
| Cartes JPG géoréférencées | 4 405 |
| **Foot-O conservés** (après filtre VTT/MTBO) | **2 851** |
| Disciplines | urbano (895), foresto (1089), mtbo (348 exclus), skio (15) |

Le script `backend/scripts/index_vikazimut.py` parse les XML IOF 3.0, filtre les parcours VTT-O (discipline, course_type, distance > 20 km) et produit `vikazimut/index.json`.

Usage prévu : patches d'entraînement XGBoost sur cartes françaises, heatmaps de pénétrabilité réelle depuis les traces GPX.

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
