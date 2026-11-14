# Phase 9 — Apprentissage : circuits réels, préférences, vitesses

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

> Phase « lointaine » : objectif, interfaces, portes et critères. Avant de coder, écrire
> `docs/plan/P9_execution.md` (règles de travail §7).

## But

Faire entrer dans le moteur ce que seul le traceur possède : ses circuits, ses choix, ses traces.

1. **Mesurer** d'abord : à quel point le moteur classe-t-il bien les interpostes qu'un humain a
   réellement tracés (K8) ? Retrouve-t-il les postes humains parmi ses sites ?
2. **Apprendre** ensuite, si et seulement si les données suffisent : un petit modèle de classement
   de jambes, qui remplace les poids de départ de la phase 6.
3. **Caler** les vitesses par type de terrain sur des traces GPS.
4. **Trancher** le sort du réseau de neurones actuel (CNN) : preuve d'utilité, ou retrait.

Règle unique : **un modèle n'entre dans le moteur que s'il fait mieux que les règles sur des cartes
qu'il n'a jamais vues.**

## Ce que le traceur verra

- Un import de ses circuits passés (fichiers de parcours OCAD, Purple Pen, IOF XML) superposés à la
  carte, avec pour chacun : les postes reconnus comme sites, les jambes jugées conformes ou non à la
  couleur qu'il déclare, et le rang que le moteur donne à chaque jambe.
- Un tableau de bord : K8 par carte, avant et après apprentissage.
- Des temps d'itinéraire qui ressemblent aux siens.

## Prérequis

Phase 6 terminée (le moteur consigne les choix du traceur depuis 6.12). Les phases 7 et 8 ne sont
pas nécessaires. Hypothèse H3 confirmée le 14 novembre 2026 : le traceur a des circuits tracés à la
main sur ses cartes.

## Contexte vérifié (10 novembre 2026 — à relire au lancement)

- Importeurs existants : `services/importers/iof_xml_importer.py` (`IOFXMLImporter`, `XMLControl`,
  `XMLCourse`, fichier d'essai `backend/test_data/sample_event.iof.xml`) et `iof_importer.py`.
  Analyse de traces : `services/analysis/gpx_parser.py`, `multi_gpx_analyzer.py` ; composant
  `GpxImporter.jsx`.
- Un fichier OCAD peut contenir des parcours : symboles de surimpression (701 départ, 703 poste,
  706 arrivée…) et chaînes de paramètres (`ocadFile.parameterStrings`), dont `ocad2geojson` donne
  l'accès brut. **Leur format exact reste à relever sur un fichier réel du traceur** (sonde ci-dessous).
- Les 338 jambes annotées (`output/annotations_*.csv`) sont des jambes de circuits **générés par le
  moteur v1**, étiquetées par le traceur : un jeu de validation des mesures (phase 5), pas un corpus
  de bons interpostes.
- CNN : `backend/data/models/control_scorer_cnn.onnx` (MobileNetV3-Small), entraîné sur des images
  de 256 × 256 pixels autour de postes réels (F1 0,814 sur ces images). Il note un **point** d'après
  une image ; il ne sait rien d'un interposte. Son entraînement passe par Kaggle (en ligne) ; la
  carte graphique du traceur (RTX 3060) permet de le refaire sur son PC si la preuve du §6 l'exige.
- `xgboost`, `scikit-learn` sont déjà dans `backend/requirements.txt`.
- lidar-o applique déjà la discipline voulue (`docs/bilan_v0.md` : registre établi / réfuté,
  validation par zones entières jamais vues) : même méthode ici.

## Conception

### 1. Corpus de circuits réels — `aitraceur/io/`, `aitraceur/learn/corpus.py`

Trois lecteurs, une seule sortie :

```python
@dataclass(frozen=True)
class RealCourse:
    map_id: str; name: str
    color: Color | None; fmt: Format | None      # déclarés par le traceur à l'import
    points_xy: tuple[tuple[float, float], ...]   # départ, postes, arrivée — mètres, repère de la carte
    source: str                                  # "ocd" | "ppen" | "iofxml"
```

| Lecteur | Fichier | À faire d'abord |
|---------|---------|-----------------|
| `io/iofxml.py` | IOF XML 3.0 (`CourseData`) | Reprendre l'analyse de `IOFXMLImporter` ; positions en `MapPosition` (mm sur la carte) ou en coordonnées géographiques. |
| `io/ppen.py` | Purple Pen (`.ppen`, XML) | Sonde sur un fichier réel : unités et origine des coordonnées. |
| `io/ocad_courses.py` + `frontend/scripts/probe_ocd_courses.mjs` | Fichier de parcours OCAD | Sonde : symboles dont `csObjType` est non nul, objets de ces symboles, chaînes de paramètres des types « objet de parcours » et « parcours ». Figer le format par des tests avant d'écrire le lecteur. |

Les circuits importés vivent dans `{DATA_DIR}/corpus/` (jamais dans le dépôt : ce sont les données
du traceur). Chaque circuit est rattaché à une carte par son empreinte.

### 2. Trois mesures, avant tout apprentissage — `aitraceur/learn/measure.py`

| Mesure | Définition | Lecture |
|--------|------------|---------|
| **Rappel des sites** | part des postes humains à moins de 10 m (ville) ou 25 m (forêt) d'un site valable du moteur | En dessous de 90 % : l'extraction des sites (phase 3) ou le registre (phase 2) manque quelque chose. Les postes non retrouvés sont listés avec leur symbole le plus proche. |
| **Conformité humaine** | part des jambes humaines jugées conformes à la couleur déclarée | En dessous de 85 % : un paramètre de niveau (A2 §7) est trop strict, ou une mesure se trompe. Les refus sont listés par paramètre. |
| **K8 — rang des jambes humaines** | pour chaque jambe humaine A → B : son centile d'intérêt parmi les jambes conformes du catalogue partant de A, de longueur comparable (±30 %) | Médiane ≥ 70 : le moteur « aime » ce que le traceur trace. |

Ces trois mesures valent à elles seules la phase : elles disent **où** le moteur se trompe.
Résultats dans `docs/plan/mesures/P9_corpus.md`, par carte.

### 3. Modèle de classement de jambes — `aitraceur/learn/ranker.py`

- **Exemples** : chaque jambe humaine A → B est préférée à des jambes conformes du catalogue partant
  de A, de longueur comparable, tirées au hasard (20 par jambe humaine) ; s'y ajoutent les
  préférences consignées depuis la phase 6 (jambe choisie contre jambes proposées non choisies ;
  poste remplacé : nouvelle jambe contre ancienne).
- **Variables** : uniquement des mesures de `LegFacts` et du niveau — nombre de choix, écart de
  temps, séparation, détour, parts par classe de ligne et de vitesse, plus long tronçon hors ligne,
  nombre de changements de ligne et de direction, distances du point d'attaque et de la ligne
  d'arrêt, évidence des deux sites, longueur relative à la fourchette du format. Aucune coordonnée,
  aucun identifiant de carte.
- **Modèle** : arbres boostés à objectif de classement par paires (`xgboost`, `rank:pairwise`), peu
  profond (profondeur 3, 200 arbres au plus), un modèle par groupe (ville ; forêt vert-bleu ; forêt
  jaune-noir). Entraînement en quelques secondes sur le PC, sans carte graphique, hors ligne.
- **Usage** : la note du modèle, ramenée à 0..1 par rang dans le catalogue, remplace
  `Interest.score`. Les contraintes dures et la conformité ne sont **jamais** apprises.
- **Explication** : pour chaque jambe, les trois variables qui pèsent le plus (contributions par
  arbre) alimentent `reasons_fr`.

### 4. Préférences

H3 est confirmée : les préférences complètent les circuits réels, elles ne les remplacent pas. Si un
groupe (ville ; forêt vert-bleu ; forêt jaune-noir) manque de circuits réels, son modèle attend que
les événements de la phase 6 fournissent au moins 300 paires sur 4 cartes ; d'ici là, les
comparaisons à l'aveugle (6.11) restent le seul juge pour ce groupe.

### 5. Vitesses — `aitraceur/learn/speed.py`

- Entrée : traces GPX du traceur (et de coureurs volontaires), rattachées à une carte et, si
  possible, à un niveau.
- Traitement : projection dans le repère de la carte ; lissage ; découpe en tronçons de 20 à 50 m ;
  pour chaque tronçon : longueur par classe de vitesse traversée, nombre de franchissements par
  famille, durée. Écarter les arrêts (vitesse < 0,3 m/s pendant plus de 5 s : poste ou hésitation).
- Modèle : régression robuste (Huber) de la durée sur les longueurs par classe et les nombres de
  franchissements → secondes par mètre pour V1 à V5, secondes par franchissement ; une allure de
  référence par coureur (effet fixe) pour comparer des coureurs de niveaux différents.
- Sortie : un fichier `{DATA_DIR}/speed_profile.json` qui remplace `CostConfig.speed_ratio` et les
  `cross_penalty_s` de départ ; les valeurs de la norme restent le repli.
- Le dénivelé n'entre dans la régression qu'après la phase 10.

### 6. Le CNN : preuve ou retrait

Ajouter au modèle de classement deux variables — la note du CNN au site d'arrivée et au site de
départ (image rendue autour du site, comme aujourd'hui) — et comparer K8 avec et sans, en
validation croisée par carte. Gain médian inférieur à 2 points : le CNN, `HeatmapCache` et leurs
scripts sont retirés en phase 11.

### 7. Sources externes de circuits

**Ce qui est exclu.** Parcourir Livelox automatiquement pour en extraire circuits, cartes ou traces.
Faits vérifiés le 14 novembre 2026 (registre E34) :

- conditions d'utilisation de Livelox (version du 7 août 2026), « Use of Our Services » : il est
  interdit « to systematically extract data from the services except through authenticated and
  authorized API access » ; « All rights to maps and courses uploaded to Livelox are reserved by
  the event organizers » ;
- `https://www.livelox.com/robots.txt` interdit `/Viewer/` (la visionneuse des circuits et des
  traces) à tous les robots ;
- l'API publique est accordée au cas par cas, « intended for publicly available applications, not
  private or personal use » ; « Maps are not available through the API » ; « Routes are not
  available through the API ».

Le client du dépôt qui contournait la clé (connexion avec un compte personnel, imitation d'un
navigateur) est supprimé en phase 1 (étape 1.11).

**Ce qui est permis, par ordre d'intérêt pour le moteur :**

| Source | Ce qu'elle apporte | Condition | Valeur pour le moteur |
|--------|--------------------|-----------|-----------------------|
| Fichiers des clubs et organisateurs (OCAD avec circuits, Purple Pen, ou IOF XML + carte OCAD) | carte **vectorielle** + circuits réels + couleurs | accord écrit (un courriel suffit) : usage local d'entraînement, aucune rediffusion, suppression sur demande | **la meilleure** : le moteur lit la carte et analyse chaque jambe (§1 à §3) |
| API Livelox, si Livelox l'accorde à AItraceur (application publique, libre, AGPL) | circuits en IOF XML : postes en coordonnées, classes ; ni carte ni trace | demande à info@livelox.com ; cache local, peu de requêtes, « Livelox » cité comme source | (a) circuits courus sur des cartes que le traceur possède en OCAD : analyse complète ; (b) statistiques par classe (longueurs d'interposte, nombre de postes) pour caler les « choix du plan » de l'annexe A2 §7 |
| Traces GPS de coureurs (club du traceur) | itinéraires réellement choisis, temps | consentement de chaque coureur | vitesses (§5) ; validation du nombre de choix d'itinéraire (phase 5) |

Pour chaque source utilisée, une entrée au registre : provenance, accord (date, forme), données
gardées. Les circuits importés portent leur provenance dans `RealCourse.source`.

**Pourquoi la carte vectorielle compte plus que le volume.** Une carte affichée sur un site est une
image : le moteur ne sait pas y distinguer une clôture d'un chemin. Mille circuits sans leur carte
OCAD n'apprennent au moteur que des longueurs et des angles ; vingt circuits avec leur carte lui
apprennent ce qui fait un bon interposte (§2 et §3).

## Étapes (à détailler dans `P9_execution.md`)

0. Collecte (§7) : demandes aux clubs et organisateurs ; si le traceur le souhaite, demande d'accès à
   l'API Livelox. À lancer dès la phase 6 : les réponses prennent des semaines.
1. Sondes OCAD et Purple Pen sur des fichiers réels ; lecteurs ; import dans l'interface avec
   déclaration de la couleur et du format.
2. Les trois mesures du §2 sur tout le corpus ; lecture des résultats avec le traceur ; corrections
   des phases 2, 3, 4 ou 5 que ces mesures révèlent (chacune avec son test).
3. Jeu d'exemples, entraînement, validation croisée « une carte laissée de côté ».
4. Calage des vitesses.
5. Preuve du CNN.
6. Intégration des modèles retenus derrière un réglage (`AITRACEUR_RANKER=regles|appris`), banc
   comparatif, nouvelle série de comparaisons à l'aveugle (règles contre appris).

## Portes de décision

| Porte | Condition | Sinon |
|-------|-----------|-------|
| Données | au moins 150 jambes humaines sur au moins 5 cartes pour un groupe | pas de modèle pour ce groupe ; on garde les règles |
| Classement | en validation « une carte laissée de côté » : K8 médian en hausse d'au moins 5 points par rapport aux règles, et aucune carte en baisse de plus de 5 points | le modèle n'est pas intégré ; le résultat est consigné comme réfuté |
| Aveugle | le traceur préfère « appris » à « règles » dans au moins 60 % de 20 comparaisons | le modèle reste une option désactivée |
| Vitesses | erreur médiane sur les temps de tronçons de traces **non vues** en baisse d'au moins 10 % par rapport aux vitesses de la norme | on garde la norme |
| CNN | gain de K8 ≥ 2 points | retrait en phase 11 |

## Critères d'acceptation

1. Les trois mesures du §2 sont publiées par carte ; rappel des sites ≥ 90 % et conformité humaine
   ≥ 85 % sur le corpus, ou chaque écart est expliqué et suivi d'une correction.
2. Chaque porte a un verdict écrit au registre (établi ou réfuté), avec la commande qui le
   reproduit.
3. Aucun entraînement ne demande de réseau ; seul un éventuel réentraînement du CNN utilise la carte
   graphique.
4. Le moteur fonctionne à l'identique sans aucun fichier de modèle (repli sur les règles).

## Hors périmètre

- Toute collecte automatique sur un site tiers sans autorisation écrite (§7).
- Apprentissage profond sur l'image de la carte.
- Génération de circuits par un modèle : l'assemblage reste une recherche sous contraintes.

## Pièges

- **Fuite entre cartes** : ne jamais mélanger les jambes d'une même carte entre entraînement et
  validation. Une validation aléatoire donnerait un excellent score sans rien prouver.
- Les jambes « négatives » tirées du catalogue ne sont pas mauvaises, seulement non choisies : le
  modèle apprend une préférence, pas une vérité. D'où la porte « aveugle ».
- Un circuit humain ancien peut avoir été tracé sur un état antérieur de la carte : écarter les
  circuits dont plus d'un poste sur cinq n'est pas retrouvé parmi les sites.
- Les couleurs déclarées par le traceur sont la vérité de la conformité humaine : les lui demander,
  ne pas les deviner d'après la longueur.
- Peu de données : préférer un modèle très simple et le dire, plutôt qu'un modèle riche qui
  mémorise cinq cartes.
