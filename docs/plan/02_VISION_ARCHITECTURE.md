# 02 — Vision et architecture cible

## 1. La cible

**AItraceur est un assistant de traçage qui tourne entièrement sur le PC du traceur.** Il lit une
carte de CO (OCAD, plus tard OpenOrienteering Mapper), montre ce qu'il en a compris, propose des
interpostes adaptés à un niveau FFCO et à un format, les assemble en circuits, contrôle le résultat
contre des règles dont il cite la source, explique ses choix en français, et apprend des décisions
du traceur. Le traceur garde la main à chaque étape.

Ce que l'application n'est pas : un générateur « bouton magique » qui remplace la reconnaissance
terrain ; un service en ligne ; un modèle de langage qui pose des balises.

## 2. Sept principes

1. **La carte dit la vérité, le moteur ne devine pas.** Tout sens donné à un symbole vient d'un
   registre unique, par norme détectée. Un symbole inconnu est montré au traceur, jamais interprété
   en silence.
2. **L'interposte d'abord.** On génère et on note des jambes ; les postes en sont les extrémités.
3. **Des mètres, pas des degrés.** Toute la géométrie du moteur est dans le système projeté de la
   carte. Les degrés n'existent qu'à l'affichage.
4. **Le dur n'est pas le souple.** Interdit, inaccessible, distance minimale, niveau : ce sont des
   filtres, jamais des poids. Les préférences souples sont peu nombreuses, nommées, et chacune
   renvoie à une source ou à une mesure.
5. **Mesurer avant de régler.** Aucun réglage sans banc d'essai reproductible ; tout résultat va au
   registre « établi / réfuté » (annexe A3).
6. **Local et gratuit.** Par défaut, aucune requête réseau. Aucune API payante. Les modèles d'IA
   sont locaux et facultatifs : le moteur fonctionne sans eux.
7. **Le traceur décide.** Chaque proposition est accompagnée de ses raisons et reste modifiable ;
   chaque décision du traceur est une donnée d'apprentissage.

## 3. Chaîne de traitement

```
 fichier .ocd (.omap en phase 10)
        │  lecture : ocad2geojson (navigateur, ou Node pour le banc d'essai)
        ▼
 [A] PAQUET DE CARTE          symboles bruts + objets en mètres + géoréférencement      phase 2
        ▼
 [B] REGISTRE DE SYMBOLES     norme détectée → rôle de chaque symbole ; corrections      phase 2
        ▼                     du traceur ; observations de l'audit terrain (14b)
 [C] TERRAIN                  grille : franchissable / interdit / vitesse / lignes ;     phase 3
        ▼                     zones atteignables ; (relief : phase 10)
 [D] SITES                    éléments où poser un poste, côté d'accès, évidence          phase 3
        ▼
 [E] ITINÉRAIRES              champs de temps, itinéraires concurrents, lignes suivies,  phase 5
        ▼                     point d'attaque, ligne d'arrêt
 [F] JAMBES                   catalogue de jambes ; conformité et intérêt par niveau     phases 4, 6
        ▼
 [G] CIRCUITS                 assemblage sous contraintes (faisceau) ; plusieurs          phase 6
        ▼                     propositions
 [H] CONTRÔLE                 règles sourcées ; rapport                                   phase 7
        ▼
 [I] EXPLICATION, EXPORT      phrases construites sur les faits ; IOF XML ; PDF           phases 7, 8
        ▼
 [J] RETOURS                  choix et corrections du traceur, traces GPS → apprentissage phase 9
```

Chaque étage a une sortie inspectable dans l'interface. Si le traceur ne peut pas *voir* ce que le
moteur a compris (calque des interdits, sites refusés et pourquoi, itinéraires d'une jambe), on ne
peut ni lui faire confiance ni le corriger.

## 4. Ce que « comprendre la carte » veut dire

Les notions du traceur deviennent des **rôles** portés par les symboles (annexe A1) puis des
**mesures** portées par les jambes (phase 5).

| Notion du traceur | Rôle dans le registre | Mesure sur la jambe |
|-------------------|-----------------------|---------------------|
| Main courante (ligne directrice) | `ligne` : les trois « types de lignes » de la FFCO (*Traçage – Aspects pratiques*, p. 8 et 10) — L1 (route, chemin, sentier, clôture, mur, rivière, ligne électrique, bâtiment), L2 (sentier peu visible, talus, fossé net, ruisseau, lisière, haie, layon), L3 (limite de végétation, fossé intermittent, mur en ruine) ; drapeau `ouvert` pour les surfaces dégagées ; lignes de relief en phase 10 | part de l'itinéraire le long d'une ligne, par classe ; nombre de changements de ligne ; plus long tronçon hors ligne |
| Ligne d'arrêt | mêmes classes, plus les bords de surfaces nettes (lac, champ, zone pavée) | présence, distance et classe d'une ligne en travers derrière le poste |
| Point d'attaque, point d'appui | éléments ponctuels et nœuds de lignes, avec une note d'**évidence** de 1 (évident) à 4 (fin) | distance du dernier élément évident avant le poste ; nombre d'éléments franchis |
| Éléments dus à l'homme | bâtiments, murs, clôtures, tours, escaliers, ponts… | type du poste, obstacles sur l'itinéraire |
| Relief | buttes, dépressions, talus, ravines (symboles) ; pente, crêtes, rentrants (MNT, phase 10) | dénivelé de l'itinéraire, poste sur élément de relief |
| Végétation | cinq classes de vitesse de la norme ISOM (>100 %, 80–100, 60–80, 20–60, <20 %) ; infranchissable | temps par classe ; itinéraire qui contourne ou traverse |
| Interdit, infranchissable | `interdit` (olive, hors limites), `infranchissable` (bâtiment, mur, clôture, falaise, eau) | impossible par construction ; « piège d'interdit » compté pour le sprint |
| Niveau du coureur | six couleurs FFCO, règles T1–T17 (annexe A2) | niveau minimal exigé par la jambe ; intérêt de la jambe pour le niveau demandé |

## 5. Organisation du code

### 5.1 Arborescence cible

```
backend/src/aitraceur/            moteur v2 — ne dépend ni de FastAPI ni de src/services
  mapmodel/     package.py                         [A]
  symbols/      roles.py detect.py classify.py overrides.py  standards/  semantics/   [B]
  terrain/      grid.py rasterize.py layers.py reach.py                                [C]
  sites/        model.py extract.py                                                    [D]
  levels/       ffco.py formats.py                                                     (phase 4)
  routes/       cost.py timefield.py alternatives.py features.py                       [E]
  legs/         catalog.py fit.py interest.py                                          [F]
  courses/      model.py constraints.py assemble.py polish.py                          [G]
  rules/        registry.py checks.py explain.py                                       [H][I]
  io/           iofxml.py ppen.py ocad_courses.py omap.py
  learn/        corpus.py ranker.py speed.py prefs.py                                  [J]
  relief/       dtm.py slope.py landforms.py
  evalbench/    metrics.py replay_v1.py run.py                                         (phase 0)
backend/src/api/v2/               routes HTTP du moteur v2 (un fichier par domaine)
backend/tests/aitraceur/          tests du moteur v2 ; fixtures synthétiques
frontend/src/services/            mapPackage.js  apiV2.js
frontend/src/components/v2/       panneaux du moteur v2
docs/plan/                        ce plan ; REGISTRE.md
```

### 5.2 Sort de l'existant

| Existant | Devenir | Phase |
|----------|---------|-------|
| `backend/src/aitraceur/` (prototype non branché) | renommé `backend/src/aitraceur_proto/` pour libérer le nom, gelé, puis supprimé | P0 (renommage), P6 (suppression) |
| `services/generation/` (moteur v1) | corrections ciblées puis gel ; alimenté par des entrées justes (« pont v1 ») ; retiré après la porte de la phase 6 | P1, P2, P11 |
| Tables de symboles (`App.jsx`, `server.js`, `*.json`, `ISOM_DESCRIPTIONS`) | supprimées, remplacées par le registre | P2 |
| `services/controleur/` | gardé pour l'endpoint sprint v1 ; remplacé par `aitraceur/rules/` | P7, P11 |
| `services/rules/ffco_rules_engine.py`, `ffco_categories.json`, `placement_rules.json` | corrigés a minima (P1), remplacés par `aitraceur/levels/` | P1, P4 |
| CNN (`ocad_patch_scorer.py`, `control_scorer_cnn.onnx`), `HeatmapCache` | restent attachés au moteur v1 ; hors du moteur v2 sauf preuve d'utilité | P9 (preuve), P11 |
| Service de tuiles Node (port 8089) | gardé pour l'affichage tant qu'un rendu dans le navigateur n'est pas mesuré équivalent | P11 |
| `knowledge_base/` (RAG, assistant, `ffco-iof-v7`) | reconstruit avec numéros de page et citations | P8 |
| Scripts d'expériences de mai (`backend/scripts/analyze_*`, `benchmark_lri*`, LRI, profil 15D) | archivés ; conclusions classées « non établies » | P0 |
| OSM / Overpass, MapAnt, API IGN | désactivés par défaut, activables explicitement | P1 |
| Collecte Livelox (client, importeur, script, route `load-livelox`) | supprimée : contraire aux conditions du site | P1 |

### 5.3 Une lecture, deux hôtes

Le fichier OCAD est lu par **un seul code** (`frontend/src/services/mapPackage.js`, fonctions pures
au-dessus d'`ocad2geojson`), exécuté dans le navigateur à l'import et sous Node par le banc d'essai
(`frontend/scripts/ocd2package.mjs`). Le backend ne lit jamais de `.ocd` : il reçoit un paquet de
carte. Ainsi le banc d'essai et l'application voient exactement la même carte.

## 6. Technologies : un agent ? un modèle ? autre chose ?

Toutes les briques ci-dessous sont gratuites, sous licence libre, et tournent hors ligne.

| Brique | Verdict | Rôle | Phase |
|--------|---------|------|-------|
| **Registre de symboles** (données + code, 4 normes) | Indispensable — c'est la vraie « nouvelle technologie » du projet | Lire la carte juste | P2 |
| numpy, scipy, scikit-image, shapely, pyproj | Indispensables ; déjà utilisés (shapely à déclarer) | Grille de terrain, zones atteignables (`scipy.ndimage.label`), champs de temps (`skimage.graph.MCP_Geometric`) | P3, P5 |
| Recherche en faisceau (code maison, ~300 lignes) | Indispensable | Assembler les jambes en circuits | P6 |
| OR-Tools CP-SAT | Optionnel, plus tard | Assemblage optimal si le faisceau plafonne | après P6 |
| **Modèle de classement de jambes** (arbres boostés, apprentissage par paires) | Utile, sous condition de données | Apprendre ce qu'est un bon interposte à partir de circuits réels et des choix du traceur | P9 |
| Calage des vitesses sur traces GPX (régression robuste) | Utile | Temps réalistes par type de terrain et par niveau | P9 |
| CNN actuel (MobileNetV3) | À prouver, sinon retiré | Il note des images autour d'un point ; il ne sait rien d'un interposte | P9 |
| **LLM local** (Ollama) | Utile mais périphérique | Traduire un brief en paramètres, reformuler une explication, répondre sur les règles en citant la page | P8 |
| Ajustement de modèle (`ffco-iof-v7`) | Abandonné | Fragile, opaque, enseigne une échelle de niveaux fausse ; remplacé par la recherche documentaire citée | P8 |
| **Agent** (LLM + outils du moteur), serveur MCP | Interface, pas moteur | Dialoguer avec le moteur (« raccourcis de 500 m en gardant les postes 3 à 7 ») ; permet aussi à Claude Code de piloter le moteur pendant le développement | P8 |
| MNT LiDAR HD de l'IGN (Licence Ouverte 2.0) | Utile | Dénivelé, pente, éléments de relief ; fichiers téléchargés une fois, lus hors ligne | P10 |
| Lecture `.omap` | Utile | Boucler lidar-o → OpenOrienteering Mapper → AItraceur sans OCAD | P10 |
| Tauri v2 + PyInstaller | Produit | Un installateur Windows, un seul programme | P11 |

**Réponse nette à « un agent ? »** — Un agent n'améliorera pas la qualité des interpostes : il ne voit
pas la carte, il ne calcule pas d'itinéraire, et les petits modèles locaux se trompent dès qu'on
enchaîne plus de deux ou trois appels d'outils. Ce qui fait un bon interposte, c'est de la géométrie
et des règles de traçage ; c'est le moteur. L'agent devient intéressant *après*, comme façon de
parler au moteur. Le plan le place donc en phase 8, derrière un moteur fiable.

**Réponse nette à « un modèle ? »** — Oui, deux petits modèles appris, pas un gros : un classeur de
jambes et un modèle de vitesses. Ils demandent des données que seul le traceur possède (ses circuits,
ses traces, ses préférences) ; le plan les collecte dès la phase 6 et n'entraîne qu'en phase 9, avec
une règle simple : un modèle n'entre dans le moteur que s'il fait mieux que les règles sur des cartes
qu'il n'a jamais vues.

## 7. Faisabilité mesurée

Essais faits le 10 novembre 2026 sur une machine de test (un cœur, scikit-image 0.26, grilles
synthétiques). À refaire sur le PC du traceur en phase 3 et 5.

| Opération | Grille | Durée |
|-----------|--------|-------|
| Composantes connexes (`scipy.ndimage.label`) | 3000 × 3000 (1,5 km à 0,5 m) | 0,05 s |
| Champ de temps depuis un point, ville, fenêtre ±300 m | 1201 × 1201 à 0,5 m | 0,16 s |
| Champ de temps depuis un point, ville, fenêtre ±500 m | 2001 × 2001 à 0,5 m | 0,53 s |
| Champ de temps depuis un point, forêt 3 km × 3 km | 600 × 600 à 5 m | 0,15 s |
| idem | 1000 × 1000 à 3 m | 0,43 s |
| idem | 1500 × 1500 à 2 m | 1,08 s |
| Tracé d'un itinéraire à partir du champ | 730 cellules | 0,005 s |

Conséquences de conception :

- Avec 300 sites, préparer une carte coûte environ une minute en ville (0,5 m, fenêtre ±300 m) et
  jusqu'à cinq minutes en forêt à 2 m (fenêtre de 3 km) sur **un** cœur : d'où la fenêtre bornée à
  la longueur d'interposte utile et le calcul en parallèle (phase 5, §5.8). C'est un calcul fait une
  fois par carte et mis en cache sur disque.
- `MCP_Geometric.find_costs` n'offre plus de borne de coût (`max_cumulative_cost` est déprécié en
  0.26) : on borne par **fenêtre** autour du point de départ.
- Étanchéité des **traits** : un trait infranchissable doit marquer toute cellule dont le centre est
  à moins de 0,75 × la résolution. Essai : 0 fuite sur 400 traits aléatoires à 0,71 × et au-delà ;
  399 fuites sur 400 à 0,5 ×.
- Étanchéité des **surfaces** : marquer seulement les cellules dont le centre est dans l'obstacle
  laisse passer entre deux bâtiments qui se touchent par un coin dans 3 cas sur 4 (224 fuites sur
  300 à 0,5 m), et un rebouchage des diagonales n'en corrige qu'une partie (107 fuites sur 300).
  La **rastérisation prudente** — une cellule est libre si son centre est dans l'espace libre érodé
  de 0,7072 × la résolution — ne fuit jamais (0 sur 200 à 0,25, 0,5 et 1 m).
- Prix de la prudence : un passage n'est garanti ouvert qu'à partir de **3,2 cellules** de large
  (à 0,5 m : 1,6 m ouvert 200 fois sur 200, 1,2 m ouvert 36 fois sur 200 ; à 0,25 m : 0,8 m toujours
  ouvert). Or la norme demande 0,4 mm entre deux bâtiments (ISOM 2017-2, p. 21 et 70 ; valeur
  ISSprOM 2019 à vérifier en phase 3), soit 1,6 m au 1:4 000 et 1,2 m au 1:3 000. D'où la règle de
  la phase 3 : en ville, résolution = 0,40 mm × échelle ÷ 3,2, plafonnée à 0,5 m.
- À l'inverse, à 2 m de résolution (valeur du prototype pour la ville), une ruelle de 1,6 m est
  fermée 2 fois sur 3 même sans prudence : le prototype ne pouvait pas marcher en sprint.

## 8. Indicateurs de long terme

| Code | Indicateur | Cible | Mesuré à partir de |
|------|-----------|-------|--------------------|
| K1 | Postes en zone interdite ou inaccessible | 0 | P3 |
| K2 | Amas : nombre maximal de postes dans un rayon (60 m sprint, 150 m forêt) | ≤ 2 | P0 |
| K3 | Croisements d'interpostes par circuit | en baisse nette par rapport au moteur v1 | P0 |
| K4 | Couverture : part des 16 cases d'une grille 4 × 4 de la zone utile contenant un poste | en hausse par rapport au moteur v1 | P0 |
| K5 | Reproductibilité : même graine, même résultat | 100 % | P0 |
| K6 | Conformité au niveau : part des jambes conformes à la couleur demandée | 100 % | P6 |
| K7 | Préférence du traceur, à l'aveugle, moteur v2 contre v1 | ≥ 70 % | P6 |
| K8 | Rang des interpostes humains : centile médian des jambes réelles dans le classement du moteur | ≥ 70, puis en hausse | P9 |
| K9 | Préparation d'une carte ; génération d'un circuit | ≤ 3 min ; ≤ 20 s | P5, P6 |

K7 et K8 sont les seuls juges de la qualité. Les autres sont des garde-fous.

## 9. Risques et parades

| Risque | Parade |
|--------|--------|
| Cartes aux symboles « maison » (numéros hors norme) | Classement par numéro **et** par nom ; héritage du numéro principal ; tout inconnu est présenté au traceur, sa réponse est mémorisée par empreinte de carte. |
| Structures urbaines à plusieurs niveaux (passerelles, parkings) | Détectées (symboles dédiés) et exclues des propositions automatiques tant qu'elles ne sont pas modélisées ; signalées au traceur. |
| Trop peu de circuits réels pour apprendre | Le moteur à règles est complet sans apprentissage ; le modèle n'entre que s'il gagne sur des cartes jamais vues. |
| Calcul trop lent sur le PC du traceur | Résolution et nombre de sites paramétrables ; cache par carte ; budget mesuré à chaque phase (K9). |
| Dérive : on recommence à régler des poids | Règles de travail §6, point 1 ; registre A3 ; aucun poids sans source ou mesure. |
| Le moteur v2 ne convainc pas le traceur | Porte de décision en fin de phase 6 (K7) : le moteur v1 n'est retiré qu'après. |
