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

---

## ÉTAPE 10a – Bypass OCAD : OSM comme support de travail ✅ 2026-03-04

### Objectif
Supprimer la dépendance dure à un fichier `.ocd`. L’app fonctionne sur fond OSM dès l’ouverture. OCAD devient un enrichissement optionnel.

### Tâches Frontend
- `frontend/src/components/MapViewer.jsx` — Supprimer early-return `!ocadData`, ajouter `MapRefCapture` + prop `onMapReady`
- `frontend/src/App.jsx` — Retirer 6 gates OCAD, bbox fallback depuis viewport Leaflet (`mapRef`), OcadUploader → widget optionnel

### Directive Claude
> Retire les 6 gates OCAD dans App.jsx et MapViewer.jsx, ajoute un `mapRef` pour exposer les bounds Leaflet, et replace le bloc `OcadUploader` plein écran par un widget optionnel dans la sidebar.

---

## ÉTAPE 10b – Module Contrôleur : règles structurées + checks C01–C12 ✅ 2026-03-04

### Objectif
Créer le module `ControleurSprint` qui valide un circuit sprint poste par poste selon les normes IOF/FFCO, avec issues structurées (code, sévérité, control_index, suggestion, référence règle).

### Tâches Backend
- `backend/src/services/controleur/controleur_rules.json` — Nouveau : règles IOF/FFCO structurées
- `backend/src/services/controleur/controleur.py` — Nouveau : classe `ControleurSprint`, 12 checks C01–C12
- `backend/src/services/generation/scorer.py` — Alimenter `issues` depuis `ControleurSprint.validate()`, corriger bearing dog-leg (haversine)

### Directive Claude
> Crée `controleur_rules.json` avec les seuils IOF/FFCO sprint et `controleur.py` avec `ControleurSprint.validate()` retournant une liste d’issues structurées (C01–C12) avec indices de postes et suggestions, puis connecte-le au scorer.py.

---

## ÉTAPE 10c – Corrections automatiques du traceur + endpoint generate-sprint ✅ 2026-03-04

### Objectif
Pour chaque issue ERROR/WARNING, le traceur applique une mutation ciblée et soumet à nouveau au contrôleur. Boucle max 5 itérations avec log du dialogue.

### Tâches Backend
- `backend/src/services/controleur/traceur_corrections.py` — Nouveau : mutations ciblées par type d’issue (C01/C02/C08/C10)
- `backend/src/main.py` — Nouveau endpoint `POST /api/v1/generation/generate-sprint` avec boucle traceur↔contrôleur

### Directive Claude
> Crée `traceur_corrections.py` avec une fonction `apply_corrections(controls, issues, candidates)` puis crée l’endpoint `/generate-sprint` qui orchestre la boucle traceur↔contrôleur (max 5 itérations) et retourne le log du dialogue.

---

## ÉTAPE 10d – Frontend : barre de progression + DialogueLog ✅ 2026-03-04

### Objectif
Afficher le dialogue traceur↔contrôleur avec barre de progression animée pendant la génération.

### Tâches Frontend
- `frontend/src/services/api.js` — Ajouter `generateSprint(bbox, circuitConfig)`
- `frontend/src/components/DialogueLog.jsx` — Nouveau : log avec icônes 🗺/⚖️ et statuts
- `frontend/src/App.jsx` — `handleAiGenerate` appelle `/generate-sprint`, barre de progression par étape

### Directive Claude
> Crée `DialogueLog.jsx` affichant les échanges traceur↔contrôleur, modifie `handleAiGenerate` pour appeler `generateSprint()` et afficher une barre de progression étape par étape pendant la génération.

---

## ÉTAPE 10e – Route Analyzer : A* graphe OSM pour dog-leg réel ✅ 2026-03-04

### Objectif
Implémenter l’équivalent du Route Analyzer OCAD avec graphe OSM + A* pour détecter les dog-legs réels et valider le choix d’itinéraire.

### Tâches Backend
- `backend/src/services/optimization/route_analyzer.py` — Nouveau : `RouteAnalyzer` (NetworkX + A* + Yen’s k-shortest)
- `backend/src/services/controleur/controleur.py` — Connecter C01 et C11 à `RouteAnalyzer`

### Directive Claude
> Crée `route_analyzer.py` avec un graphe NetworkX construit depuis les ways OSM et A* pour trouver la route optimale entre deux postes WGS84, puis utilise `detect_dogleg()` dans le check C01 et `route_diversity_score()` dans le check C11 du contrôleur.

---

## ÉTAPE 10f – Route Analyzer visuel : k meilleurs itinéraires entre deux postes ✅ 2026-03-04

### Objectif
Afficher les k meilleures routes OSM entre deux postes cliqués dans la sidebar, comme l'outil Route Analyzer d'OCAD. Bouton 🔍 par jambe dans ControlsList, polylines colorées sur la carte.

### Tâches
- `backend/src/services/optimization/route_analyzer.py` — Ajout `get_k_routes()` (Yen's k-shortest via `nx.shortest_simple_paths`) + `route_length_m()`
- `backend/src/main.py` — Endpoint `POST /api/v1/terrain/routes-between` : fetch OSM, construit RouteAnalyzer, retourne k routes + diversité
- `frontend/src/services/api.js` — `getRoutesBetweenControls(params)` (timeout 60s)
- `frontend/src/App.jsx` — State `routeDisplay`, handler `handleShowRoutes()`, prop `routeDisplay` → MapViewer, props `onShowRoutes`/`activeRouteLegIdx` → ControlsList
- `frontend/src/components/MapViewer.jsx` — Rendu de k Polylines colorées (bleu/orange/rouge) avec Popup distance, prop `routeDisplay`
- `frontend/src/components/ControlsList.jsx` — Séparateur de jambe avec bouton 🔍 toggle ; actif = fond bleu

### UX
- Clic 🔍 → requête backend → 3 polylines colorées (rang 1 bleu, 2 orange, 3 rouge) sur la carte
- Re-clic → toggle off
- Score de diversité Jaccard retourné (utilisé en interne par C11)

---

## ÉTAPES 11a+11b – PDFs IOF/FFCO → cerveau de génération ✅ 2026-03-04

### Objectif
Les 22 PDF (IOF/FFCO guidelines) alimentent directement le pipeline de génération de postes :
- Prompt LLM enrichi des règles pertinentes (circuit_type + TD) issues des PDF
- Algorithme génétique avec seuils calibrés par niveau (dog-leg, distance min/max) depuis `placement_rules.json`

### Tâches Backend
- `backend/requirements.txt` — Ajout `pymupdf`
- `backend/src/services/knowledge_base/ingest_docs.py` — Extraction fitz + chunking 800/200 → `data/pdf_knowledge.jsonl`
- `backend/src/services/knowledge_base/local_rag.py` — `charger_dataset()` charge aussi `pdf_knowledge.jsonl` ; `search_chunks()` pour retrieval direct ; `reload()` post-ingestion
- `backend/src/services/knowledge_base/placement_rules.json` — Seuils IOF/FFCO par circuit_type + TD (min/max jambe, dog-leg angle, climb ratio)
- `backend/src/services/knowledge_base/course_rules_retriever.py` — `get_course_rules(circuit_type, td_level)` + `get_placement_rules()`
- `backend/src/services/generation/ai_generator.py` — `{rules_context}` injecté dans `CIRCUIT_GENERATION_PROMPT` + `circuit_type`/`technical_level` passés à `GenerationConfig`
- `backend/src/services/generation/genetic_algo.py` — `GenerationConfig` inclut `circuit_type`/`technical_level` ; `_load_placement_rules()` au init ; seuils dog-leg/distance dynamiques dans `_default_scoring()`
- `backend/src/main.py` — Endpoint `POST /api/v1/knowledge/ingest-docs` (déclenche ingestion + reload LocalRAG)

### Usage
1. Lancer une fois : `POST /api/v1/knowledge/ingest-docs` → indexe les 22 PDF
2. Redémarrer le backend → LocalRAG charge `pdf_knowledge.jsonl` automatiquement
3. Générer un circuit → prompt LLM + seuils GA incluent les règles IOF/FFCO du bon niveau


---

## ÉTAPE 13 – OCAD-first workflow : carte OCAD comme fond, postes sur éléments ✅ 2026-03-04

### Objectif
Quand un .ocd est chargé, l'app bascule en mode "OCAD-first" :
- Fond de carte = PNG OCAD géoréférencé seul (OSM masqué à l'affichage)
- OSM reste utilisé en coulisses pour enrichir les candidats (intersections piétonnes)
- Candidats postes = coins/virages OCAD + intersections OSM (fusionnés, dédupliqués)
- Rapport des éléments OCAD détectés visible dans la sidebar

### Tâches — 13a : MapViewer OCAD-first
- `frontend/src/components/MapViewer.jsx` — Prop `ocadMode` : masque `<TileLayer>` OSM si true
- `frontend/src/App.jsx` — State `mapMode: 'osm' | 'ocad'`, auto-switch à 'ocad' quand tile service répond, toggle sidebar OCAD/OSM

### Tâches — 13b : extractCandidatePoints() exhaustif
- `frontend/src/App.jsx` — Refonte de `extractCandidatePoints()` :
  - Coins de polygones bâtiments (isom 521/522/527/528) au lieu du centroïde
  - Vertices de changement de direction sur lignes chemins (angle < 150° = virage net)
  - Endpoints des LineStrings (carrefours, impasses)
  - Tous les Points avec code ISOM attractif
  - Déduplication ~15m (`deduplicatePoints()`)
  - Max porté à 600

### Tâches — 13c : Endpoint analyse OCAD + panel sidebar
- `backend/src/main.py` — `POST /api/v1/ocad/analyze` : reçoit GeoJSON WGS84, retourne rapport structuré (total features, by_category, candidate_points_extracted, top_candidates, terrain_summary, recommendations)
- `frontend/src/components/OcadAnalysisPanel.jsx` — Panel sidebar affiché post-chargement OCAD (catégories ISOM, nb candidats extraits, résumé terrain)
- `frontend/src/services/api.js` — `analyzeOcadGeojson(geojson)`

### Tâches — 13d : Fusion OCAD+OSM dans generate-sprint
- `backend/src/main.py` — `generate_sprint_with_validation()` : toujours fusionner OCAD + OSM (même si OCAD fournit 50+ candidats), déduplication 10m, limite 800 pts
- RouteAnalyzer toujours construit depuis OSM highway_ways (même si carte OCAD affichée)

### Architecture
- OCAD → GeoJSON (client ocad2geojson) → extractCandidatePoints() → coins/virages/points → backend
- OSM → Overpass (backend) → intersections piétonnes → fusion avec OCAD
- Résultat : GA places controls sur éléments concrets (carrefours, coins bâtiments, buttes, dépressions)
