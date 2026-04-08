# CLAUDE.md — AItraceur

Instructions pour assistants IA travaillant sur ce projet.

---

## Démarrage rapide

```bash
# Backend (Python 3.11+)
cd backend && uvicorn src.main:app --reload   # → port 8000

# Frontend (Node 18+)
cd frontend && npm run dev                    # → port 5173

# Tile Service (requis pour rendu OCAD)
cd backend/tile-service && node server.js     # → port 8089
```

L'utilisateur accède au frontend sur **5173**. Le backend est sur **8000**, le tile service sur **8089**.

---

## Fichiers critiques

| Fichier | Rôle |
|---------|------|
| `backend/src/main.py` | FastAPI, ~47 endpoints — point d'entrée backend |
| `backend/src/services/generation/genetic_algo.py` | Algorithme génétique multi-objectifs |
| `backend/src/services/learning/ocad_patch_scorer.py` | `CnnPatchScorer` + `HeatmapCache` |
| `backend/src/services/controleur/controleur.py` | `ControleurSprint`, checks C01–C12 IOF/FFCO |
| `backend/src/services/optimization/route_analyzer.py` | RouteAnalyzer, A* NetworkX |
| `backend/data/models/control_scorer_cnn.onnx` | Modèle CNN V4 en prod (6.1 MB) |
| `frontend/src/App.jsx` | Composant React principal |
| `frontend/src/components/MapViewer.jsx` | Leaflet, tiles, contrôles |
| `backend/tile-service/server.js` | Rendu OCAD `.ocd` → PNG tiles |

---

## Architecture clé

### Pattern Task-Status (génération sprint async)

La génération sprint prend ~35s — trop long pour une requête HTTP synchrone.

```
POST /api/v1/generation/generate-sprint
  → {task_id, status: "processing"}   # retour immédiat <100ms

GET /api/v1/generation/sprint-status/{task_id}
  → polling 2s frontend, max 150s
```

`_sprint_tasks` est un dict en mémoire — perdu au restart uvicorn.

### CNN Scorer V4

Le scorer principal est un **MobileNetV3-Small** exporté en ONNX.

```python
# ocad_patch_scorer.py
CnnPatchScorer.load()                        # charge control_scorer_cnn.onnx via onnxruntime
build_heatmap_cache(cnn_scorer=cnn)          # branche CNN si .onnx présent
# Fallback automatique → XGBoost V3 si .onnx absent
```

- **Modèle** : `backend/data/models/control_scorer_cnn.onnx`
- **Métriques** : F1=0.814, Recall=0.919 (epoch 18, 20 epochs total)
- **Dataset** : 428k patches PNG 256×256 (RG2 UK + Vikazimut FR)
- **Entraînement** : `backend/scripts/train_control_scorer_kaggle.py` (Kaggle GPU T4)

### HeatmapCache

Avant chaque génération GA, une grille de scores est précalculée sur toute la bbox :
- Source : OCAD tile service (priorité) ou MapAnt (fallback forêt)
- Lookup O(1) dans le GA → rend l'évaluation fitness rapide
- `build_heatmap_cache()` dans `ocad_patch_scorer.py`

### Boucle traceur ↔ contrôleur

```
GA génère circuit
  → ControleurSprint.check() (C01–C12 IOF/FFCO)
  → corrections automatiques si violations
  → max 5 itérations
  → retourne dialogue JSON + rapport final
```

---

## Conventions

- **OCAD optionnel** : l'app fonctionne sans `.ocd` — bbox = viewport Leaflet
- **`force_mode`** : `None` (Auto) / `"urban"` / `"forest"` — écrase la détection IA
- **Tile service sans état** : restart = toutes les cartes perdues (re-upload `.ocd` requis)
- **SQLite** par défaut (`aitraceur.db`) — pas besoin de Docker en dev
- **`global_score`** est dans [0, 100] — diviser par 100 pour obtenir [0, 1]

---

## Re-entraîner le CNN

Les 4 datasets Kaggle sont sur le compte `guillaumelemigre` :
- `aitraceur-rg2-pos`, `aitraceur-rg2-neg`
- `aitraceur-vikazimut-pos`, `aitraceur-vikazimut-neg`

Scripts locaux :
- `backend/scripts/prepare_kaggle_datasets.py` — prépare les 4 dossiers depuis les patches locaux
- `backend/scripts/train_control_scorer_kaggle.py` — script d'entraînement avec resume/checkpoint

Le notebook Kaggle embarque le script inline (`%%writefile train_cnn.py`) pour éviter les problèmes de montage en commit mode.

---

## Backlog (par priorité)

| Priorité | Tâche |
|----------|-------|
| Haute | Déploiement prod (CORS, API_BASE, build frontend, rate limiting, clé admin) |
| Moyenne | CNN 5 canaux (RGB + altitude + pente DEM SRTM) — plan dans `~/.claude/plans/` |
| Basse | Mode Compétition (plusieurs circuits partagent des balises) |
