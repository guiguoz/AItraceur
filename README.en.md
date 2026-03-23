# AItraceur — AI-Assisted Orienteering Course Designer

> Web tool for AI-assisted orienteering (OL) course design.

---

## Features

- **Automatic course generation** for sprint (urban) and forest disciplines via multi-objective genetic algorithm
- **V2 multicriteria fitness** : AI Score (HeatmapCache XGBoost), distance penalty, dog-leg detection, rhythm bonus
- **HeatmapCache** : V2 score grid precomputed from MapAnt tiles (O(1) GA lookups), Smart Seeding of initial population
- **IOF/FFCO Controller** : automated rule validation (dog-legs, legs C01–C12, TD1-5/PD1-5)
- **Course setter ↔ controller loop** : AI dialogue with automatic corrections (up to 5 iterations)
- **Route analysis** : NetworkX A*, route diversity scoring, dog-leg detection
- **XGBoost V2 Scorer** : `patch_scorer_v2.pkl` (AUC=0.835) — visual quality scoring of control placements
- **OCAD map** : tile rendering of `.ocd` files (optional)
- **OSM terrain** : automatic enrichment from Overpass API
- **Export** : IOF XML 3.0, GPX, PDF, KML/KMZ
- **Local RAG** : 22 IOF/FFCO PDFs indexed, LLM chain (OpenAI → local fallback)

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

### 4. Integration: HeatmapCache

When `/generate-sprint` is called, the backend:
1. Fetches the MapAnt map image (`_fetch_mapant_bbox_image`)
2. Precomputes a V3 score grid (`scorer.build_heatmap_cache(img, bbox, mpp)`)
3. Interpolates `lng/lat` from the WGS84 `bbox` to activate the `is_urban` feature
4. Passes the `HeatmapCache` to the genetic algorithm → O(1) lookups during evolution

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

## License

Educational and research use project.
