# AItraceur — Document de référence

> **Ce fichier est mis à jour automatiquement après chaque étape.**
> À chaque nouvelle session, je (Claude) le lis en premier pour savoir où on en est.

---

## 🔖 Progression actuelle

| Champ | Valeur |
|-------|--------|
| **Dernière étape complétée** | Étape 0 — Fondations (Git + STATUS.md + check.sh) |
| **Date** | 2026-02-26 |
| **Prochaine étape** | Étape 1a — Ajouter `sharp` à tile-service/package.json |
| **État global** | 🟡 Fondations en place, bugs à corriger |

---

## 📋 Checklist des étapes

- [x] **Étape 0** — Fondations (Git, STATUS.md, check.sh) ✅ 2026-02-26
- [ ] **Étape 1a** — Ajouter `sharp` à tile-service/package.json
- [ ] **Étape 1b** — Corriger calcul distance (Euclidien → Haversine) dans ai_generator.py
- [ ] **Étape 1c** — Protéger appel Ollama dans local_rag.py
- [ ] **Étape 1d** — Compléter OSM fetcher (forêts, eau, bâtiments)
- [ ] **Étape 2a** — Créer backend/tests/test_endpoints.py
- [ ] **Étape 2b** — Créer backend/tile-service/test.js
- [ ] **Étape 2c** — Intégrer tests dans check.sh
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
| 1 | `sharp` absent de package.json | `backend/tile-service/package.json` | 🔴 Critique | ❌ |
| 2 | Distance Euclidienne au lieu d'Haversine | `backend/src/services/generation/ai_generator.py` | 🟠 Important | ❌ |
| 3 | Pas de gestion d'erreur si Ollama absent | `backend/src/services/knowledge_base/local_rag.py` | 🟠 Important | ❌ |
| 4 | OSM fetcher : seulement les routes récupérées | `backend/src/services/terrain/osm_fetcher.py` | 🟡 Moyen | ❌ |
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
| Analyse terrain OSM | ⚠️ | Seulement les routes pour l'instant |
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

> Tests non encore créés — voir Étape 2.

| Test | Résultat | Dernière exécution |
|------|----------|-------------------|
| Backend health | ⏳ Non créé | — |
| Circuits CRUD | ⏳ Non créé | — |
| Génération circuit | ⏳ Non créé | — |
| Export IOF XML | ⏳ Non créé | — |
| Tile service health | ⏳ Non créé | — |

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

---

*Document géré automatiquement par Claude Code. Ne pas modifier manuellement sauf indication contraire.*
