# AItraceur — AI-Assisted Orienteering Course Designer

> Web tool for AI-assisted orienteering (OL) course design.

---

## Features

- **Automatic course generation** for sprint (urban) and forest disciplines via multi-objective genetic algorithm
- **Async sprint** : POST returns `task_id` in <100ms, background pipeline (~35s), GET `/sprint-status` polling
- **Terrain mode selector** : [Auto / Urban / Forest] to override AI detection
- **V2 multicriteria fitness** : AI Score (HeatmapCache XGBoost), distance penalty, dog-leg detection, rhythm bonus
- **Native OCAD pipeline** : `.ocd` file feeds the AI directly — forbidden zones from OCAD vectors (sym 709/527), rasterized image normalized toward MapAnt training distribution
- **HeatmapCache** : V3 score grid precomputed (O(1) GA lookups), Smart Seeding — source: OCAD tile service (priority) or MapAnt (forest/LD fallback)
- **ISOM vector anchoring Phase 2** : controls snapped to real OCAD features via `scipy.spatial.KDTree` (O(log N)), penalty if control > 40m (sprint) / 80m (forest) from any feature
- **IOF/FFCO Controller** : automated rule validation (dog-legs, legs C01–C12, TD1-5/PD1-5)
- **Course setter ↔ controller loop** : AI dialogue with automatic corrections (up to 5 iterations)
- **FFCORulesEngine** : single source of truth for FFCO/IOF thresholds — distances, TD, winning times per category, exposed via `GET /api/v1/categories`
- **Impossible course detection** : GA fitness < -5000 → explicit error; distance < 70% of target → `warning` + `distance_ratio` displayed in UI (orange banner)
- **Route analysis** : NetworkX A*, route diversity (Jaccard), dog-leg detection, Top-3 re-ranker (15s budget) ; 🔍 button per leg → k colored polylines on map (blue/orange/red)
- **DialogueLog** : visual panel showing course setter↔controller exchanges with IOF/FFCO score per iteration
- **XGBoost V3 Scorer** : 18-dim bi-mode, `patch_scorer_v2.pkl` (AUC=0.807, Recall=0.789) — 370k RG2 patches (88 UK clubs)
- **OCAD map** : high-fidelity rendering of `.ocd` files via Node.js tile service
- **OSM terrain** : automatic enrichment from Overpass API
- **Export** : IOF XML 3.0, GPX, PDF, KML/KMZ
- **Local RAG** : 22 IOF/FFCO PDFs indexed, LLM chain (OpenAI → local Ollama fallback)

---

## Architecture

| Service | Port | Technology |
|---------|------|------------|
| Backend FastAPI | 8000 | Python 3.11+ |
| Frontend | 5173 | React + Vite |
| Tile Service | 8089 | Node.js |

---

## Installation

### Prerequisites
- Python 3.11+
- Node.js 18+
- (Optional) Ollama for local LLM fallback

### Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # edit as needed
uvicorn src.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Tile Service (optional, for OCAD maps)
```bash
cd backend/tile-service
npm install
node server.js
```

Open [http://localhost:5173](http://localhost:5173)

---

## Configuration

Copy `backend/.env.example` to `backend/.env` and configure:

```env
# Optional: OpenAI LLM (fallback to local Ollama)
# OPENAI_API_KEY=sk-...

# Database (SQLite by default, no configuration needed)
# DATABASE_URL=sqlite:///./aitraceur.db
```

---

## ML Pipeline — Control Placement Scorer (XGBoost V3)

### Overview

The `patch_scorer_v2.pkl` component is an XGBoost classifier trained to visually assess the quality of a control placement from an orienteering map tile.

### 1. Dataset Scraping (RG2)

The script `backend/scripts/scrape_rg2.py` automatically collects georeferenced controls from orienteering clubs using [RouteGadget 2](https://www.routegadget.co.uk):

```bash
cd backend && python scripts/scrape_rg2.py
```

**Results (2026-03-23 session):**
- 102 RG2 instances probed, 88 with usable data
- **370,213 positive controls** (WGS84, georeferenced)
- **740,378 non-controls** (randomly generated negative samples)
- Metadata: `lat`, `lon`, `course_type` (sprint/score/forest...), `mpp`, `event_name`

Each control generates a **256×256 PNG patch** extracted from MapAnt tiles at the appropriate zoom level.

### 2. Feature Extraction (18-dim)

Module `backend/src/services/learning/patch_feature_extractor.py`:

| Dimension | Feature | Description |
|-----------|---------|-------------|
| [0:7] | ISOM global | Pixel fraction per ISOM color class (brown/dense-green/light-green/yellow/blue/black/white) over the full 256×256 patch |
| [7:14] | ISOM centre | Same 7 colors over the central 64×64 crop (control zone) |
| [14] | `edge_density` | Fraction of pixels with Sobel gradient > 20 (geometric complexity) |
| [15] | `corner_density` | Fraction of pixels with Harris response > 1% of max (intersections, corners) |
| [16] | `entropy` | Normalized Shannon entropy [0,1] (visual richness) |
| [17] | `is_urban` | 1 if coordinates fall within a dense urban area (hardcoded UK/FR bounding boxes), else 0 |

### 3. XGBoost V3 Training (bi-mode)

```bash
cd backend && python scripts/train_control_scorer.py --phase xgboost
```

**Key parameters:**
- `n_estimators=300`, `max_depth=6`, `scale_pos_weight=2.0` (1:2 class imbalance)
- **Sample weighting**: `course_type=sprint` patches → weight 2.0×, others → 1.0× (urban sprint bias)
- Parallel feature extraction (6 workers) via `ProcessPoolExecutor`

**V3 metrics (238k patches, 88 clubs):**
| Metric | Value |
|--------|-------|
| AUC-ROC | 0.807 |
| F1 | 0.645 |
| Precision | 0.545 |
| Recall | **0.789** |

The higher Recall (+4% vs V2) means fewer legitimate controls are missed. The slightly lower AUC reflects the broader dataset diversity (forest + score + sprint disciplines).

### 4. Integration: HeatmapCache + OCAD Pipeline

When `/generate-sprint` is called, the backend:
1. **If `.ocd` uploaded (`map_id` provided)**: extracts forbidden zones from OCAD vectors (sym 709/527), fetches the full-map PNG rendered by the tile service, normalizes colors OCAD→MapAnt (`style_normalizer.py`, `match_histograms`)
2. **Otherwise (forest/LD/MD fallback)**: fetches MapAnt tiles (`_fetch_mapant_bbox_image`, 30s timeout)
3. Precomputes a V3 score grid (`scorer.build_heatmap_cache(img, bbox, mpp)`)
4. Interpolates `lng/lat` from the WGS84 `bbox` to activate the `is_urban` feature
5. Passes the `HeatmapCache` to the genetic algorithm → O(1) lookups during evolution

---

## Vikazimut Dataset

3,486 French orienteering courses downloaded from [Vikazimut.fr](https://vikazimut.vikazim.fr) — anonymized, open data.

| Type | Count |
|------|-------|
| IOF XML 3.0 courses + KML georeferencing | 3,486 |
| Runner GPS traces (GPX) | 13,264 |
| Georeferenced map images (JPG) | 4,405 |
| **Foot-O retained** (after VTT/MTBO filter) | **2,851** |
| Disciplines | urbano (895), foresto (1,089), mtbo (348 excluded), skio (15) |

The `backend/scripts/index_vikazimut.py` script parses IOF XML 3.0, filters VTT-O courses (discipline, course_type, distance > 20 km) and produces `vikazimut/index.json`.

Planned use: XGBoost training patches on French maps, real runnability heatmaps from GPX traces.

---

## References & Credits

This project draws on the following tools and standards:

- **[Streeto](https://streeto.co.uk)** — sprint course generation software for urban environments
- **[IOF XML 3.0](https://orienteering.sport/iof/it/data-standard-3-0/)** — international data exchange standard for orienteering
- **IOF/FFCO Course Setting Rules** — official course design guidelines (TD1-5, PD1-5, dog-leg control, distances, climb)
- **[ocad2geojson / ocad-tiler](https://github.com/openlayers/ocad-tiler)** — reading and rendering OCAD `.ocd` map files
- **[OpenStreetMap](https://www.openstreetmap.org) / [Overpass API](https://overpass-api.de)** — geographic terrain data (buildings, roads, obstacles)
- **[Ollama](https://ollama.ai)** — local LLM engine (optional fallback)
- **[Leaflet](https://leafletjs.com) / [react-leaflet](https://react-leaflet.js.org)** — interactive mapping

---

## License & Usage

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see [LICENSE](./LICENSE).

- **Open Source**: Free to use, modify, and distribute provided all source modifications are published, including SaaS deployments.
- **Commercial proprietary use**: Contact the author for a commercial license if you wish to embed AItraceur in a closed product without publishing modifications.

Copyright (c) 2026 Guillaume Lemiègre
