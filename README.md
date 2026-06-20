# AItraceur — Générateur IA de tracés d'orientation

> Outil web d'aide à la conception de circuits d'orientation (CO), assisté par intelligence artificielle.
> Web tool for AI-assisted orienteering course design.

---

## État du développement — Juin 2026

### Bugs connus

| Priorité | Symptôme | Cause identifiée | Statut |
|----------|----------|-----------------|--------|
| **Haute** | Circuits sprint 2× trop longs (5–6 km pour cible 2 800 m) | GA converge vers ~5 800 m — discipline distance défaillante, terrain GA restreint | Fix C8 en cours — résultat post-fix à valider après le prochain run |
| **Haute** | Raster forbidden mask sur-agressif | `_building_px` détecte les zones pavées comme bâtiments → 91 % des circuits mouraient en death penalty → espace GA quasi-nul sur cartes sprint | Fix 2026-06-14 : passage à pénalité douce −20 pts/poste, mutations libres sur tout le terrain |
| **Moyenne** | Départ utilisateur "déplacé" dans les suggestions | La 2e suggestion affiche un départ différent du départ posé par l'utilisateur | Cause non identifiée (frontend/backend) — investigation en attente |
| **Basse** | Durée génération sprint ~360 s | GA 100 gen × 30 chromosomes, `_calculate_total_length` 2×O(N) par mutation | Non adressé |

### Diagnostic disponible dans la console backend

```
[heatmap-debug] forbidden=X%          → % de la carte marquée interdite
[mask-debug] ctrl=(lat,lng)           → 10 premières positions pénalisées par le mask raster
[death-summary] total=N oob_vector=X cnn_low=Y raster_forbidden=Z  → causes de mort GA
[diversity-distance] dist=[a..b]m mean=Xm target=Ym                → longueur des circuits sortants
```

`backend/debug/forbidden_mask_debug.png` — carte OCAD avec zones interdites en rouge (généré automatiquement à chaque build HeatmapCache). Doit couvrir uniquement les bâtiments (gris OCAD) et les zones olive hors-limites.

### Fixes récents (sessions 2026-06-13/14)

| Fix | Fichier(s) | Description |
|-----|-----------|-------------|
| A5 CRS forbidden zones | `tile-service/server.js` | Polygones Lambert-93 → WGS84 via `transformGeoJsonCrs` |
| A6 Fallback postes clippés | `main.py` | Restaure `best_latlng` si < `max(3, n//2)` postes intérieurs survivent |
| C1 Crossing penalty | `genetic_algo.py` | `W_CROSSING=50` — pénalité croisement de jambes actif |
| C8a Target sprint | `frontend/src/App.jsx` | Cible sprint 2 200 m → **2 800 m** (FFCO H21E correct) |
| C8b Overshoot mutation | `genetic_algo.py` | Rejet si `new_len > 1.5×target AND new_len > curr_len` |
| C8 Smart seeding local | `genetic_algo.py` | Candidats CNN limités à ±2×target_leg_m (≈350 m) du poste courant |
| C8 Raster mask → douce | `genetic_algo.py` | `is_forbidden()` : pénalité −20 pts/poste (plus death penalty) |
| OOB start/finish fix | `genetic_algo.py` | Death penalty OOB vectoriel sur `controls[1:-1]` (départ/arrivée exclus) |
| PNG debug mask | `ocad_patch_scorer.py` | `forbidden_mask_debug.png` généré à chaque sprint dans `backend/debug/` |

### Règle de stabilité des poids GA

> Ne pas modifier `W_AI`, `W_DIST`, `W_SHAPE`, `H4`, `W_SCENARIO`, seuil CNN death penalty (0.01), ni les polygones OOB vectoriels sans mesures préalables (`[fitness-debug]` + `[death-summary]`). Le raster forbidden mask est désormais une pénalité douce — calibration en cours.

---

## Fonctionnalités

- **Génération automatique** de circuits sprint (urbain) et forêt via algorithme génétique multi-objectifs
- **Sprint asynchrone** : POST retourne `task_id` en <100ms, pipeline en arrière-plan (~35s), polling GET `/sprint-status`
- **Contexte terrain manuel** : sélecteur [Auto / Urbain / Forêt] pour forcer le mode détection IA
- **Fitness multicritère A→L** : IA Score CNN (HeatmapCache), distance, dog-legs, rythme, diversité, zones interdites, D+/distance, forme géométrique, point d'attaque/arrêt/main courante, longueur jambes IOF
- **Pipeline OCAD natif** : le fichier `.ocd` uploadé alimente directement l'IA — zones interdites extraites des vecteurs (sym 709/527 ISSprOM/ISOM), image rasterisée normalisée vers la distribution MapAnt d'entraînement
- **HeatmapCache** : grille de scores V2 précomputée (O(1) lookups GA), Smart Seeding population initiale — source : OCAD tile service (priorité) ou MapAnt (fallback forêt/LD)
- **Forbidden mask vectoriel** : polygones OOB extraits directement depuis les symboles OCAD (100 % fiable) ; requête Overpass bâtiments skippée → gain ~50s
- **Ancrage vectoriel ISOM Phase 2** : postes ancrés sur les features OCAD réelles via `scipy.spatial.KDTree` (O(log N)) — pénalité si poste trop loin (rayon 40 m sprint / 80 m forêt), attractivité sémantique `ISOM_ATT` transmise depuis le frontend (`extractCandidatePoints` : contours 101-105 ignorés, chemins forêt 503-508 inclus avec extraction des vertices de changement de direction, ruisseaux 301-303 exclus pour éviter la confusion avec les lignes nord magnétiques)
- **Contrôleur IOF/FFCO** : validation automatique des règles (dog-legs, jambes C01–C16, TD1-5/PD1-5)
- **Boucle traceur ↔ contrôleur** : dialogue IA avec corrections automatiques (jusqu'à 5 itérations)
- **FFCORulesEngine** : source de vérité unique pour les seuils FFCO/IOF — distances, TD, temps gagnants par catégorie exposés via `GET /api/v1/categories` ; seuils injectés dans le GA (remplace les constantes hardcodées)
- **Détection circuit impossible** : score GA < -5000 → erreur explicite ; distance < 70 % cible → `warning` dans la réponse
- **Analyse de routes** : NetworkX A*, diversité des itinéraires (Jaccard), détection dog-legs, Re-Ranker Top-3 (budget 15s) ; bouton 🔍 par jambe → k polylines colorées sur la carte (bleu/orange/rouge)
- **DialogueLog** : panneau visuel des échanges traceur↔contrôleur avec score IOF/FFCO par itération
- **Diversification inter-runs** : 3 variantes distinctes A/B/C par session de génération — pool multi-runs, filtrage fitness 95%, déduplication cosinus, sélection greedy (`DIVERSITY_FITNESS_RATIO=0.95`) — variantes mesurées par vecteur CourseProfile 15D
- **Signal terrain adaptatif** : détection `is_flat_signal` (std CNN < 0.05 sur la grille HeatmapCache) → fallback automatique sur features ISOM si MapAnt sans OCAD → pas de convergence en forêt
- **CourseProfile 15D** : sous-module `profiling/` — vecteur `map_coverage`, `route_choice_density`, `alternation`, `geo_center_x/y`, `geo_spread_x/y`, etc. — mesure la diversité entre variantes A/B/C par distance cosinus
- **RCD (route_choice_density)** : fraction de jambes où ≥2 itinéraires distincts existent (Jaccard > 0.30, via RouteAnalyzer k-shortest timeout 150ms) — signal non redondant avec fitness (r=0.566, validé sur 3 types de terrain)
- **Avertissement génération** : si circuit < 70 % de la distance cible → `warning` + `distance_ratio` affichés dans l'interface (fond orange)
- **Complétion de circuit** : si le circuit validé est sous la distance cible, l'IA propose des postes supplémentaires via `/generate-circuit` avec `required_controls` — chaque suggestion s'intercale dans la jambe géométriquement la plus proche (`insertAfterId` + label "intercaler entre poste #X → poste #Y"), OCAD params (map_id, candidate_points CNN) transmis pour maintenir la qualité forêt
- **CNN Scorer V4** : MobileNetV3-Small ONNX (6.1 MB), F1=0.814, Recall=0.919 — 428k patches (RG2 UK + Vikazimut FR), entraîné sur Kaggle T4 GPU ; fallback XGBoost V3 (AUC=0.807) si `.onnx` absent
- **map_scale adaptatif** : échelle OCAD extraite du `.ocd` → `scale_min_separation()` adapte `min_control_separation_m` à l'échelle (refs IOF sprint=4000 / md=10000 / ld=15000, LD vétérans 1:10000 → 40m)
- **Carte OCAD** : rendu haute-fidélité des fichiers `.ocd` via tile service Node.js
- **Terrain OSM** : enrichissement automatique depuis Overpass API (highways pour RouteAnalyzer)
- **Export** : IOF XML 3.0, GPX, PDF, KML/KMZ — à importer dans OCAD pour le tracé final
- **RAG local** : 22 PDF IOF/FFCO indexés, chaîne LLM (OpenAI → fallback local)

---

## Roadmap

### Priorité immédiate — C8 Discipline distance (en cours)

Le GA sprint produit des circuits à 5–6 km pour une cible de 2 800 m. Trois correctifs appliqués en session 2026-06-14 (voir tableau fixes ci-dessus) — validation du prochain run en attente.

**Hypothèse post-fix :** avec le raster mask en pénalité douce, le GA peut désormais explorer les zones pavées (trottoirs, intersections) qui étaient faussement classées "bâtiment". Le smart seeding local (±350 m) devrait contraindre l'initialisation près de la longueur cible.

**Indicateurs de succès :** `[diversity-distance] dist=[2400..3500]m mean≈2800m err_mean<400m`

### Conscience globale de la carte (backlog)

**Constat** : AItraceur est localement intelligent, globalement aveugle. Le GA place les postes un à un et mesure le résultat global *après*. Un traceur humain lit la carte, identifie les zones riches, conçoit un scénario, puis place les postes. Ce gap est adressé par couches :

| Couche | Statut | Contenu |
|--------|--------|---------|
| **0 — Segmentation de carte** | Implémenté (validation en attente) | k-means (k=3) sur `scores_grid` HeatmapCache → zones riches/modérées/pauvres ; `zone_coverage`, `zone_diversity` dans `CourseProfile` |
| **1 — Descripteurs mixtes** | Backlog | Labels absolus calibrés Atlas (p75 Vikazimut) + labels carte-relatifs — titre automatique "Exploratoire, multi-zone" etc. |
| **2 — Scénario pré-génération** | Backlog long terme | Avant GA : choisir un scénario narratif adapté aux zones détectées → soft constraint GA |

### Autres backlog

- **C6 Seeding géographique diversifié** : zones spatiales par run (implémenté, non validé — bloqué par C8)
- **Boucles papillon LD** : terme fitness figure-8 + check contrôleur (prérequis Segment Crossover ✅)
- **Déploiement prod**
- **Départ déplacé dans les suggestions** : investigation frontend/backend en attente

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

À l'appel de `/generate-sprint` **et `/generate-circuit`** (forêt/LD/MD), le backend :
1. **Si `.ocd` uploadé (`map_id` fourni)** :
   - Extrait les zones OOB depuis les vecteurs OCAD (sym 709/527) → `forbidden_mask` fiable à 100%
   - Récupère le PNG pleine-carte rendu par le tile service
   - Normalise les couleurs OCAD → distribution MapAnt (`style_normalizer.py`)
2. **Sinon** : récupère l'image MapAnt (`_fetch_mapant_bbox_image`)
3. Précompute une grille de scores CNN (`build_heatmap_cache`) — `CnnPatchScorer` si `.onnx` présent, XGBoost sinon
4. Passe le `HeatmapCache` à l'algorithme génétique → lookups O(1)

> Le frontend transmet `candidate_points` (jusqu'à 600, filtrés bbox + OOB) et les paramètres OCAD dans **toutes** les requêtes de génération, y compris la complétion de circuit (`handleCompleteCircuit`).

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
