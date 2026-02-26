# CONTEXT.md – Contexte métier et usage de l’app

## 1. Objectif général du projet

L’application vise à **assister les traceurs de parcours de course d’orientation** (CO), en forêt et en milieu urbain (sprint), en exploitant :

- Des cartes OCAD existantes.
- Des données terrain externes (LIDAR, OSM, éventuellement cadastre).
- Une base de connaissances IA (documents officiels, circuits réels, analyses expertes).

L’objectif n’est **pas** de remplacer le traceur, mais de :
- Détecter automatiquement des problèmes.
- Proposer des améliorations.
- Générer des idées de circuits conformes aux standards.
- Expliquer les choix de manière pédagogique.

Le traceur reste **décisionnaire final**.

---

## 2. Rappels sur la course d’orientation

### 2.1. Définition

La course d’orientation est un sport où les coureurs doivent :
- Se déplacer d’un **départ** à une **arrivée**.
- En passant par une série de **postes** (points de contrôle) dans un ordre imposé.
- En s’aidant d’une **carte spécifique** et d’une **boussole**.
- Le plus rapidement possible.

Le travail du **traceur** consiste à définir :
- Le **placement des postes**.
- L’**enchaînement des postes** (interpostes).
- La **difficulté technique**.
- La **distance** et le **dénivelé**.
- Un **équilibre global** (physique, technique, ludique, sécurité).

### 2.2. Types de courses

Quelques types courants :
- **Classic / Longue distance (LD)** : longues distances, navigation macro.
- **Moyenne distance (MD)** : orientation plus technique, nombreux changements de direction.
- **Sprint** : en ville ou parc, très rapide, décisions fréquentes.
- **Score, relais, mass-start, papillons** : variantes, à prévoir plus tard.

Dans un premier temps, le projet se concentre sur :
- Courses **individuelles** à postes ordonnés.
- En **forêt** (ISOM) et en **urbain/sprint** (ISSprOM).

---

## 3. Cartographie CO (OCAD, ISOM, ISSprOM)

### 3.1. OCAD

OCAD est un logiciel propriétaire utilisé massivement pour :
- Dessiner des cartes de course d’orientation.
- Créer des circuits (Module Course Setting).
- Exporter vers formats standards (IOF XML, PDF, etc.).

Les fichiers `.ocd` sont binaires et contiennent :
- La carte **vectorielle** (symboles, polygones, lignes, textes).
- Les **paramètres de la carte** (échelle, projection, grilles).
- Les **postes** et **circuits** (via le module course setting).

L’application devra :
- Lire ces fichiers (**lecture**).
- Extraire les informations utiles.
- Éventuellement produire des fichiers pour réimport dans OCAD (**écriture** ou export XML).

### 3.2. Standards de carte

- **ISOM 2017** : norme pour les cartes de forêt.
  - Symboles végétation (verts).
  - Courbes de niveau.
  - Rochers, falaises, marécages, etc.

- **ISSprOM 2019** : norme pour les cartes de sprint.
  - Bâtiments, murs, escaliers, zones interdites.
  - Détails urbains.

Ces normes sont importantes pour :
- Comprendre la **nature du terrain** à partir de la carte.
- Détecter si la carte est plutôt **forêt** ou **urbain**.
- Interpréter les symboles pour la **runnability** (vitesse de déplacement).

---

## 4. Données externes : LIDAR, OSM, cadastre

### 4.1. LIDAR (France : LIDAR HD IGN)

Le LIDAR fournit des données de distance laser permettant de dériver :
- **DTM** (Digital Terrain Model) – modèle du sol nu.
- **DSM** (Digital Surface Model) – sol + végétation + bâtiments.
- Hauteur de végétation (DSM – DTM).
- Pente, exposition, etc.

Utilisation pour CO :
- Analyser le **relief** avec précision.
- Estimer la **runnability** en forêt (vitesse de déplacement).
- Détecter des **sentiers** ou structures linéaires.
- Vérifier la cohérence carte / terrain.

### 4.2. OpenStreetMap (OSM)

OSM fournit :
- Routes, chemins, sentiers.
- Bâtiments (avec types, parfois hauteur).
- Zones interdites (privé, militaire).
- Mobilier urbain (bancs, poubelles, etc.).
- Landuse (forêt, parc, urbain).

Utilisation :
- En forêt : routes/chemins supérieurs, parfois sentiers.
- En ville : **référence principale** pour rues/bâtiments/mobilier.
- Pour repérer zones **non cartographiées** sur la carte.

### 4.3. Cadastre (optionnel, France)

Le cadastre (via API IGN ou autres) fournit :
- Limites de parcelles.
- Distinction public/privé (approximative selon usage).

Utilisation :
- Vérifier que les postes/circuits ne traversent pas de parcelles privées interdites.
- Améliorer la **validation sécurité** en urbain.

---

## 5. Qualité d’un circuit CO

### 5.1. Critères techniques

- **Niveau technique (TD1–TD5)** :
  - TD1 : très simple (enfants).
  - TD2 : simple.
  - TD3 : moyen.
  - TD4 : difficile.
  - TD5 : très difficile.
- **Qualité des interpostes** :
  - Choix d’itinéraires variés.
  - Éviter les lignes droites sans décision.
  - Exposer le coureur à différents types de décisions (macro/micro).
- **Équilibre** :
  - Difficulté croissante ou structure pensée.
  - Combinaison d’interpostes physiques, techniques, rapides.
- **Lisibilité de la carte** :
  - Éviter les zones surchargées ou ambiguës.
- **Proportion chemin / hors-chemin** :
  - Dépend du niveau (débutants vs experts).

### 5.2. Critères physiques

- Longueur totale.
- Dénivelé cumulé.
- Répartition du dénivelé (pas tout au début ou tout à la fin).
- Temps gagnant estimé (en fonction de la catégorie).

### 5.3. Critères de sécurité

- Éviter falaises dangereuses, barres rocheuses, zones instables.
- Sur sprint : éviter traversées de routes à fort trafic.
- Respect des zones interdites (sur carte, OSM, cadastre).
- Éviter postes trop proches de zones dangereuses.

---

## 6. Spécificités Forêt vs Ville

### 6.1. Forêt

- Terrain naturel, relief, végétation.
- Runnability dépend de la végétation et de la pente.
- Postes sur détails du terrain : dépressions, buttes, rochers, etc.
- Données clés : LIDAR + carte ISOM.

### 6.2. Ville / Sprint

- Terrain urbain, bâtiments, rues.
- Runnability dépend du type de surface (asphalte, pavés, herbe).
- Postes sur détails urbains : coins de bâtiments, mobilier urbain, escaliers.
- Sécurité très importante (routes, zones privées).
- Données clés : OSM + carte ISSprOM, éventuellement cadastre.

---

## 7. Rôle de l’IA dans le projet

### 7.1. IA « analytique »

- **Analyser des circuits existants** :
  - Détecter automatiquement des problèmes.
  - Comparer avec circuits similaires réussis.
  - Fournir un **rapport** (texte + visuels).
- S’appuyer sur une base RAG :
  - Documents IOF/FFCO.
  - Circuits et analyses de Livelox/Vikazimut.
  - Expérience accumulée.

### 7.2. IA « générative »

- **Proposer des circuits** à partir de contraintes :
  - Forêt : circuits LD/MD.
  - Ville : circuits sprint.
- Aider à **expliquer** :
  - Pourquoi tel poste est intéressant.
  - Pourquoi tel interposte est bon en termes de choix d’itinéraires.
- Toujours cadrée par des validations et filtres :
  - Règles IOF.
  - Contraintes de sécurité.
  - Contraintes utilisateur.

---

## 8. Limites et responsabilités

- L’outil :
  - Ne remplace pas le terrain ni la validation humaine.
  - Ne garantit pas l’absence de tous problèmes.
- Le traceur :
  - Doit **valider** tous les circuits proposés.
  - Doit tenir compte des contraintes locales spécifiques (autorisation, accès terrain).
- L’app doit être conçue comme un **assistant expert**, pas comme un générateur 100 % autonome.

---

## 9. Public cible

- Traceurs de clubs (amateurs, bénévoles).
- Traceurs nationaux/internationaux (experts).
- Fédérations (support à la formation et au contrôle).
- Potentiellement : cartographes (vérification cartes).

---

## 10. Cas d’usage typiques

1. **Analyse d’un circuit existant** :
   - Le traceur uploade son OCAD.
   - L’app récupère LIDAR/OSM.
   - L’app :
     - signale des problèmes potentiels,
     - propose des modifications,
     - génère un rapport.

2. **Génération d’un sprit urbain** :
   - Le traceur uploade la carte sprint.
   - Place départ, arrivée, zones interdites.
   - Demande un sprint H21E 12–15 minutes.
   - L’app propose plusieurs variantes et explique les choix.

3. **Exploration d’une nouvelle zone** :
   - Uploader une carte basique + LIDAR.
   - Demander à l’app :
     - de trouver des zones prometteuses pour des circuits,
     - de suggérer des tracés.

---
