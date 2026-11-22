# Registre — établi, réfuté, à vérifier

> Anciennement `docs/plan/A3_registre_etabli_refute.md`. Ce fichier est tenu à jour à chaque
> phase (règles de travail §6). Une entrée n'est jamais effacée : une croyance réfutée reste
> inscrite, avec ce qui l'a réfutée.

Identifiants : **E** = établi, **X** = réfuté, **V** = à vérifier. (Les identifiants **R01–R19**
sont réservés aux règles du contrôleur, phase 7 ; **K1–K9** aux indicateurs.)

Les numéros de ligne valent pour le commit `60b624a` de la branche `origin/arena/01a100b3-aitraceur`
(backend identique à `main`, `e321816`). Les preuves `mesures_2026-11/…` sont les scripts joints à
ce plan.

## Établi

| Id | Énoncé | Preuve | Date |
|----|--------|--------|------|
| E01 | Deux moteurs coexistent : le moteur v1 (`services/generation/`) est le seul branché ; le paquet `backend/src/aitraceur/` (7 513 lignes, un seul commit `93dee5c`) n'est importé par aucun endpoint. | `grep -n "aitraceur" backend/src/main.py` (vide) ; `git log -- backend/src/aitraceur` | 2026-11-10 |
| E02 | La sélection du moteur v1 est faite par `_default_scoring` ; `evaluate_fitness` (« termes A→L ») n'est qu'une télémétrie appelée une fois par génération, sur le meilleur circuit. | `genetic_algo.py` l.278 et l.1007-1012 ; aucun appelant ne passe `scoring_function` ; message du commit `6bfbd95` | 2026-11-10 |
| E03 | Les amas de postes sont récompensés : `cluster_bonus` pèse 15 % de la note sprint (`cluster_weight = 0.15` écrit en dur l.3353) ; `placement_rules.json` exige des amas ; le contrôle C16 signale leur absence. | `genetic_algo.py` l.3320-3353 ; `placement_rules.json` l.53-55, 76-78, 99-101 ; `controleur.py` l.653-719 | 2026-11-10 |
| E04 | Neuf endroits du dépôt décrivent le sens des symboles ; aucun ne correspond à une norme ; le même numéro change de sens d'une norme à l'autre et rien ne détecte la norme. | `01_ETAT_DES_LIEUX.md` C4 ; comparaison aux jeux de symboles d'OpenOrienteering Mapper (`mesures_2026-11/symboles/symtables.json`) | 2026-11-10 |
| E05 | Causes des postes dans l'olive : liste exacte de sous-numéros dans le service de tuiles ; zones du navigateur **remplacées** par celles du service ; candidats OpenStreetMap non filtrés ; aucune notion d'atteignabilité. | `server.js` l.91-101 ; `main.py` l.4088, l.4094-4115 | 2026-11-10 |
| E06 | Tous les sommets de chaque bâtiment sont candidats, sans notion d'accès. | `App.jsx` l.378-451 | 2026-11-10 |
| E07 | En forêt, les candidats sont des centroïdes d'objets, mélangés par `Math.random()` puis tronqués : non reproductible. | `App.jsx`, `extractCandidatePoints`, l.446 | 2026-11-10 |
| E08 | Le code raisonne en TD1–TD5 (échelle britannique) et range les couleurs dans l'ordre britannique (Jaune = TD1, Vert = TD2). | `ffco_categories.json` (bloc `couleur`) ; `App.jsx` l.25-30 ; `local_rag.py` l.73-77 ; 20 lignes de `Lora/mondial_tracage_QR_v4.jsonl` contiennent « TD1 » à « TD5 » | 2026-11-10 |
| E09 | Six défauts de câblage : arrivée jamais transmise, postes imposés ignorés, nombre de postes × 1,5, erreurs sprint perdues, aucun contrôleur en forêt, distance minimale vérifiée sur postes consécutifs seulement. | `01_ETAT_DES_LIEUX.md` C9 (fichiers et lignes) | 2026-11-10 |
| E10 | Géométrie en degrés : constante `72600` à 7 endroits ; mutations « diagonales » (un seul tirage appliqué à x et y). | `grep -rn 72600 backend/src` ; `genetic_algo.py` l.1968-1970, l.2079-2081 | 2026-11-10 |
| E11 | Dépendances en ligne (Overpass, IGN, opentopodata, MapAnt, Kaggle) et payante (embeddings OpenAI) ; le corpus de l'assistant (2 395 extraits, sans numéro de page) contient 141 extraits d'un règlement suisse sur les contrôleurs de combustion. | `01_ETAT_DES_LIEUX.md` C11 ; décompte par `source` dans `pdf_knowledge.jsonl` | 2026-11-10 |
| E12 | Un trait infranchissable rastérisé est étanche (8-connexité) si l'on marque toute cellule dont le centre est à moins de 0,75 × la résolution : 0 fuite sur 400 dès 0,71 × ; 399 fuites sur 400 à 0,5 ×. | `mesures_2026-11/rasterisation/leak.py` | 2026-11-10 |
| E13 | Deux surfaces infranchissables qui se touchent par un coin fuient en rastérisation « au centre » : 224 fois sur 300 à 0,5 m ; un rebouchage des diagonales laisse 107 fuites sur 300. | `mesures_2026-11/rasterisation/seal.py` | 2026-11-12 |
| E14 | La rastérisation prudente (cellule libre si son centre est dans l'espace libre érodé de 0,7072 × la résolution) ne fuit jamais (0 sur 200 à 0,25, 0,5 et 1 m) et garde ouvert tout passage d'au moins 3,2 cellules (à 0,5 m : 1,6 m ouvert 200 fois sur 200 ; 1,2 m, 36 fois sur 200). | `mesures_2026-11/rasterisation/eroded.py` | 2026-11-12 |
| E15 | À 2 m de résolution, une ruelle de 1,6 m est fermée deux fois sur trois, même au centre : la grille de 2 m du prototype ne convient pas à la ville. En rastérisation au centre, un passage d'une cellule reste ouvert en 8-connexité, pas en 4-connexité. | `mesures_2026-11/rasterisation/alley.py` | 2026-11-10 |
| E16 | Durées (un cœur) : composantes connexes 3000 × 3000 en 0,05 s ; champ de temps `MCP_Geometric` 0,16 s (ville ±300 m à 0,5 m), 0,53 s (±500 m), 1,08 s (3 km à 2 m) ; tracé 5 ms. `max_cumulative_cost` est déprécié en scikit-image 0.26 : on borne par fenêtre. | `mesures_2026-11/rasterisation/bench_mcp.py`, `bench2.py` | 2026-11-10 |
| E17 | La FFCO définit six niveaux techniques par couleur (vert, bleu, jaune, orange, violet, noir), avec un niveau maximal et un temps maximal préconisé par âge. | RTS mai 2025 §3.2.1, p. 7/12 ; Guide des circuits de couleur 2024, p. 2 | 2026-11-12 |
| E18 | Correspondance couleur ↔ règles de la Méthode fédérale : vert T1–T3 (p. 4), bleu T4–T7 (p. 5), jaune T8–T9 (p. 6), orange T10–T12 (p. 7), violet T13–T14 (p. 8), noir T15–T17 (p. 9) ; sprint : bleu p. 10, jaune p. 12, orange p. 13. Portée par la couleur des bandeaux, vérifiée sur le rendu des pages. | rendu des pages 4 à 13 de `Méthode Fédérale - Edition 2016.pdf` ; TAP §2 p. 7-12 | 2026-11-12 |
| E19 | Le sprint n'a que trois niveaux de couleur : bleu, jaune, orange. | Guide des circuits de couleur 2024, p. 5 | 2026-11-12 |
| E20 | Distances minimales entre postes : 30 m à vol d'oiseau, 60 m sur éléments de même nature (1:7 500 à 1:15 000) ; 15 m à vol d'oiseau et 25 m en distance de course (1:4 000, 1:3 000). | RTS p. 8/12 ; TP §3.5.6, p. 10 | 2026-11-12 |
| E21 | Dénivelé : au plus 4 % de la longueur par l'itinéraire le plus logique — « ne doit pas excéder » (TP) ; « il est recommandé » (RTS). | TP §3.11.6, p. 17 ; RTS p. 7/12 | 2026-11-12 |
| E22 | ISOM 2017-2 : passage minimal entre deux bâtiments, ou entre un bâtiment et un autre infranchissable, 0,4 mm sur la carte. | `ISOM2017_2_FR_EN  (mars2022).pdf`, p. 70 (symbole 521) et p. 21 | 2026-11-12 |
| E23 | ISOM 2017-2 : référence de vitesse = forêt ouverte et plate courue à 4 min/km ; cinq catégories de vitesse (> 100 %, 80–100 %, 60–80 %, 20–60 %, < 20 %). | ISOM 2017-2 §2.3, p. 9-10 | 2026-11-10 |
| E24 | Les citations de l'annexe A2 et des phases 1 à 7 ont été contrôlées mot à mot contre le texte des PDF ; les écarts relevés ont été corrigés (fautes du PDF reproduites, crochets pour les corrections). | `mesures_2026-11/citations/check_quotes.py` | 2026-11-12 |
| E25 | Les tables de sémantique de l'annexe A1 couvrent tous les couples (numéro principal, type) des jeux de référence : 121 pour ISOM 2017-2, 104 pour ISSprOM 2019 ; aucun manquant, aucun en trop. | `mesures_2026-11/symboles/gen_a1.py` | 2026-11-10 |
| E26 | Les tables ISOM 2000 et ISSOM 2007 se génèrent par les correspondances d'OpenOrienteering, sauf 8 couples sur 109 (ISOM 2000) et 5 sur 99 (ISSOM 2007), réglés à la main dans A1 §4 ; piège : 410 ISSOM 2007 (franchissable) correspond à 410 ISSprOM 2019 (infranchissable). | `mesures_2026-11/symboles/gen_old.py` | 2026-11-10 |
| E27 | Le dépôt contient 338 jambes étiquetées par le traceur : forêt `suivi` 127, `attaque` 61, `uncertain` 104 ; sprint 46 (nombre d'itinéraires × impact). Ce sont des jambes produites par le moteur v1. | `output/annotations_*.csv`, `output/intent_legs_*.csv`, `backend/scripts/annotate_legs.html` l.186-212 | 2026-11-12 |
| E28 | Le LiDAR ne discrimine pas la végétation cartographiée (AUC ≈ 0,49 une fois le relief retiré) : la carte fait foi pour la végétation, le LiDAR ne sert qu'au relief. | lidar-o, `docs/bilan_v0.md` §4 | 2026-11-10 |
| E29 | Les tableaux de la Méthode fédérale sont sur deux colonnes : une extraction de texte naïve entrelace « compétences » et « règles de traçage ». | `pdftotext` par zone (`-x 436 -W 410`) contre extraction pleine page | 2026-11-12 |
| E30 | `services/map-importer/` (Express, port 8788) n'est appelé par aucun fichier depuis le premier commit. | `grep -rn "8788\|map-importer"` hors du dossier lui-même ; `git log -- services/map-importer` | 2026-11-14 |
| E31 | `ocad2geojson@2.1.20` est sous licence AGPL-3.0-or-later, compatible avec AItraceur ; il expose `ocadToGeoJson`, `ocadToSvg`, `ocadToMapboxGlStyle` et `getCrs()`. | `package.json` et sources du paquet npm | 2026-11-10 |
| E32 | Hypothèses : H1 corrigée — PC Windows avec carte graphique NVIDIA GeForce RTX 3060 (mémoire vidéo exacte à relever) ; H2, H3, H4 confirmées. | Réponse du traceur | 2026-11-14 |
| E33 | Le traceur déclare détenir le droit de diffuser les PDF du dossier `docs/`. | Déclaration du traceur | 2026-11-14 |
| E34 | Livelox : ses conditions d'utilisation (version du 7 août 2026) interdisent « to systematically extract data from the services except through authenticated and authorized API access » et réservent aux organisateurs « all rights to maps and courses » ; son `robots.txt` interdit `/Viewer/` à tous les robots ; son API est accordée au cas par cas, pour des applications publiques et non un usage personnel, et ne fournit ni cartes ni traces. | `https://www.livelox.com/UserAgreement`, `https://www.livelox.com/robots.txt`, `https://www.livelox.com/Documentation/Api` | 2026-11-14 |
| E35 | Le client Livelox du dépôt se connecte avec un compte personnel et imite un navigateur (en-têtes `User-Agent`, `Origin`, `Referer`) pour interroger `api.livelox.com` sans clé ; il sert à des collectes par lots. | `livelox_client.py` l.40-124 ; `backend/ingest_livelox.py` | 2026-11-14 |
| E44 | Le service de tuiles ne peut pas rendre les cartes d'emprise comprise entre ~2,7 et 4,5 km² : la résolution adaptative (`server.js` l.44-49) raffinait à 0,1 m/px quand RAW < 0,3, produisant 431 Mpx pour une carte de 4,3 km² (La Forêt de Caen 2022, 2107 × 2045 m), au-delà de la limite dure de Sharp (268 Mpx). Correctif : la résolution est `Math.max(0.1, RAW)` (plancher 0,1 m/px) plus une garantie dure à 200 Mpx. Les cartes déjà rendues (Bayeux, Dôme, Porten-Bessin) ne changent pas de résolution. | Banc P0 / carte « La Forêt de Caen 2022 » ; `resolution.js` `chooseResolution()` | 2026-11-22 |

## Réfuté

| Id | Croyance | Ce qui la réfute | Date |
|----|----------|------------------|------|
| X01 | « La fonction de score à termes A→L (`CLAUDE.md`, README, `ARCHITECTURE.md`) pilote la génération. » | E02 | 2026-11-10 |
| X02 | « Il existe un réglage optimal de `W_DIST` et de `W_DIVERSITY` » (`docs/latent_manifold_findings.md` §9 et §10). | Poids situés dans la fonction inerte (E02) ; graines `abs(hash((map_name, td, local_idx)))` (`collect_fitness_data.py` l.194-196) non reproductibles d'un processus à l'autre. Conclusions classées « non établies ». | 2026-11-10 |
| X03 | « Les IOF Sprint Guidelines §4.5 demandent des amas de postes (désorientation). » | Introuvable dans les 22 PDF du dépôt (recherche « disorient », « cluster », « désorient », sections 4.x) ; seule mention d'amas : courses au score (*officials handbook*). | 2026-11-10 |
| X04 | « TD1–TD5 est l'échelle de niveaux IOF / FFCO. » | Échelle britannique ; FFCO = six couleurs (E17). | 2026-11-10 |
| X05 | « Jaune est plus facile que Vert » (`ffco_categories.json`, `App.jsx`). | Vert « très facile », jaune « moyen » (Guide des circuits de couleur, p. 2). | 2026-11-10 |
| X06 | « 406 et 407 sont du vert olive interdit » (`server.js` l.91-101). | 406, 407 = végétation, course ralentie, franchissable (ISOM 2017-2) ; l'olive est 520. | 2026-11-10 |
| X07 | Les neuf tables de symboles du dépôt (E04), dont « 3xx = végétation, 4xx = eau » (`aitraceur/controls/symbol_map.py`). | Jeux de symboles de référence ; annexe A1. | 2026-11-10 |
| X08 | « La triangulation vient du choix argmax et des distances à vol d'oiseau » (plans de juillet 2026). | Cause directe : récompense explicite des amas (E03). | 2026-11-10 |
| X09 | « Marquer les cellules dont le centre est dans un bâtiment suffit à le rendre étanche. » | E13 | 2026-11-12 |
| X10 | « Reboucher les passages diagonaux suffit. » | E13 (107 fuites sur 300) | 2026-11-12 |
| X11 | « Une grille de 2 m suffit en ville » (prototype, `profiles.py`). | E15 | 2026-11-10 |
| X12 | « Le détour mesure le choix d'itinéraire » (prototype, `model/leg.py` l.143-148). | Contre-exemple : autour d'un lac, deux itinéraires égaux ; le long d'un chemin sinueux, un seul ; même détour. Preuve exécutable : tests de la phase 5, étape 5.3. | 2026-11-12 |
| X13 | « Les 338 jambes annotées sont un corpus de bons interpostes. » | Ce sont des jambes du moteur v1 (E27) : jeu de **validation** des mesures, pas exemples à imiter. | 2026-11-12 |
| X14 | « Le score F1 de 0,814 du CNN mesure la qualité d'un poste. » | Il mesure la reconnaissance d'images de 256 × 256 pixels autour de postes réels ; il ne dit rien d'un interposte. Utilité à prouver : V06. | 2026-11-10 |
| X15 | « Ajuster un modèle de langage (`ffco-iof-v7`) est la voie vers l'expertise réglementaire. » | Son jeu d'entraînement enseigne l'échelle TD (E08) ; aucune citation de page ; remplacé par la recherche citée (phase 8). | 2026-11-10 |
| X16 | « Le PC du traceur n'a pas de carte graphique puissante » (hypothèse H1 initiale du plan). | E32 | 2026-11-14 |
| X17 | « On peut apprendre des circuits de Livelox en parcourant le site automatiquement. » | Interdit par les conditions du site et par son `robots.txt` (E34) ; de plus le site n'expose les cartes qu'en images, inutilisables par le moteur sans la carte vectorielle. Voies permises : phase 9, §7. | 2026-11-14 |

## À vérifier

| Id | Question | Comment | Quand |
|----|----------|---------|-------|
| V01 | Norme réelle de chacune des cartes du traceur. | Détection automatique, confirmée par le traceur | Phase 2 |
| V02 | Numérotation réelle des sous-symboles dans ses fichiers OCAD. | Sonde de l'étape 2.3.0 | Phase 2 |
| V03 | Passage minimal entre bâtiments en ISSprOM 2019 (0,40 mm attendu). | Lecture de la spécification | Phase 3 |
| V04 | Source « Guide du Traceur FFCO 2023 » de `ffco_categories.json`. | Demander le document au traceur ; d'ici là, distances par catégorie affichées « source non vérifiée » | Phase 4 |
| V05 | Ligne de base des tests du dépôt (non exécutés pendant l'analyse). | `pytest`, `vitest` | Phase 0 |
| V06 | Utilité du CNN pour classer des interpostes. | Gain de K8 avec et sans | Phase 9 |
| V07 | Format des parcours dans un fichier `.ocd`. | Sonde sur un fichier réel du traceur | Phase 9 |
| V08 | Unités et origine des coordonnées d'un fichier Purple Pen. | Sonde | Phase 9 |
| V09 | Les dix « choix du plan » des niveaux (A2 §7). | Revue de calage | Phase 4 |
| V10 | Classement des lignes marquées d'un astérisque (A1 §3.1). | Revue de calage (question 9) | Phase 4 |
| V11 | Hypothèses H1 à H4 (`00_LISEZ-MOI.md`). | **Résolu le 14 novembre 2026 → E32** | — |
| V12 | Durées sur le PC du traceur (K9). | Bancs des phases 3 et 5 | Phases 3, 5 |
| V13 | Couverture du MNT LiDAR HD sur les zones du traceur. | Tableau d'assemblage de l'IGN | Phase 10 |
| V14 | Lecture GeoTIFF sous Windows sans compilateur (`rasterio` ou `tifffile`). | Essai d'installation | Phase 10 |
| V15 | Modèles locaux disponibles et leur fiabilité (sortie JSON, appels d'outils) ; le schéma JSON d'Ollama garantit la forme, pas les valeurs. | Portes G1 à G4 sur la machine du traceur | Phase 8 |
| V16 | Droit de diffuser les PDF FFCO et IOF de `docs/` dans un dépôt public et dans un installateur. | **Résolu le 14 novembre 2026 → E33** | — |
| V17 | Import d'un IOF XML 3.0 exporté dans la version d'OCAD et dans Purple Pen du traceur. | Essai | Phase 11 |
| V18 | Pertinence des vitesses de la norme sur les terrains du traceur. | Traces GPX | Phase 9 |
| V19 | Disponibilité locale des huit cartes des jambes annotées. | Le traceur | Phase 5 |
| V20 | Fidélité et vitesse d'un rendu de carte dans le navigateur. | Porte P1 | Phase 11 |
| V21 | Livelox accorde-t-il l'accès à son API à AItraceur (application publique, libre) ? | Demande à info@livelox.com, si le traceur le souhaite | Dès la phase 6 (réponse attendue avant la phase 9) |
| V22 | Conditions d'utilisation des sites RouteGadget des clubs et de Vikazimut pour la collecte qui a servi au CNN ; visibilité des quatre jeux de données Kaggle. | Lecture des conditions ; vérification sur Kaggle ; consigner | Phase 1 (étape 1.11) |
| V23 | Mémoire vidéo exacte de la RTX 3060 du traceur (12, 8 ou 6 Go). | `nvidia-smi --query-gpu=name,memory.total --format=csv` | Phase 8 |
