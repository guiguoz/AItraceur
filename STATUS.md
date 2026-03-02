# AItraceur — Document de référence

> **Ce fichier est mis à jour automatiquement après chaque étape.**
> À chaque nouvelle session, je (Claude) le lis en premier pour savoir où on en est.

---

## 🔖 Progression actuelle

| Champ | Valeur |
|-------|--------|
| **Dernière étape complétée** | Étape 5b — Dataset RAG 54 Q/R (mondial_tracage_QR_v4.jsonl) |
| **Date** | 2026-03-02 |
| **Prochaine étape** | Étape 5d — Analyse multi-GPX consensus |
| **État global** | 🟢 13 bugs corrigés, RAG actif (54 Q/R, scores 0.70-0.78), 3 circuits IOF valides |

---

## 📋 Checklist des étapes

- [x] **Étape 0** — Fondations (Git, STATUS.md, check.sh) ✅ 2026-02-26
- [x] **Étape 1a** — Ajouter `sharp` à tile-service/package.json ✅ 2026-02-26
- [x] **Étape 1b** — Corriger calcul distance (Euclidien → Haversine) dans ai_generator.py ✅ 2026-02-26
- [x] **Étape 1c** — Protéger appel Ollama dans local_rag.py ✅ 2026-02-26
- [x] **Étape 1d** — Compléter OSM fetcher (forêts, eau, bâtiments) ✅ 2026-02-26
- [x] **Étape 2a** — Créer backend/tests/test_endpoints.py (13/13 tests) ✅ 2026-02-26
- [x] **Étape 2b** — Créer backend/tile-service/test.js (12/12 tests) ✅ 2026-03-02
- [x] **Étape 2c** — Tests intégrés dans check.sh (18/18 vérifications) ✅ 2026-03-02
- [x] **Étape 3a** — Audit génération + 3 bugs corrigés (scorer, genetic_algo) ✅ 2026-03-02
- [x] **Étape 3b** — Convergence circuits longs (pop. intelligente + mutations scalées) ✅ 2026-03-02
- [x] **Étape 3c** — Cohérence des échelles + too_close Haversine ✅ 2026-03-02
- [x] **Étape 4** — IGN altimétrie API (élévation réelle via data.geopf.fr) ✅ 2026-03-02
- [x] **Étape 5a** — System prompt CO/IOF injecté, API REST Ollama, 13/13 tests ✅ 2026-03-02
- [x] **Étape 5b** — Dataset RAG 54 Q/R créé (mondial_tracage_QR_v4.jsonl) ✅ 2026-03-02

---

## 🏗️ Architecture des 3 services

| Service | Port | Démarrage | État |
|---------|------|-----------|------|
| Backend FastAPI | 8000 | `cd backend && uvicorn src.main:app --reload` | ✅ Opérationnel |
| Frontend React | 5173 | `cd frontend && npm run dev` | ✅ Opérationnel |
| Tile service Node.js | 8089 | `cd backend/tile-service && node server.js` | ✅ Opérationnel |

**Note :** Le frontend est ce que l'utilisateur voit dans son navigateur à l'adresse `http://localhost:5173`

---

## 🐛 Bugs connus

| # | Bug | Fichier | Priorité | Résolu ? |
|---|-----|---------|----------|----------|
| 1 | `sharp` absent de package.json | `backend/tile-service/package.json` | 🔴 Critique | ✅ commit fb81867 |
| 2 | Distance Euclidienne au lieu d'Haversine | `backend/src/services/generation/ai_generator.py` | 🟠 Important | ✅ commit 12a9faf |
| 3 | Pas de gestion d'erreur si Ollama absent | `backend/src/services/knowledge_base/local_rag.py` | 🟠 Important | ✅ commit 05d56a1 |
| 4 | OSM fetcher : seulement les routes récupérées | `backend/src/services/terrain/osm_fetcher.py` | 🟡 Moyen | ✅ commit 3112574 |
| 5 | LIDAR = simulation uniquement | `backend/src/services/terrain/lidar_manager.py` | 🔵 Long terme | ⚠️ Partiel — API IGN altimétrie intégrée (1m), nuage de points LIDAR = futur |
| 6 | Dataset RAG manquant | `Lora/mondial_tracage_QR_v4.jsonl` | 🟡 Moyen | ✅ 54 Q/R (TD1-5, PD1-5, IOF, symboles ISOM, circuits, formats) |
| 7 | scorer.py — Euclidien en degrés au lieu de Haversine en mètres | `backend/src/services/generation/scorer.py` | 🔴 Critique | ✅ commit 1214e84 |
| 8 | genetic_algo.py — mutations ±50° au lieu de ±50m | `backend/src/services/generation/genetic_algo.py` | 🔴 Critique | ✅ commit 1214e84 |
| 9 | genetic_algo.py — OX crossover IndexError (départ==arrivée) | `backend/src/services/generation/genetic_algo.py` | 🟠 Important | ✅ commit 1214e84 |
| 10 | genetic_algo.py — OX crossover IndexError (p2_idx ≥ n avant break) | `backend/src/services/generation/genetic_algo.py` | 🟠 Important | ✅ Étape 3b |
| 11 | genetic_algo.py — pop. initiale trop étalée → circuits longs 2× trop longs | `backend/src/services/generation/genetic_algo.py` | 🔴 Critique | ✅ Étape 3b |
| 12 | genetic_algo.py — too_close en degrés Euclidiens (jamais actif) → Haversine 60m | `backend/src/services/generation/genetic_algo.py` | 🟠 Important | ✅ Étape 3c |
| 13 | ai_generator.py — min_control_distance fixe (60m) sans différencier sprint/classique | `backend/src/services/generation/ai_generator.py` | 🟡 Moyen | ✅ Étape 3c |

---

## ✅ État des fonctionnalités

### Backend FastAPI
| Fonctionnalité | État | Notes |
|---------------|------|-------|
| Santé API (`/health`) | ✅ | |
| CRUD circuits | ✅ | |
| Upload carte OCAD (overlay) | ✅ | |
| Analyse terrain OSM | ✅ | Routes + forêts + eau + bâtiments + barrières |
| Grille de runnabilité | ✅ | |
| Profil d'élévation | ✅ | |
| LIDAR IGN | ⚠️ | API IGN altimétrie intégrée (1m réel), nuage LIDAR = futur |
| Génération de circuit (algo génétique) | ✅ | |
| Génération de circuit (IA / GPT) | ✅ | Nécessite clé OpenAI |
| Scoring IOF (TD/PD/dog-legs) | ✅ | |
| Analyse de problèmes | ✅ | |
| Estimation du temps | ✅ | Tobler + multiplicateurs terrain |
| A* pathfinding | ✅ | |
| Export IOF XML 3.0 | ✅ | |
| Export GPX | ✅ | |
| Export PDF | ✅ | |
| Export KML/KMZ | ✅ | |
| Import IOF XML | ✅ | |
| Import KML/KMZ | ✅ | |
| AI chat (questions CO/IOF) | ✅ | OpenAI → Ollama → démo |
| Analyse RouteGadget | ✅ | |
| Analyse Livelox | ✅ | |

### Frontend React
| Fonctionnalité | État | Notes |
|---------------|------|-------|
| Upload .ocd (drag & drop) | ✅ | |
| Affichage carte OCAD (tuiles PNG) | ✅ | Via tile service |
| Affichage carte OCAD (fallback canvas) | ✅ | Si tile service absent |
| Placement départ / postes / arrivée | ✅ | |
| Zones interdites | ✅ | |
| Heatmap runnabilité | ✅ | |
| Génération AI de circuit | ✅ | |
| Panneau AI chat | ✅ | |
| Export IOF XML | ✅ | |
| Multi-circuits | ✅ | |

### Tile service Node.js
| Fonctionnalité | État | Notes |
|---------------|------|-------|
| Rendu OCAD → PNG | ✅ | Via ocad2tiles + sharp |
| Conversion CRS → WGS84 | ✅ | Lambert-93 et autres |
| Cache des rendus | ✅ | `/renders/` |

---

## 🧪 État des tests (mis à jour après `./check.sh`)

> `./check.sh` lance automatiquement les 2 suites de tests.

| Suite | Tests | Résultat | Dernière exécution |
|-------|-------|----------|-------------------|
| Backend (pytest) | health, root, circuits CRUD, scorer, export IOF/GPX, haversine x2, OSM query x2, Ollama fallback | ✅ 13/13 | 2026-03-02 |
| Tile service (node) | dépendances x6, CRS Lambert-93, SVG→PNG, structure server.js x4 | ✅ 12/12 | 2026-03-02 |

---

## 🔧 Comment démarrer le projet

### Prérequis
- Python 3.11+ (`python --version`)
- Node.js 18+ (`node --version`)
- Optionnel : Ollama pour l'IA locale (`ollama --version`)
- Optionnel : clé OpenAI dans `backend/.env`

### Démarrage (3 terminaux)
```bash
# Terminal 1 — Backend
cd backend
pip install -r requirements.txt  # première fois
uvicorn src.main:app --reload

# Terminal 2 — Tile service
cd backend/tile-service
npm install  # première fois
node server.js

# Terminal 3 — Frontend
cd frontend
npm install  # première fois
npm run dev
```

Ouvrir le navigateur : http://localhost:5173

### Vérification rapide
```bash
# Depuis la racine du projet :
./check.sh
```

---

## 📝 Journal des étapes

### Étape 0 — Fondations ✅ (2026-02-26)
- Git initialisé (`git init`)
- `.gitignore` créé (Python + Node + données volumineuses)
- `STATUS.md` créé (ce fichier)
- `check.sh` créé (vérification rapide)
- Premier commit Git : "Baseline - état initial documenté"

### Étape 1a — Bug #1 corrigé ✅ (2026-02-26)
- `sharp` ajouté à `backend/tile-service/package.json` (commit fb81867)
- Le rendu PNG ne plantera plus après un `npm install` propre

### Étape 1b — Bug #2 corrigé ✅ (2026-02-26)
- `_calculate_length()` dans `ai_generator.py` : Euclidien → Haversine (commit 12a9faf)
- Résultat : 2 postes à 600m → 622.8m calculés (au lieu de 0.007 °)

### Étape 1c — Bug #3 corrigé ✅ (2026-02-26)
- `demander_ollama()` dans `local_rag.py` protégé par try/except (commit 05d56a1)
- Plus de crash si Ollama est absent ; retourne `None` avec message `[WARNING]`

### Étape 1d — Bug #4 corrigé ✅ (2026-02-26)
- `build_overpass_query()` dans `osm_fetcher.py` complété (commit 3112574)
- Maintenant : routes + bâtiments + landuse + eau + zones vertes + barrières
- `out body;` → `out body geom;` (coordonnées des ways incluses)

### Étape 2a — Tests backend ✅ (2026-02-26)
- `backend/pytest.ini` créé (asyncio_mode=auto)
- `backend/tests/conftest.py` créé (DB SQLite in-memory + StaticPool + fixture client)
- `backend/tests/test_endpoints.py` créé : 13/13 tests passent
- Couvre : health, CRUD, scorer, exports, haversine, OSM query, Ollama fallback

### Étape 2b — Tests tile service ✅ (2026-03-02)
- `backend/tile-service/test.js` créé : 12/12 tests passent (commit 916bdce)
- Couvre : dépendances npm, conversion CRS Lambert-93→WGS84, SVG→PNG, structure server.js

### Étape 2c — Tests dans check.sh ✅ (2026-03-02)
- `check.sh` section [4/5] lance automatiquement pytest et node test.js
- 18/18 vérifications passent (services hors ligne = info, pas erreur)

### Étape 3a — Audit génération + 3 bugs corrigés ✅ (2026-03-02)
- Script `backend/tests/audit_generation.py` créé (lancer : `cd backend && python tests/audit_generation.py`)
- 3 bugs critiques découverts et corrigés (commit 1214e84) :
  - **Bug #7** : `scorer.py` — 4 endroits utilisaient Euclidien en degrés → Haversine en mètres. Résultat : TD était toujours TD1, PD5 systématique, tous les postes "trop proches"
  - **Bug #8** : `genetic_algo.py` mutations — ±50 degrés (= 3600km !) → converti en degrés WGS84 (÷ 72600 lng, ÷ 111000 lat)
  - **Bug #9** : OX crossover IndexError pour circuits où départ==arrivée → garde copie si None détecté

- **Résultats après corrections** (zone 49.19°N 5.50°E) :

  | Circuit | Longueur | Cible | Écart | Score | TD | IOF |
  |---------|----------|-------|-------|-------|-----|-----|
  | Sprint TD2 (D21, 8 postes) | 1753m | 2000m | -12% | 79/100 [C] | TD3 | ✅ |
  | Classique TD3 (H21, 12 postes) | 4317m | 4000m | +8% | 82/100 [B] | TD3 | ⚠️ 1 dog-leg |
  | Long TD4 (H21E, 15 postes) | 14243m | 7000m | +103% | 72/100 [C] | TD5 | ✅ |

- **Problème restant** : Circuits longs (>5km) convergent mal (50 générations insuffisantes, placement initial trop écarté) → **résolu en Étape 3b**

---

### Étape 3c — Cohérence des échelles ✅ (2026-03-02)
- **Bug #12** corrigé : `too_close` dans la fitness GA utilisait Euclidien en degrés → jamais actif (100° ≈ 11 000km). Remplacé par Haversine mètres.
- **Bug #13** corrigé : `min_control_distance` passé de 100 (degrés, inutilisable) à 60m (IOF AA3.5.5). Sprint (TD1/TD2) → 30m ; forêt (TD3-TD5) → 60m.
- Résultat : plus de "trop proches" dans la fitness → l'algo les pénalise activement dès la génération

**Résultats après Étape 3c** :

| Circuit | Longueur | Cible | Écart | Score | Dog-legs | Trop proches | IOF |
|---------|----------|-------|-------|-------|----------|-------------|-----|
| Sprint TD2 | 2016m | 2000m | +0.8% | 86.5/100 [B] | 0 | 0 | ✅ |
| Classique TD3 | 3754m | 4000m | -6.2% | 78.1/100 [C] | 0 | 0 | ✅ |
| Long TD4 | 7991m | 7000m | +14.2% | 84.8/100 [B] | 0 | 0 | ✅ |

- **Problème résiduel** : `balance_score` moyen à 45/100 (déséquilibre des distances entre interpostes). À adresser si nécessaire dans une future étape.

---

### Étape 3b — Convergence circuits longs ✅ (2026-03-02)
- **Bug #10** corrigé : OX crossover IndexError quand `p2_idx ≥ n` avant le `break` (affectait les circuits longs avec pop. smart)
- **Bug #11** corrigé : Population initiale 100% aléatoire dans la bbox → circuits longs 2× trop longs (length_score=0 dès génération 0, pas de gradient)
- **Fix 1** : `_create_smart_circuit()` dans `genetic_algo.py` — place les postes à ~target_leg_m du précédent (±40%), crée des circuits initiaux proches de la cible
- **Fix 2** : Générations et population scalées dans `ai_generator.py` — `pop = max(30, n×3)`, `gens = max(50, n×7)` (8 postes → 56 gens, 15 postes → 105 gens)
- **Fix 3** : Mutations proportionnelles à la jambe cible — ±12% walk, ±25% perturbation (vs ±50m/±100m fixe)

**Résultats après Étape 3b** (zone 49.19°N 5.50°E) :

| Circuit | Longueur | Cible | Écart | Score | Avant |
|---------|----------|-------|-------|-------|-------|
| Sprint TD2 (D21, 8 postes) | 2115m | 2000m | +5.8% | 82/100 [B] | 1753m (-12%) |
| Classique TD3 (H21, 12 postes) | 3861m | 4000m | -3.5% | 90/100 [A] | 4317m (+8%) |
| Long TD4 (H21E, 15 postes) | 7831m | 7000m | +11.9% | 70/100 [D] | 14243m (+103%) ✅ |

- **Problème résiduel** : Long TD4 a 1 paire de postes trop proches (<60m) non pénalisée par la fitness GA (le scorer le détecte). La fitness equity utilise encore Euclidien en degrés pour `too_close`. → Étape 3c

---

### Étape 4 — IGN altimétrie API ✅ (2026-03-02)
- **Bug #5 partiellement résolu** : `lidar_manager.py` était 100% simulation (fichiers LAZ fictifs, rasters .tif vides)
- **Décision** : API IGN altimétrie REST (data.geopf.fr) choisie à la place de PDAL/LAZ — gratuite, sans authentification, résolution 1m (RGE Alti) sur France
- 3 nouvelles fonctions module-level dans `lidar_manager.py` :
  - `get_elevation_for_points(coords)` — batch API, retourne `[z1, z2, ...]` en mètres
  - `get_elevation_profile(coords, chunk_size=100)` — chunked pour >100 points
  - `calculate_climb(elevations)` — calcule D+ depuis une liste d'élévations
- **Test validé** : zone 49.19°N 5.50°E → 247.2m, 251.89m, 240.67m (données réelles IGN RGE Alti 1m)
- **Nuage de points LIDAR** (LAZ IGN) reste futur — dépend de disponibilité PDAL + ~100Mo/zone

---

### Étape 5a — System prompt CO/IOF + API REST Ollama ✅ (2026-03-02)
- **Diagnostic** : `ffco-iof-v7` répondait "Temps Disparu" pour TD3 (complètement faux) — le subprocess `ollama run` n'injectait aucun contexte CO/IOF
- **Fix 1** : `demander_ollama()` passe maintenant par l'API REST `/api/chat` (requests) avec `role: "system"` → system prompt CO/IOF complet injecté à chaque requête
- **Fix 2** : Fallback subprocess conservé si REST échoue (Ollama absent = None retourné)
- **System prompt** (`_SYSTEM_PROMPT_CO`) contient :
  - Tableau TD1-TD5 (terrain, public, postes)
  - Tableau PD1-PD5 (D+/km, catégories)
  - Règles IOF clés (60m min, dog-leg, temps victoire)
  - 3 exemples few-shot (TD3, distance min, dog-leg)
- **Résultats après fix** : TD3 → "niveau technique moyen, postes sur formes de terrain" ✅, 60m IOF AA3.5.5 ✅, H21E 45-60min ✅
- Test `test_ollama_fallback_on_missing` mis à jour (mock REST + subprocess) → 13/13 ✅

---

### Étape 5b — Dataset RAG 54 Q/R ✅ (2026-03-02)
- **Bug #6 résolu** : `Lora/mondial_tracage_QR_v4.jsonl` créé de zéro avec 54 paires Q/R
- 8 thèmes couverts : TD1-5, PD1-5, règles IOF (distance min, dog-leg, départ, arrivée), temps de victoire, symboles ISOM (101/109/118/201/210/301/401/404), circuits par couleur (Blanc→Noir), formats d'export (IOF XML, GPX, KML), navigation CO (runnabilité, Tobler, equity)
- **Résultats RAG** :
  - "distance minimale postes" → score 0.78 (exact_match direct, ≥0.65) ✅
  - "TD3" → score 0.70 (exact_match direct) ✅
  - "dog-leg" → score 0.59 (Ollama + contexte RAG, entre 0.35-0.65) ✅
- `local_rag.py` charge 54 Q/R, modèle SentenceTransformer indexé

---

*Document géré automatiquement par Claude Code. Ne pas modifier manuellement sauf indication contraire.*
