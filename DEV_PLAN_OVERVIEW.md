# Plan de Développement - Application CO (Forêt & Ville)

## 🎯 Vision

Application web d’aide au traçage de parcours de course d’orientation, capable de :
- Analyser et optimiser des circuits existants.
- Générer automatiquement des circuits à partir d’une carte OCAD et de contraintes.
- Exploiter LIDAR, OSM, éventuellement cadastre, et une base de connaissances IA (RAG).
- Gérer à la fois la forêt (ISOM) et la ville/sprint (ISSprOM).

Nom de travail proposé : **CourseForge** ou **SmartO**.

---

## 🧩 Modes Fonctionnels

### Mode 1 : Optimisation d’un circuit existant
- Upload d’un fichier OCAD avec circuits.
- Lecture des postes, circuits, emprise, CRS.
- Téléchargement et traitement LIDAR (forêt) et OSM (ville/parc).
- Analyse des problèmes :
  - Sentiers non cartographiés.
  - Croisements de circuits.
  - Postes trop proches ou dans des zones interdites.
  - Spoils (visibilité excessive).
  - Traversées dangereuses (routes, zones privées).
- Proposition de déplacements locaux de postes (rayon paramétrable).
- Export du circuit optimisé (IOF XML, éventuellement OCAD).

### Mode 2 : Génération d’un circuit from scratch
- Upload d’une carte OCAD (sans circuit ou avec circuit ignoré).
- Sur carte interactive, l’utilisateur définit :
  - Départ, arrivée.
  - Balises obligatoires.
  - Zones interdites (polygones).
  - Type de circuit : par couleur ou par catégorie.
  - Objectifs (longueur, D+, nb de postes, difficulté TD, temps gagnant).
- L’app :
  - Détecte l’environnement (forêt / urbain / parc / mixte).
  - Construit un graphe de navigation (positions candidates, runnability).
  - Génère plusieurs variantes de circuits (algorithme génétique + IA).
  - Score chaque variante selon :
    - Respect des contraintes.
    - Qualité des choix d’itinéraires.
    - Équilibre difficulté.
    - Sécurité.
  - Permet à l’utilisateur de choisir une variante puis d’exporter.

---

## 🌍 Environnements : Forêt vs Ville

### Environnement Forêt
- Carte : ISOM 2017.
- Données principales : LIDAR (DTM, DSM, végétation, pente).
- OSM : routes et quelques chemins.
- Runnability basée sur végétation + pente.
- Circuits LD/MD, TD2–TD5.

### Environnement Ville / Sprint
- Carte : ISSprOM 2019.
- Données principales : OSM (bâtiments, rues, mobilier urbain, barrières).
- Éventuellement cadastre (France).
- Runnability basée sur type de surface, escaliers, mobilier.
- Circuits sprint (10–15 min) et urbains.

### Détection automatique d’environnement
- Analyse symboles OCAD (forêt vs urbain).
- Densité de bâtiments OSM.
- Couverture végétation à partir du LIDAR.
- Retourne :
  - type : forest / urban / park / mixed
  - confiance
  - caractéristiques (densité bâtiments, couverture végétale, etc.)
  - configuration de traitement recommandée.

---

## 🏗️ Architecture Technique (Vue d’ensemble)

### Backend (Python / FastAPI)
- API REST + éventuellement WebSockets pour suivi de tâches longues.
- Base de données PostgreSQL + PostGIS (circuits, événements, tâches).
- Redis pour cache (données terrain, sessions IA).
- Celery pour tâches asynchrones (traitement LIDAR, génération circuits).
- Vector DB (Pinecone ou Chroma) pour la base de connaissances RAG.

### Frontend (React + TypeScript)
- Carte interactive (Mapbox GL JS).
- Éditeur de contraintes (départ/arrivée, zones interdites).
- Visualisation circuits (avant/après, variantes).
- Panneaux d’analyse (problèmes détectés, stats).
- Intégration d’un chat/assistant IA spécialisé CO.

---

## 📦 Modules Principaux Backend

- `services/ocad/` : lecture/écriture de fichiers OCAD, export IOF XML.
- `services/terrain/` :
  - LIDAR manager (tuiles IGN, PDAL, DTM/DSM/végétation/pente).
  - OSM fetcher (Overpass API).
  - Cadastre fetcher (France, optionnel).
  - Overlay OCAD + OSM + LIDAR.
- `services/environment/` :
  - Detection de type environnement (forêt/urbain/parc/mixte).
  - Configuration de traitement associée.
- `services/optimization/` :
  - Détection de problèmes (foret/urbain).
  - Calcul de routes réalistes (runnability).
  - Optimisation des positions de postes.
- `services/generation/` :
  - Construction graphe de navigation.
  - Algorithme génétique de génération.
  - Génération IA (GPT-4) de circuits et d’explications.
  - Scoring des variantes.
- `services/knowledge_base/` :
  - Scrapers Livelox, Vikazimut (routegadget éventuellement).
  - Import de documents officiels (IOF, FFCO, etc.).
  - Construction de la base RAG (Embeddings + Vector DB).
  - Assistant IA expert pour analyse de circuits.
- `services/export/` :
  - Export IOF XML 3.0.
  - Rapports PDF d’analyse.
  - GPX des circuits.

---

## 🧠 Base de Connaissances IA (RAG)

Sources :
- Documents officiels IOF, FFCO (guides traceur, règlements, standards de carte).
- Circuits réels (Livelox) : caractéristiques, résultats, traces GPS, analyses de choix d’itinéraires.
- Analyses expertes (Vikazimut, éventuellement autres blogs spécialisés).
- Retours d’expérience agrégés au fil de l’usage.

Usage :
- Aider à analyser un circuit selon les standards.
- Comparer à des circuits similaires réussis.
- Suggérer des améliorations.
- Expliquer les choix de l’algorithme aux traceurs.

---

## 🚀 Roadmap par Sprints (résumé)

1. **Sprint 0** : Setup projet, Docker, structure, CI simple.
2. **Sprint 1** : Upload + parsing OCAD, affichage circuit sur carte.
3. **Sprint 2** : Intégration LIDAR et runnability forêt.
4. **Sprint 3** : Intégration OSM + overlay OCAD/OSM.
5. **Sprint 4** : Détection de problèmes (forêt).
6. **Sprint 5** : Optimisation de positions de postes.
7. **Sprint 6** : Base RAG (scraping + documents officiels).
8. **Sprint 7** : Génération de circuits from scratch (forêt).
9. **Sprint 8** : Support ville/sprint (OSM enrichi, runnability urbaine).
10. **Sprint 9** : Parc/mixte + polish + exports.
11. **Sprint 10** : Beta fermée et lancement.

---

## 🎯 Objectif pour Claude / Cursor

Ce fichier donne :
- La vision d’ensemble.
- Les modes fonctionnels.
- L’architecture globale.
- La roadmap.

À utiliser comme contexte pour :
- Prioriser les tâches.
- Garder la cohérence.
- Justifier les choix techniques.
