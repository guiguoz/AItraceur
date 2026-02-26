# Plan Environnements : Forêt, Ville, Parc

## 1. Types d’Environnements

- `FOREST` : Forêt classique, cartes ISOM, données LIDAR critiques.
- `URBAN` : Ville/sprint, cartes ISSprOM, OSM critique, éventuellement cadastre.
- `PARK` : Parc urbain, mix OSM + LIDAR.
- `MIXED` : Péri-urbain, combinaison dynamique.

## 2. Détection Automatique

Sources utilisées :
- Carte OCAD :
  - Ratio symboles végétation vs bâtiments.
  - Échelle de la carte.
- OSM :
  - Densité de bâtiments.
  - Densité de routes.
- LIDAR :
  - Couverture de végétation haute.
  - Relief.

Sortie :
- `type`: FOREST / URBAN / PARK / MIXED.
- `confidence`: 0–1.
- `characteristics`: densité bâtiments, couverture végétale, etc.
- `recommended_processing`: configuration des modules.

Usage :
- Adapter les modèles de runnability.
- Choisir les sources principales (LIDAR vs OSM).
- Modifier les prompts IA.
- Activer des règles de validation spécifiques.

## 3. Traitement Forêt

- Données clés :
  - LIDAR IGN (DTM, DSM, végétation, pentes).
  - OSM (routes principales, chemins).
- Runnability :
  - Fonction de la végétation (hauteur, densité).
  - Fonction de la pente.
- Problèmes spécifiques :
  - Falaises, marécages, zones très lentes.
  - Interpostes trop physiques/monotones.
  - Risques de spoils avec relief.
- Génération :
  - Accent sur navigation macro/micro.
  - Choix d’itinéraires contournement végétation/relief.
  - Postes sur détails naturels.

## 4. Traitement Ville/Sprint

- Données clés :
  - OSM enrichi : bâtiments, rues, mobilier urbain, barrières, zones privées.
  - Cadastre (France) pour limites de parcelles (optionnel).
- Runnability :
  - Basée sur type de surface (asphalte, pavés, herbe, etc.).
  - Escaliers, dénivelé urbain.
- Problèmes spécifiques :
  - Traversées de routes dangereuses.
  - Postes en zones privées.
  - Circuits linéaires sans choix d’itinéraires.
  - Densité de décisions trop faible ou trop élevée.
- Génération :
  - Raisonnement sprint (décisions rapides, micro-choix).
  - Postes sur détails urbains précis.
  - Sécurité (zones interdites, traffic).

## 5. Traitement Parc/Mixte

- Combinaison de :
  - LIDAR (relief, végétation).
  - OSM (bâtiments, chemins, mobilier).
- Adaptation automatique du poids de chaque source.
- Détection d’aires appropriées pour différents types de postes.

## 6. Impacts sur les Modules

- `route_calculator` :
  - Version forêt vs version ville.
- `detector` :
  - Règles différentes (ex. distances entre postes en sprint).
- `ai_generator` :
  - Prompts spécifiques selon environnement.
- `scorer` :
  - KPIs adaptés (forêt : navigation & relief ; ville : décisions & sécurité).
- `MapViewer` :
  - Set de couches et style différents selon environnement.

## 7. Tests & Fixtures

- Fixtures par environnement :
  - `tests/fixtures/forest/…`
  - `tests/fixtures/urban/…`
  - `tests/fixtures/park/…`
- Tests d’intégration :
  - Vérifier la détection d’environnement.
  - Vérifier que le pipeline correct est utilisé.
  - Comparer la qualité des circuits générés par type d’environnement.
