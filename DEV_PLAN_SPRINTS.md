# Plan de Développement par Sprints

## SPRINT 0 – Setup & Structure

### Objectif
Mettre en place l’infrastructure de base (backend + frontend) et la structure du repo.

### Tâches
- Initialiser monorepo (backend `src/`, frontend `frontend/`).
- Mettre en place Docker Compose avec :
  - Backend FastAPI.
  - PostgreSQL + PostGIS.
  - Redis.
  - Frontend React.
- Configurer :
  - Formatage : Black, isort, Ruff côté Python ; Prettier + ESLint côté TS.
  - Tests de base : pytest, vitest/jest.
- Créer :
  - `CONTEXT.md` (contexte métier CO).
  - `ARCHITECTURE.md` (architecture technique).
  - `README.md` (installation & lancement).

### Directive pour Claude
> Crée la structure complète du projet (backend FastAPI + frontend React TS) avec Docker Compose, Postgres+PostGIS et Redis. Ajoute la config de base (formatters, linters, tests) conforme au style défini dans `.clinerules`.

---

## SPRINT 1 – Upload OCAD & Affichage Carte

### Objectif
Pouvoir déposer un fichier OCAD, l’analyser minimalement et afficher les circuits sur une carte web.

### Tâches Backend
- Créer `services/ocad/parser.py` :
  - Lire des fichiers OCAD (au moins une version supportée).
  - Extraire : emprise, CRS, postes, circuits.
- Créer endpoint `POST /api/v1/circuits/upload` :
  - Acceptation de fichiers `.ocd`.
  - Stockage (disque ou S3).
  - Parsing et retour JSON structuré.
- Créer modèle Pydantic `Circuit` dans `schemas/circuit.py`.

### Tâches Frontend
- Composant `FileUploader` :
  - Drag & drop de fichier OCAD.
  - Affichage état (envoi, succès, erreur).
- Composant `MapViewer` (Mapbox) :
  - Afficher la carte de fond.
  - Placer les postes et les relier (par circuit).
  - Cliquer pour voir détails d’un poste.

### Directive Claude
> Implémente un parser OCAD minimal (version X) permettant d’extraire les postes et les circuits, plus un endpoint FastAPI pour l’upload, et un composant React MapViewer pour les afficher.

---

## SPRINT 2 – LIDAR & Terrain Forêt

### Objectif
Intégrer les données LIDAR IGN pour la forêt et préparer une carte de runnability.

### Tâches Backend
- `services/terrain/lidar_manager.py` :
  - Rechercher les tuiles LIDAR IGN couvrant une emprise (API ou index local).
  - Télécharger et mettre en cache les fichiers LAZ.
  - Pipeline PDAL : calcul DTM, DSM, hauteur de végétation, pente.
- `services/terrain/terrain_analyzer.py` :
  - Calculer runnability en forêt en fonction de végétation et pente.
- Task Celery `tasks/lidar_processing.py` :
  - Traitement asynchrone, progressif.

### Tâches Frontend
- Indicateur de progression (traitement LIDAR).
- Overlay runnability (heatmap) sur la carte.

### Directive Claude
> Développe un gestionnaire LIDAR complet utilisant PDAL pour produire DTM/DSM, hauteur de végétation et pentes, puis un modèle de runnability forêt. Expose-les via API et affiche un overlay sur Mapbox.

---

## SPRINT 3 – OSM & Overlay Forêt/Ville

### Objectif
Intégrer les données OSM et superposer OCAD + OSM + terrain.

### Tâches Backend
- `services/terrain/osm_fetcher.py` :
  - Requêtes Overpass pour : routes, chemins, bâtiments, landuse.
- `services/terrain/overlay_builder.py` :
  - Rasteriser la carte OCAD.
  - Superposer OCAD, OSM, et éventuellement runnability.
  - (Optionnel) Export GeoTIFF ou tiles.

### Tâches Frontend
- Boutons pour activer/désactiver couches :
  - Carte OCAD.
  - Routes/bâtiments OSM.
  - Runnability.
- Légende simple.

### Directive Claude
> Crée un fetcher OSM pour routes, bâtiments et landuse via Overpass, et un overlay OCAD+OSM avec rasterisation OCAD. Intègre ça dans une carte Mapbox côté frontend.

---

## SPRINT 4 – Détection de Problèmes (Forêt d’abord)

### Objectif
Détecter automatiquement les problèmes principaux sur un circuit forêt.

### Problèmes ciblés
- Sentiers non cartographiés (LIDAR vs OCAD).
- Croisements de circuits.
- Postes trop proches.
- Traversées de routes.
- Interpostes trop linéaires.
- Zones interdites (si définies).

### Tâches Backend
- `services/optimization/detector.py` :
  - Fonctions de détection pour chaque type de problème.
- `services/optimization/visibility_analyzer.py` (si temps) :
  - Analyse basique de visibilité (spoils) à partir du DSM.
- Endpoint `GET /api/v1/circuits/{id}/analysis`.

### Tâches Frontend
- Panneau « Problèmes détectés » :
  - Liste des problèmes.
  - Sélection d’un problème → zoom sur la carte.

### Directive Claude
> Implémente un module de détection de problèmes pour circuits en forêt, qui analyse LIDAR+OSM+OCAD et renvoie une liste de problèmes typés avec gravité et géométrie. Crée l’endpoint d’analyse et l’UI correspondante.

---

## SPRINT 5 – Optimisation Positions de Postes

### Objectif
Proposer des déplacements locaux de postes pour améliorer le circuit.

### Tâches Backend
- `services/optimization/route_calculator.py` :
  - Calculer une route réaliste entre deux postes en utilisant la runnability.
- `services/optimization/optimizer.py` :
  - Définir une fonction de scoring qualité interposte.
  - Chercher des positions optimales dans un rayon donné (par ex. 50 m).
- Appliquer les optimisations au circuit et produire une version modifiée.

### Tâches Frontend
- Comparaison avant/après :
  - Carte avec positions originales vs optimisées.
  - Détails par interposte (distance, D+, qualité).

### Directive Claude
> Développe un module d’optimisation de postes : pour chaque interposte, calcule une nouvelle position de poste dans un rayon donné afin d’améliorer un score de qualité. Fournis aussi la comparaison avant/après.

---

## SPRINT 6 – Base RAG (Livelox, Vikazimut, Docs Officiels)

### Objectif
Construire une base de connaissances IA pour analyses avancées.

### Tâches Backend
- `services/knowledge_base/scrapers/livelox.py` :
  - Récupérer événements, circuits, résultats, traces GPS.
- `services/knowledge_base/scrapers/vikazimut.py` :
  - Récupérer analyses textuelles de circuits.
- `services/knowledge_base/document_loader.py` :
  - Importer PDF/Doc IOF & FFCO.
- `services/knowledge_base/rag_builder.py` :
  - Chunking des textes.
  - Embeddings (OpenAI).
  - Indexation Vector DB (Pinecone ou Chroma).
- `services/knowledge_base/ai_assistant.py` :
  - Assistant IA spécialisé traçage, avec retrieval.

### Tâches Frontend
- Panneau chat IA « Assistant traceur » :
  - Poser des questions sur un circuit ou sur des bonnes pratiques.
  - Afficher réponse + sources.

### Directive Claude
> Crée un pipeline RAG complet : scrapers Livelox/Vikazimut, import docs officiels, embeddings, indexation, puis une API d’assistant IA capable de répondre à des questions de traceur avec références.

---

## SPRINT 7 – Génération de Circuits From Scratch (Forêt)

### Objectif
Générer automatiquement des circuits forêt à partir de contraintes.

### Tâches Backend
- `services/environment/detector.py` :
  - Détection d’environnement (déjà utile pour la suite).
- `services/generation/graph_builder.py` :
  - Construire un graphe de navigation (positions candidates, edges, coûts).
- `services/generation/genetic_algo.py` :
  - Algorithme génétique pour circuits.
- `services/generation/ai_generator.py` :
  - Utiliser GPT-4 pour proposer une population initiale de circuits.
- `services/generation/scorer.py` :
  - Scorer des variantes selon :
    - Respect des contraintes.
    - Qualité des choix d’itinéraires.
    - Équilibre difficulté.
    - Sécurité.

### Tâches Frontend
- Éditeur de contraintes :
  - Départ, arrivée, balises obligatoires, zones interdites.
  - Paramètres (longueur, D+, nb postes, TD, temps gagnant).
- Écran de sélection de variantes :
  - Affichage 2–3 variantes sur carte.
  - Stats comparatives.
  - Choix d’une variante pour export.

### Directive Claude
> Mets en place un pipeline de génération de circuits forêt : graph builder, algorithme génétique, intégration GPT-4 pour proposer des circuits intelligents, scoring multi-critères, et API pour générer plusieurs variantes.

---

## SPRINT 8 – Support Ville/Sprint

### Objectif
Adapter tout le pipeline à l’environnement urbain (sprint).

### Tâches Backend
- Enrichir `osm_fetcher.py` pour récupérer :
  - Bâtiments (hauteur, type).
  - Mobilier urbain, clôtures/murs, escaliers, zones privées.
- `services/terrain/urban_osm_processor.py` :
  - Construire runnability urbaine (surface, escaliers, obstacles).
- `services/generation/urban_control_detector.py` :
  - Positions valides de postes en ville.
- Adapter :
  - route_calculator (runnability urbaine).
  - detector (règles sprint IOF).
  - ai_generator (prompts spécifiques sprint).

### Tâches Frontend
- UI adaptée sprint :
  - Zoom plus fort.
  - Couches urbaines (bâtiments, rues).
  - Mise en avant des décisions rapides.

### Directive Claude
> Étends tous les modules (terrain, optimisation, génération, IA) pour gérer un environnement urbain sprint (ISSprOM), en adaptant runnability, validation, et prompts IA.

---

## SPRINT 9 – Parc/Mixte, Exports & Polish

### Objectif
Support mixte, exports riches, finitions.

### Tâches Backend
- Environnement parc/mixte (combinaison forêt/ville).
- Export IOF XML, PDF, GPX propres.
- Améliorations performance (caching, parallélisme).

### Tâches Frontend
- Comparaison de circuits similaires (via RAG).
- Interface plus soignée (thème, dark mode).
- Onboarding/tutoriel.

### Directive Claude
> Finalise les fonctionnalités multi-environnements, ajoute les exports et améliore l’UX pour une release beta utilisable par de vrais traceurs.

