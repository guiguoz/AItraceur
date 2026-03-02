# AItraceur — Document de référence

> **Ce fichier est mis à jour automatiquement après chaque étape.**
> À chaque nouvelle session, je (Claude) le lis en premier pour savoir où on en est.

---

## 🔖 Progression actuelle

| Champ | Valeur |
|-------|--------|
| **Dernière étape complétée** | Étape 2c — Tests intégrés dans check.sh (25/25 tests passent) |
| **Date** | 2026-03-02 |
| **Prochaine étape** | Étape 3a — Audit génération : que propose l'IA aujourd'hui ? |
| **État global** | 🟢 Fondations solides, 4 bugs corrigés, tests automatiques actifs |

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
- [ ] **Étape 3a** — Audit génération : que propose l'IA aujourd'hui ?
- [ ] **Étape 3b** — Améliorer scorer (attractivité des postes)
- [ ] **Étape 3c** — Vérifier cohérence des échelles (sprint vs classique)
- [ ] **Étape 4** — LIDAR / WMS (décision + implémentation)
- [ ] **Étape 5a** — Vérifier état Ollama + ffco-iof-v7
- [ ] **Étape 5b** — Créer dataset RAG minimal

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
| 5 | LIDAR = simulation uniquement | `backend/src/services/terrain/lidar_manager.py` | 🔵 Long terme | ❌ |
| 6 | Dataset RAG manquant | `Lora/mondial_tracage_QR_v4.jsonl` | 🟡 Moyen | ❌ |

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
| LIDAR IGN | ⚠️ | Simulation uniquement |
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

---

*Document géré automatiquement par Claude Code. Ne pas modifier manuellement sauf indication contraire.*
