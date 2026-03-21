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
