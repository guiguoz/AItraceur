# AItraceur — Générateur IA de tracés d'orientation

> Outil web d'aide à la conception de circuits d'orientation (CO), assisté par intelligence artificielle.
> Web tool for AI-assisted orienteering course design.

---

## Fonctionnalités

- **Génération automatique** de circuits sprint (urbain) et forêt via algorithme génétique multi-objectifs
- **Contrôleur IOF/FFCO** : validation automatique des règles (dog-legs, jambes C01–C12, TD1-5/PD1-5)
- **Boucle traceur ↔ contrôleur** : dialogue IA avec corrections automatiques (jusqu'à 5 itérations)
- **Analyse de routes** : NetworkX A*, diversité des itinéraires, détection dog-legs
- **Carte OCAD** : rendu tuilé des fichiers `.ocd` (optionnel)
- **Terrain OSM** : enrichissement automatique depuis Overpass API
- **Export** : IOF XML 3.0, GPX, PDF, KML/KMZ
- **RAG local** : 22 PDF IOF/FFCO indexés, LLM local via Ollama (Llama 3)

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

### Tile Service (optionnel, pour cartes OCAD)
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

## Licence

Projet à usage éducatif et de recherche.
