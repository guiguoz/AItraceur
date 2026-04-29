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
| `backend/src/services/controleur/controleur.py` | `ControleurSprint`, checks C01–C16 IOF/FFCO |
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

Avant chaque génération GA, une grille de scores CNN est précalculée sur toute la bbox :
- Source : OCAD tile service (priorité) ou MapAnt (fallback forêt)
- Lookup O(1) dans le GA → rend l'évaluation fitness rapide
- `build_heatmap_cache()` dans `ocad_patch_scorer.py`
- Actif sur `/generate-circuit` (forêt/MD/LD) **et** `/generate-sprint`
- `get_top_candidates(0.40)` filtre les pixels `forbidden_mask` avant de retourner les top-40%

### ElevationCache

Avant chaque génération GA, une grille 30×30 d'altitudes est précomputée via IGN API :
- `build_elevation_cache(bbox)` dans `lidar_manager.py` — ~900 points, batches IGN, ~10-15s
- `estimate_dplus(controls)` → D+ estimé O(N postes) sans requête réseau
- Fallback silencieux si IGN inaccessible — terme G fitness désactivé
- Actif sur `/generate-circuit` **et** `/generate-sprint`

### map_scale — Propagation échelle OCAD

L'échelle de la carte OCAD est extraite dans `OcadUploader.jsx` via `normalizeScale()` (gère string `"1:10 000"`, objet, number) et propagée jusqu'au `GenerationConfig` :

```
OcadUploader.scale → App.jsx ocadScale → request body map_scale
  → _sprint_impl / _circuit_impl → GenerationRequest.map_scale → GenerationConfig.map_scale
```

- `leg_m` est en **mètres terrain** (Haversine WGS84) → cibles terme L correctes telles quelles
- `map_scale` adapte `min_control_separation_m` (equity score) et `min_control_distance` (fallback GA) via `scale_min_separation()` (module-level `genetic_algo.py`) : `ceil(base × scale/ref)`, refs IOF sprint=4000 / md=10000 / ld=15000, clamp [15-80m] sprint / [40-150m] md+ld. LD vétérans 1:10000 → clamp bas 40m. Alias "forest"/"foret" → md.
- Terme L inchangé — distances IOF (250/600/2000m) indépendantes de l'échelle

### Fitness GA — termes A→L

| Terme | Critère | Poids |
|-------|---------|-------|
| A | Score CNN moyen (HeatmapCache) | ×30 |
| B | Pénalité distance vs cible | ×40 |
| C | Dog-legs (−20 pts/violation) | ×1 |
| D | Rythme CV inter-postes (cap 0.8) | ×15 |
| E | Diversité GPX Vikazimut — gradient `(cv−0.20)×15` | additive |
| F | Zones interdites forbidden_mask (−50 pts/poste) | additive |
| G | D+/distance > seuil IOF 4% (ElevationCache) | additive |
| H | Forme géométrique — anti-Z/spirale/accordéon | ×10 |
| I | Qualité point d'attaque (KDTree OCAD, si dispo) | ×8 centré 0.5 |
| J | Ligne d'arrêt (KDTree OCAD, si dispo) | ×6 centré 0.5 |
| K | Main courante (KDTree OCAD, si dispo) | ×5 |
| L | Conformité longueur jambes au profil format IOF (Sprint 250m, MD 600m, LD 2000m) | ×8 |

### GA — Opérateur de croisement : Segment Crossover spatial (2026-04-27)

`_segment_crossover()` remplace `_ox_crossover()` (OX TSP). L'OX traitait les coordonnées WGS84 comme des symboles de permutation — deux postes géographiquement proches étaient traités comme complètement différents.

**Algorithme :**
1. Choisir un point de coupe aléatoire `cut` dans les contrôles internes (hors départ/arrivée)
2. Ancre = `inner1[cut-1]` (dernier contrôle du premier segment de P1)
3. Trouver `j = argmin distance(ancre, inner2[k])` — le point de jonction naturel dans P2
4. Rotation de `inner2` : `rotation = (j - cut + 1) % inner_n` → `inner2_rot[cut-1] == inner2[j]`
5. `child1 = inner1[:cut] + inner2_rot[cut:]` (longueur garantie par construction)
6. `child2 = inner2_rot[:cut] + inner1[cut:]`

Départ et arrivée (`controls[0]`, `controls[-1]`) préservés depuis chaque parent respectif. Complexité O(inner_n) par paire ≈ O(8) — négligeable. `_ox_crossover()` conservé dans le code, non appelé.

**Prérequis boucles papillon LD satisfait.** Prochaine étape : terme fitness figure-8 + check contrôleur.

### Boucle traceur ↔ contrôleur

```
GA génère circuit
  → ControleurSprint.check() (C01–C16 IOF/FFCO)
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

### extractCandidatePoints (App.jsx)

Extrait les features OCAD comme candidats pour le KDTree ISOM Phase 2.
- `ATTRACTIVE_ISOM` : ensemble des codes ISOM retenus (terrain forms 101-120, végétation 201-215, constructions 304-308/401-406, sentiers/chemins forêt 501-508/516/521-522)
- **Contours 101-105** (LineString) : centroïde ignoré — points sur courbe de niveau sans signification CO
- **Terrain forms 106-115** (knolls/pits, LineString fermée) : centroïde conservé
- **PATH_ISOM 501-506** : extraction des vertices de changement de direction (> 15°, pas centroïde)
- **Ruisseaux 301-303 absents** : endpoints de LineString = bords de carte + confusion avec lignes nord magnétiques (même couleur bleue)
- `sym` parsing : `sym > 10000 ? Math.floor(sym/1000) : Math.floor(sym)` — gère formats 6-chiffres (`101000`) et 3-chiffres (`101`)

### Complétion de circuit + intercalation (App.jsx)

Quand le circuit validé est sous la distance cible :
1. `handleCompleteCircuit` appelle `/generate-circuit` avec `required_controls` (postes existants) + params OCAD complets
2. `assignInsertionPositions` attribue à chaque suggestion l'`insertAfterId` de la jambe géométriquement la plus proche (`pointToSegmentDist`, filtre MIN_LEG_M=30m)
3. `handleValidateSuggestion` insère par `insertAfterId` (pas en fin de liste)
4. `AISuggestionPanel` affiche "↕ intercaler entre X → Y"

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
| ~~Moyenne~~ | ~~Segment Crossover spatial (remplacer OX TSP)~~ — ✅ `_segment_crossover()` implémenté 2026-04-27 |
| ~~Moyenne~~ | ~~Décalage cercles CO sur carte OCAD~~ — ✅ `applyGrivation: true` dans `server.js` (2026-04-29) |
| Basse | Mode Compétition (plusieurs circuits partagent des balises) |
| Basse | Intercalation V2 : algorithme TSP cheapest-insertion (backend) pour ordre optimal des postes de complétion |

### Améliorations IOF/FFCO — hors scope actuel

Issues identifiées lors de l'audit du document IOF/FFCO (avril 2026) mais non implémentées :

| Sujet | Complexité | Prérequis |
|-------|-----------|-----------|
| **Boucles papillon LD** — vérifier et favoriser les formes en 8 (IOF LD §4.4) | Haute — terme fitness figure-8 + check contrôleur | ~~Segment Crossover~~ ✅ — prérequis satisfait ; reste : terme fitness butterfly + validation contrôleur |
| ~~**Scalabilité carte**~~ — ✅ `scale_min_separation()` — refs IOF sprint=4000/md=10000/ld=15000, `ceil`, clamp, alias forest→md | Implémenté 2026-04-25 | — |
| **Proximité arène/spectateurs sprint** (C17 IOF §3.2) — ≥1 poste visible depuis start/finish | Moyenne — nécessite coordonnées arène dans requête | Paramètre `arena_coords` optionnel dans `GenerationRequest` |
| **Apprentissage supervisé sur circuits référence** — fine-tuner le CNN sur des circuits d'experts annotés | Haute — dataset annoté requis (WRE/IOF) | CNN V4 déjà base solide (F1=0.814) |
