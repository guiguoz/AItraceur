# 01 — État des lieux vérifié (10 novembre 2026)

Ce document décrit ce que le code fait **réellement**, pas ce que la documentation du dépôt en dit.
Chaque constat cite un fichier et une ligne. Les numéros de ligne valent pour la branche
`origin/arena/01a100b3-aitraceur` (commit `60b624a`), c'est-à-dire `main` (`e321816`) plus les cinq
commits des étapes 14c–14d. Le backend est identique sur les deux branches ; seul le frontend diffère.

Méthode : lecture du code, `git log`, recherche plein texte dans les 22 PDF du dépôt (`docs/` et
`docs controleur/`), comparaison des tables de symboles aux jeux de symboles officiels
d'OpenOrienteering Mapper et au gabarit ISOM 2017-2 de lidar-o. Les tests n'ont pas été exécutés.

## 1. Repères

| Élément | Valeur |
|---------|--------|
| `main` | `e321816` — « diagnostic OCAD factuel + audit terrain (étapes 14a-14b) » |
| Branche non fusionnée | `origin/arena/01a100b3-aitraceur`, 5 commits d'avance (étapes 14c–14d), 8 fichiers frontend |
| Backend | `backend/src/`, 38 940 lignes Python ; `main.py` 5 203 l. ; `genetic_algo.py` 3 484 l. |
| Frontend | `frontend/src/`, 6 249 lignes ; `App.jsx` 1 947 l. |
| Tests | 198 fonctions de test backend (dont 128 sur un paquet non branché, voir C1), 47 tests frontend (vitest) |
| Depuis juillet | Aucune phase de l'ancien plan n'a été exécutée. Le travail a porté sur le diagnostic OCAD factuel (étapes 14a–14d). |

## 2. Constats

### C1 — Deux moteurs coexistent, un seul est branché

- **Moteur v1 (branché)** : `backend/src/services/generation/` — algorithme génétique sur des
  coordonnées WGS84 en degrés. C'est lui que les endpoints appellent.
- **Paquet `backend/src/aitraceur/` (non branché)** : 7 513 lignes, 7 couches (candidats, navigation,
  matrice de coûts, modèle, score, génération, calibration), ajouté en un seul commit (`93dee5c`,
  2026-03-28) et jamais modifié depuis. `main.py` ne l'importe pas ; seuls
  `backend/scripts/run_generator.py`, `backend/scripts/visualize_leg.py` et
  `backend/tests/aitraceur/` l'utilisent. Le README annonce des résultats sur « 20 candidats
  synthétiques plats ».
- Ce paquet a la bonne intention (géométrie en mètres, objet `Leg`, score explicable) mais ses
  fondations sont fausses : table de symboles inventée (`controls/symbol_map.py` : 3xx = végétation,
  4xx = eau, l'inverse de toutes les normes), niveaux britanniques (`profiles.py` l.41-48 :
  WHITE/YELLOW/ORANGE/GREEN/BLUE/RED), vitesse de base `6.0` « m/min » (`profiles.py` l.156),
  raster peint cellule par cellule en Python (`navigation/raster.py` l.198-219), « complexité du
  choix d'itinéraire » = simple ratio de détour (`model/leg.py` l.143-148).

**Conséquence** : le plan ne « branche » pas ce paquet. Il réutilise son emplacement et son intention,
et remplace ses fondations (voir `02_VISION_ARCHITECTURE.md` §5).

### C2 — La fonction de score documentée n'a jamais piloté la génération

- `genetic_algo.py` l.278 : `self.scoring_function = scoring_function or self._default_scoring`.
  Aucun appelant ne passe `scoring_function`. Cette ligne existe depuis le premier commit
  (`bca5db2`, 2026-02-26).
- `evaluate_fitness` (l.2109, les « termes A→L » de `CLAUDE.md`, du README et d'`ARCHITECTURE.md`)
  n'est appelée qu'une fois par génération, sur le meilleur circuit, à titre de télémétrie
  (l.1007-1012). Le message du commit `6bfbd95` (2026-05-25) le dit lui-même : « la telemetrie
  était dans evaluate_fitness mais GA appelait _default_scoring — jamais executé ».
- La sélection est donc faite par `_default_scoring` (l.3061-3414).

**Conséquences** : (a) la documentation décrit un moteur qui n'existe pas ; (b) les expériences de
mai (`docs/latent_manifold_findings.md`, réglages `w_dist_override` l.2636 et `w_diversity_mult`
l.2606) faisaient varier des poids situés dans la fonction inerte ; (c) leurs graines venaient de
`abs(hash((map_name, td, local_idx)))` (`backend/scripts/collect_fitness_data.py` l.194-196), or le
`hash` d'une chaîne Python change à chaque processus : ces séries ne sont pas reproductibles.
Les conclusions tirées de ces expériences sont à classer « non établies ».

### C3 — Les amas de postes (« triangulation ») sont récompensés exprès

- `_default_scoring`, l.3320-3353 : `cluster_bonus` vaut jusqu'à 100 quand le circuit contient des
  groupes de postes rapprochés, et `cluster_weight = 0.15` (l.3353, valeur écrite en dur ;
  `GAWeights.w_cluster` n'est jamais lu). En sprint, 15 % de la note récompense donc les amas.
- `placement_rules.json` (l.53-55, 76-78, 99-101) : amas de 3 ou 4 postes dans 80 m, 1 ou 2 amas
  exigés selon le niveau.
- `controleur.py` l.653-719, contrôle C16 : signale l'**absence** d'amas, au nom d'« IOF Sprint
  Course Planning Guidelines §4.5 ».
- Cette règle est introuvable dans les 22 PDF du dépôt. La seule mention d'amas de postes
  (*officials handbook*) concerne les courses au score.

**Conséquence** : la « triangulation de postes dans des secteurs très rapprochés » signalée par le
traceur n'est pas un accident de l'algorithme, c'est un objectif codé.

### C4 — Les tables de symboles sont fausses et se contredisent

Neuf endroits décrivent le sens des symboles, sans norme détectée et sans source commune :

| Fichier | Exemple de contenu | Sens réel (ISOM 2017-2 / ISSprOM 2019) |
|---------|--------------------|----------------------------------------|
| `frontend/src/App.jsx` l.224 `ATTRACTIVE_ISSOM` | 401-405 = « intersections, carrefours, coudes » | 401-404 = terrains découverts, 405 = forêt (des **surfaces**) |
| `frontend/src/App.jsx` l.311 `PATH_ISSOM` | 401-405 = chemins | idem : aucune ligne ne porte ces codes |
| `frontend/src/App.jsx` l.353 `ISOM_ATT` | 109-111 = dépression, 118 = rocher isolé, 209 = fontaine | 109 = petite butte, 111 = petite dépression, 118 n'existe pas, 209 = champ de blocs dense |
| `frontend/src/App.jsx` l.236 `OOB_ISOM` | 526 = « passage hors limites », 715 | 526 = cairn ; 715 n'existe pas |
| `backend/tile-service/server.js` l.91-101 | 406/407 = « rough open land (olive) » interdits | 406/407 = végétation, course ralentie (franchissable) |
| `backend/src/aitraceur/controls/symbol_map.py` | 301-311 = végétation, 401-413 = eau | l'inverse |
| `backend/src/services/knowledge_base/isom_semantics.json` | 516 = « unpaved_road », 201 = « open_land », 306 = « impassable_ditch » | 516 = clôture, 201 = falaise infranchissable, 306 = petit cours d'eau |
| `backend/data/isom_navigation_roles.json` | 402-403 = points d'attaque « très haute qualité », 401-403 = mains courantes « très haute qualité » | des surfaces de terrain découvert |
| `backend/src/data/ocad_semantics.json` | 201 = plan d'eau, 414 = bâtiment, 505 = hors limites | 201 = falaise, 414 = vigne, 505 = chemin |
| `backend/src/data/control_descriptions.json`, `ISOM_DESCRIPTIONS` (`ai_generator.py` l.127) | deux autres numérotations (109 = dépression, 202 = bloc, 508 = pont…) | 109 = petite butte, 202 = falaise, 508 = layon |

S'y ajoute un piège que le code ignore : **le même numéro change de sens d'une norme à l'autre**.

| Élément | ISOM 2017-2 / ISSprOM 2019 | ISOM 2000 | ISSOM 2007 |
|---------|---------------------------|-----------|------------|
| Bâtiment | 521 | 526 | 526.1 |
| Zone interdite (olive) | 520 | 527 (habitat), 528 (interdit permanent) | 528.1 |
| Zone pavée | 501 | 529 | 529.x |
| Mur infranchissable | 515 | 521 | 521.1 |
| Clôture infranchissable | 518 | 524 | 524 |
| Végétation infranchissable | 410 (ISSprOM), 411 (ISOM 2017 1re éd.) | 410 | 421 |
| Petite butte | 109 | 112 | 112 |
| Rocher | 204 | 206 | 206 |
| Cairn | 526 | 537 | 537 |

Sur une carte ISSOM 2007, le code actuel prend donc les bâtiments (526) pour des « passages hors
limites », prend les sommets des zones pavées (529) pour des coins de bâtiment (`BUILDING_ISSOM`,
`App.jsx` l.310) et ne voit pas l'olive (528.1).

### C5 — Pourquoi des postes tombent dans le vert olive

1. Le service de tuiles ne retient que des numéros exacts (`520000`, `520001`, `520002`…,
   `server.js` l.91-101) : tout sous-symbole au-delà de `.2` et toute carte à l'ancienne norme passent
   au travers.
2. `main.py` l.4088 : `oob_polygons = _ocad_fz  # remplace les zones frontend`. Les zones calculées
   par le service de tuiles **remplacent** celles du navigateur au lieu de s'y ajouter.
3. `main.py` l.4094-4115 : en sprint, des candidats OpenStreetMap sont fusionnés « toujours », sans
   être filtrés à ce stade par les zones interdites.
4. Rien ne vérifie qu'un poste est *atteignable* (voir C6).

### C6 — Pourquoi les bâtiments en propriété privée ne sont pas distingués

`extractCandidatePoints` (`App.jsx` l.378-451) prend **tous les sommets** du contour de chaque
bâtiment comme candidats. Aucune notion d'accès n'existe dans le dépôt : ni « de quel côté se tient
le coureur », ni « ce coin est-il relié au reste de la carte sans traverser d'interdit ».
Un coin de maison au fond d'un jardin privé vaut autant qu'un coin sur la rue.

### C7 — En forêt, les candidats ne sont pas des éléments de poste

Pour tout ce qui n'est ni point, ni bâtiment, ni chemin, le code prend le **centroïde** de l'objet
(`App.jsx`, branche `else` de `extractCandidatePoints`). Comme les codes 401-406 sont dans
`ATTRACTIVE_ISOM`, le centre des zones de végétation devient candidat. À l'inverse, de vrais éléments
ponctuels sont absents de la liste : 207 (groupe de rochers), 303 (trou d'eau), 311-313 (puits,
source), 418-419, 524-527 (tours, cairn, mangeoire), 530-531. Le mélange final est tiré au sort par
`Math.random()` (l.446) puis tronqué : deux essais sur la même carte n'ont pas les mêmes candidats.

### C8 — Les niveaux ne sont pas ceux de la FFCO

- Le code raisonne en « TD1 à TD5 », l'échelle **britannique**, présentée comme « IOF/FFCO ».
  La FFCO définit **six niveaux par couleur** (RTS mai 2025 §3.2.1 ; Guide des circuits de couleur
  2024 §2) : vert (très facile), bleu, jaune, orange, violet, noir (extrême).
- `backend/data/ffco_categories.json` (bloc `couleur`) et `App.jsx` l.25-30 rangent les couleurs
  dans l'ordre britannique : Jaune = TD1 (1,5–2,5 km), Orange, Vert = TD2 (3,5–5 km), Bleu, Violet,
  Noir. Un circuit « Vert » demandé pour des enfants de 10 ans sort donc à 3,5–5 km et un niveau
  au-dessus. La source déclarée du fichier (« Guide du Traceur FFCO 2023 ») n'est pas dans le dépôt.
- L'assistant enseigne la même échelle : invite système de `local_rag.py` (tableau TD1–TD5) et jeu
  de questions-réponses `Lora/mondial_tracage_QR_v4.jsonl`.

### C9 — Défauts de câblage

| Défaut | Preuve | Effet |
|--------|--------|-------|
| L'arrivée n'est jamais transmise | Le frontend n'envoie pas `end_position` ; `ai_generator.py` l.298 : `end = request.end_position or start` | Tous les circuits reviennent au départ, même si une arrivée est posée (outil « Arrivée », `App.jsx` l.502). |
| Les postes imposés sont ignorés | `required_controls` est transmis (`main.py` l.2232, 2369) mais `_generate_genetic` ne le lit pas | « Compléter le circuit » ne tient pas compte des postes existants. |
| Nombre de postes gonflé | `App.jsx` l.979 : `target_controls × 1.5` (forêt) | Jambes plus courtes que demandé. |
| Erreurs sprint perdues | `_sprint_impl` fait `return {"error": …}` (l.4330, 4357) ; `_run_sprint_task` (l.4925) ignore la valeur de retour | La tâche reste « processing » jusqu'à l'expiration côté interface. |
| Pas de contrôleur en forêt | Seul appel : `ControleurSprint(circuit_type="sprint")`, `main.py` l.4523 | Les circuits forêt ne sont jamais contrôlés. |
| Distance mini entre postes incomplète | C02 (`controleur.py` l.338-353) ne compare que les postes **consécutifs** et cite « ISSprOM 2019 §6.1 », qui est une norme de carte | Deux postes non consécutifs peuvent être collés. |

### C10 — Géométrie en degrés

- La constante `72600` (mètres par degré de longitude, vraie seulement vers 49° N) apparaît à 7
  endroits : `genetic_algo.py` l.1254, 1969, 2040, 2080 ; `main.py` l.4368, 4830 ;
  `services/analysis/gpx_parser.py` l.211.
- Mutations `_mutate_random_walk` (l.1968-1970) et `_mutate_perturbation` (l.2079-2081) : un seul
  tirage `delta_m` est appliqué à x **et** à y. Les postes ne bougent que le long de la diagonale
  sud-ouest / nord-est.

### C11 — Dépendances en ligne et payantes

| Dépendance | Où | Statut |
|------------|----|--------|
| Overpass (OpenStreetMap) | sprint, « toujours » (`main.py` l.4094 et suivantes) ; analyse d'itinéraires en forêt (`main.py` l.2343-2344) | En ligne, gratuit |
| IGN altimétrie, opentopodata, MapAnt | `services/terrain/` | En ligne, gratuit |
| API d'embeddings OpenAI | `knowledge_base/rag_builder.py` l.67-71 | **Payant** si activé |
| Entraînement du CNN | Kaggle (GPU) | En ligne |
| Livelox | `services/importers/livelox_client.py`, `livelox_importer.py`, `backend/ingest_livelox.py`, `knowledge_base/scrapers/livelox.py` | Connexion avec un compte personnel et imitation d'un navigateur pour interroger l'API sans clé : contraire aux conditions d'utilisation de Livelox (registre E34, E35 ; retrait en phase 1) |
| Sites RouteGadget de clubs, Vikazimut | `backend/scripts/scrape_rg2.py`, scripts `*vikazimut*` (jeu d'entraînement du CNN) | Conditions des sites à vérifier (V22) |
| Modèle `ffco-iof-v7` | Ollama local, accompagné d'un jeu de 54 questions-réponses (`Lora/`) | Local, mais enseigne TD1–5 |
| `sentence-transformers` (donc PyTorch) | `local_rag.py` | Local, lourd, absent de `requirements.txt` |

Le corpus de l'assistant (`backend/data/pdf_knowledge.jsonl`, 2 395 extraits) contient 141 extraits
d'un document sans rapport (`docs controleur/20241209_WL_FeuerungskontrolleurIn_Fz.pdf`, règlement
d'examen suisse des contrôleurs de combustion) et n'enregistre aucun numéro de page.

## 3. La chaîne causale

```
tables de symboles fausses, pas de norme détectée (C4)
   ├─► zones interdites incomplètes (C5) ─────────────► postes dans l'olive
   ├─► candidats = centroïdes et sommets bruts (C6, C7) ► postes sur des bâtiments enclavés,
   │                                                      postes « au milieu de rien »
   └─► lignes directrices / d'arrêt calculées sur des codes faux ► interpostes sans logique
amas récompensés (C3) ────────────────────────────────► « triangulation »
arrivée = départ, mutations diagonales (C9, C10) ─────► carte sous-exploitée, croisements
niveaux britanniques mal rangés (C8) ─────────────────► H10/H12 traités comme H21
score réel ≠ score documenté (C2) ────────────────────► réglages sans effet, mesures non fiables
```

Aucun réglage de poids ne peut corriger cela : il faut d'abord que la carte soit lue juste.

## 4. Ce qui existe et que l'on garde

| Acquis | Où | Rôle dans le plan |
|--------|----|-------------------|
| Lecture OCAD par `ocad2geojson@2.1.20` dans le navigateur | `OcadUploader.jsx` | Lecteur unique (phase 2). |
| Étapes 14a–14d : inventaire factuel des symboles, empreinte SHA-256, audit terrain | `OcadDiagPanel.jsx`, `ocadInventory.js`, `TerrainAuditPanel.jsx`, `terrainAudit.js` | Point d'ancrage du registre de symboles ; l'audit terrain devient une entrée du moteur (un élément « absent » n'est plus un site). |
| 22 documents officiels | `docs/`, `docs controleur/` | Source unique des règles (phases 4, 7, 8). |
| 338 jambes annotées à la main (« suivi », « attaque », nombre d'itinéraires) | `output/annotations_*.csv`, `output/intent_legs_*.csv` | Jeu de validation de l'analyse de jambe (phase 5). |
| Cartes d'essai déjà utilisées : airelles, bayeux, caen, cerisy, grochot, langrune, llose, montmirel, steanne | fichiers locaux du traceur | Banc d'essai (phase 0). |
| Export IOF XML 3.0, imports IOF/KML/GPX, analyse multi-GPX | `services/export/`, `services/importers/`, `services/analysis/` | Réutilisés (phases 9, 11). |
| Squelette Tauri v2 | `src-tauri/` | Empaquetage (phase 11). |
| Projet lidar-o | dépôt voisin | Gabarit ISOM 2017-2, correspondances de noms de symboles français, discipline de mesure, MNT LiDAR HD (phases 2, 10). |

## 5. Verdict sur les plans de juillet

| Élément des anciens plans | Verdict | Motif |
|---------------------------|---------|-------|
| Idée directrice « jambes d'abord » | **Gardée** | C'est le principe du traceur et celui de la FFCO. |
| Banc de mesure avant tout réglage, gel des poids | **Gardé, renforcé** | Devient indépendant du score du moteur (phase 0). |
| Atteignabilité par composantes connexes | **Gardée** | Corrige C6 (phase 3). |
| Source unique de vérité | **Gardée, mais déplacée** | La source unique n'est pas un fichier de poids : c'est le registre de symboles. |
| Cadre de niveaux TD1–TD5 présenté comme IOF/FFCO | **Faux — corrigé** | Échelle britannique ; remplacée par les six couleurs FFCO (phase 4). |
| Listes de numéros de symboles citées de mémoire (« 520, 526, 709, 714, 715 ») | **Faux — corrigé** | Recopiaient les erreurs du code ; remplacées par quatre tables de référence (annexe A1). |
| Triangulation attribuée au choix « argmax » et aux distances à vol d'oiseau | **Faux — corrigé** | La cause directe est `cluster_bonus` + C16 (C3). |
| « Récupérer » les termes d'`evaluate_fitness` | **Abandonné** | Ces termes reposent sur des codes de symboles faux (C4). |
| Audit de pondération en 16 points | **Abandonné** | Auditer des poids appliqués à des entrées fausses ne sert à rien ; le moteur v1 est gelé puis retiré. |
| Softmax à la place d'argmax, en expérience A/B réversible | **Reporté en phase 6** | Devient le tirage de diversité de l'assemblage, toujours derrière un drapeau. |
| Phases 3 « distances réseau » et 4 « jambes d'abord » | **Refondues** | Remplacées par les phases 5 et 6, fondées sur un raster de temps et non sur OpenStreetMap. |
| Plan non raccordé aux étapes 14 du traceur | **Corrigé** | La phase 2 prolonge directement l'inventaire 14a–14d. |
| Paquet `backend/src/aitraceur/` non mentionné | **Oubli — corrigé** | Voir C1 et `02_VISION_ARCHITECTURE.md` §5. |

## 6. Ce qui n'a pas été vérifié

- Les tests n'ont pas été exécutés (dépendances lourdes absentes de l'environnement d'analyse).
  La phase 0 établit la ligne de base réelle.
- Aucune carte `.ocd` réelle n'a été lue pendant cette analyse : la norme de chacune des cartes
  du traceur est inconnue. La phase 2 la mesure.
- L'utilité du CNN (`control_scorer_cnn.onnx`) n'a pas été mesurée. La phase 9 tranche.
