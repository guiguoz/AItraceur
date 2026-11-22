# Annexe A2 — Référentiel des niveaux FFCO

Cette annexe est la source du fichier `backend/src/aitraceur/levels/ffco_levels.json` (phase 4).
Elle remplace l'échelle « TD1 à TD5 » du code actuel, qui est l'échelle britannique et non celle de
la FFCO (constat C6 de l'état des lieux).

Chaque ligne dit d'où elle vient : un document du dossier `docs/` du dépôt, avec sa page dans le
PDF, ou la mention **choix du plan** quand la FFCO ne donne pas de chiffre. Les choix du plan sont
des valeurs de départ, soumises au traceur en phase 4 (§6).

## 1. Documents

| Abréviation | Fichier dans `docs/` | Pages |
|-------------|----------------------|-------|
| **MF** | `Méthode Fédérale - Edition 2016.pdf` | 23 |
| **GC** | `Guide de mise en place des circuits de couleur 2024.pdf` (éd. déc. 2024) | 13 |
| **RTS** | `RTS_CO_(Ed.mai2025)_b6e41MU.pdf` — *Règles techniques et de sécurité en Course d'Orientation*, éd. mai 2025 | 12 numérotées |
| **TP** | `TRACAGE PRINCIPES.pdf` | 19 |
| **TAP** | `TRACAGE ASPECTS PRATIQUES.pdf` | 26 |

Les numéros de page sont ceux du PDF (page 1 = couverture), sauf pour le RTS, cité par sa
numérotation imprimée « n/12 ».

## 2. Les six couleurs

| Couleur | Difficulté (GC p. 2) | Étape de la Méthode fédérale | Règles de traçage | Âge et temps de course maximal préconisé (RTS §3.2.1, p. 8/12) |
|---------|----------------------|------------------------------|-------------------|--------------------------------------------|
| vert | très facile | Acquisition des fondamentaux (MF p. 4) | T1, T2, T3 | niveau maximal des 10 ans et moins ; 30 min |
| bleu | facile | Acquisition des techniques de base (MF p. 5) | T4 à T7 | niveau maximal des 11-12 ans ; 40 min |
| jaune | moyen | Notions de relief, de végétation, de visée (MF p. 6) | T8, T9 | niveau maximal des 13-14 ans ; 60 min |
| orange | difficile | Acquisition des automatismes de base (MF p. 7) | T10, T11, T12 | niveau maximal des 15-16 ans ; 80 min |
| violet | très difficile | Anticipation et adaptation (MF p. 8) | T13, T14 | plus de 16 ans |
| noir | extrême | Stratégie et performance (MF p. 9) | T15, T16, T17 | plus de 16 ans |

La correspondance couleur ↔ étape n'est pas écrite en toutes lettres dans le texte de la Méthode :
elle est portée par la **couleur du bandeau** de chaque tableau (vert p. 4, bleu p. 5, jaune p. 6,
orange p. 7, violet p. 8, noir p. 9), vérifiée sur le rendu des pages, et confirmée par TAP §2
(« Parcours VERT » T1–T3 p. 7-8, « Parcours BLEU » p. 9-10, « Parcours JAUNE » p. 11-12).

Le sprint n'a que trois niveaux (GC p. 5 : bleu, jaune, orange), décrits à part par la Méthode
(MF p. 10 à 13) avec leurs propres règles, elles aussi notées T1, T2, T3 : bandeau bleu p. 10,
jaune p. 12, orange p. 13. Pour éviter toute confusion, le moteur les nomme `S1`, `S2`, `S3`.

## 3. Forêt : ce que dit la FFCO, niveau par niveau

### Vert — T1 à T3

> « T1 : Le parcours doit être tracé sur un terrain comportant des éléments de planimétrie évidents
> et reliés entre eux. Les postes sont toujours sur des lignes identiques et aux changements de
> direction. Un seul itinéraire possible. Le point d'attaque est confondu avec le poste. Choisir des
> postes faciles : bâtiment, jonction ou croisement de chemins. » (MF p. 4)
>
> « T2 : mêmes caractéristiques : seuls seront proposés des changements de lignes au poste.
> T3 : mêmes caractéristiques : proposer des changements de lignes durant l'itinéraire. Ne pas
> proposer plus de deux changements de lignes durant le circuit. » (MF p. 4)

Compléments : « Il est obligatoire de "conduire" le jeune orienteur tout le long du parcours »
(TAP p. 9) ; lignes de niveau 1 seulement, et surfaces non boisées à bonne visibilité (TAP p. 7-8) ;
« Parcours partiels courts. Ils ne doivent pas inciter à l'utilisation de la boussole » ; le poste
« doit être situé sur la ligne directrice ou visible de celle-ci » (TP §2.3.3.1, p. 3-4).

### Bleu — T4 à T7

> « La difficulté du parcours reste identique au niveau précédent : éléments de planimétrie évidents
> et reliés entre eux par des chemins, des sentiers des espaces découverts, bâtiments,… Postes
> évidents faciles à identifier. Possibilités d'utiliser des rochers falaises, clôtures…
> T4 : Les postes sont à proximité des lignes et du point d'attaque mais parfaitement visibles de
> celui-ci et facile à identifier, avec des lignes d'arrêt évidentes derrière le poste. Des choix
> d'itinéraires sur des lignes de nature et de « courabilité » identiques peuvent être proposés
> T5 : orientation sur diverses lignes de nature et de difficultés différentes
> T6 : possibilité de couper (saut) sur des terrains totalement ouverts avec des lignes d'arrêt
> évidentes. La visibilité des lignes doit être parfaite
> T7 : Saut de lignes, orientation sommaire facile vers des lignes d'arrêt sûres. La visibilité est
> très bonne et les distances sont inférieures à 200m » (MF p. 5)

Complément : « ce saut ne doit jamais dépasser 100 m s'il y a recours à la boussole » (TAP p. 9) ;
les lignes 2 et 3 sont introduites à ce niveau (TAP p. 10) ; « Positionner le premier poste de
préférence au changement de direction » (TAP p. 10).

### Jaune — T8, T9

> « Le parcours est tracé sur un terrain plus difficile mais la pénétrabilité doit rester bonne. Le
> terrain doit être constitué d'un réseau de lignes de nature différentes (sentiers, fossés, limite
> de végétation) et de zones découvertes. Les postes deviennent plus difficiles (sommet de colline,
> entre les collines, rocher, butte) mais toujours précédés d'un point d'attaque net.
> T8 : proposer des choix d'itinéraire et de l'orientation de précision dans l'approche du poste sur
> des éléments de planimétrie encadrés de lignes d'arrêt évidentes.
> T9 : orientation à partir de la lecture de relief facile. Poste au sommet des collines.
> Possibilité d'utiliser des lignes de crêtes ou des rentrants bien marqués comme ligne directrice
> ent[r]e 2 postes » (MF p. 6)

Complément : pour les 13-14 ans, « rechercher des choix d'itinéraire simples, mais conserver un
élément d'attaque et d'arrêt à proximité du poste, nettement identifiable » (TP §2.3.3.3, p. 4).

### Orange — T10 à T12

> « Les tracés doivent se faire sur des terrains très pénétrables moyennement accidentés dans des
> zones boisées avec de nombreuses parties découvertes. Éviter les terrains difficilement
> pénétrables. Les détails du terrain sont facilement identifiables. À la différence des circuits
> faciles, les postes peuvent être des éléments de relief (colline, dépression, avancée bien marquée
> ou falaise) avec obligatoirement un point d'attaque précis situé à moins de 200 m du poste et une
> ligne d'arrêt claire. […]
> T10 : proposer de l'orientation sommaire avec des points d'appui et des points d'attaque évidents.
> T11 – T12 : proposer de l'orientation de précision en direction de postes au relief assez simple
> avec des lignes d'arrêt évidentes. » (MF p. 7)

### Violet — T13, T14

> « Le[s] traçage, à ce niveau, doit exiger de la part du coureur des capacités à planifier son
> itinéraire et d'adapter sa vitesse de course (sûreté et prise de risque) en fonction du terrain et
> de ses capacités personnelles. L'attaque du poste se fait sans ligne d'arrêt
> évidente derrière le poste. Utilisation de tous les types de terrain sauf les très difficiles
> physiquement. T13 : postes sans lignes d'arrêt évidentes. T14 : attaque du poste dans une zone
> avec peu de détails. » (MF p. 8)

### Noir — T15 à T17

> « Les caractéristiques du traçage sont les suivantes : orientation dans les zones de relief
> difficiles ; Utilisation de terrains riches en détails et petits détails ; Absence de mains
> courantes ; Visibilité réduite. T15 : proposer des choix d'itinéraire difficiles. T16 : proposer
> de l'orientation sommaire avec lecture de relief difficile. Terrain très difficile avec de
> l'orientation dans les flancs. T17 : proposer de l'orientation fine en terrain détaillé. »
> (MF p. 9)

Complément pour tous les adultes confirmés : « Un itinéraire comportant une ligne directrice ou un
élément d'arrêt trop évident ne doit jamais être l'alternative la plus rapide entre deux postes »
(TP §2.3.3, p. 4-5).

## 4. Forêt : paramètres du moteur

`—` : sans objet. « plan » : choix du plan, à valider (§6). Les mesures (colonne de gauche) sont
celles de la phase 5.

| Paramètre (`LevelSpec`) | vert | bleu | jaune | orange | violet | noir | Source |
|-------------------------|------|------|-------|--------|--------|------|--------|
| `site_max_obviousness` | 2 | 3 | 4 | 4 | 4 | 4 | MF p. 4-6 ; TP §3.5.1 p. 9 |
| `site_on_line` : le poste est sur une ligne | L1 obligatoire | — | — | — | — | — | MF T1 |
| `site_max_dist_to_line_m` | 0 | 30 | — | — | — | — | MF T4 « à proximité des lignes » ; valeur : plan |
| `handrail_classes` : lignes utilisables | L1 + `ouvert` | L1, L2, L3 + `ouvert` | toutes | toutes | toutes | toutes | TAP p. 7-8 et p. 10 |
| `max_offline_m` : plus long tronçon hors ligne | 0 | 100 ; 200 si tout le tronçon est en terrain `ouvert` et qu'une ligne d'arrêt le ferme | sans limite | sans limite | sans limite | sans limite | TAP p. 9 (100 m) ; MF T6-T7 (200 m) |
| `attack_max_m` : point d'attaque au plus à | 0 (confondu) | 50 | 150 | 200 | — | — | MF T1 ; MF T4 « parfaitement visibles de celui-ci » (valeur : plan) ; MF p. 6 (valeur : plan) ; MF p. 7 (200 m) |
| `attack_max_obviousness` | — | 2 | 2 | 3 | — | — | MF « net », « précis » ; valeurs : plan |
| `catching` : ligne d'arrêt derrière le poste | — | exigée à 50 m | exigée à 100 m | exigée à 150 m | **absente** sur au moins un tiers des postes | indifférent | MF T4, T8, p. 7, T13 ; distances : plan |
| `route_choice` | aucun | sur lignes | simple | libre | libre | difficile | MF T1, T4, T8, T15 |
| `max_midleg_line_changes_course` | 2 | — | — | — | — | — | MF T3 |
| `max_unmarked_turns_leg` : changements de direction sans poste | 1 | — | — | — | — | — | MF T1 « aux changements de direction » ; tolérance : plan |
| `handrail_fastest_forbidden` : la main courante évidente ne doit pas être le plus rapide | non | non | non | non | oui | oui | TP §2.3.3 p. 4-5 |
| `speed_classes_allowed` | V1, V2 | V1, V2 | V1–V3 | V1–V3 | V1–V4 | toutes | MF p. 6 « pénétrabilité bonne », p. 7 « très pénétrables », p. 8 ; découpage : plan |
| `max_time_min` | 30 | 40 | 60 | 80 | — | — | RTS §3.2.1 |
| `pace_factor` : allure relative au niveau noir | 2,5 | 2,2 | 1,9 | 1,5 | 1,25 | 1,0 | plan (calé en phase 9) |

Lecture de `route_choice` :

| Valeur | Sens pour le moteur |
|--------|---------------------|
| aucun | Un seul itinéraire raisonnable : toute variante coûte au moins 50 % de plus (plan). |
| sur lignes | Des variantes sont permises si chacune suit des lignes autorisées de bout en bout. |
| simple | Deux variantes au plus, clairement séparées. |
| libre | Aucune contrainte ; le choix d'itinéraire est recherché. |
| difficile | Au moins un tiers des jambes longues offrent un vrai choix (plan). |

## 5. Sprint : ce que dit la FFCO et paramètres

> « […] les parcours doivent tester et valoriser la capacité des coureurs à planifier et à réaliser
> des choix d'itinéraire à vitesse élevée sous la pression du temps. […] l'enjeu ne réside pas dans
> la découverte des postes mais bien dans l'itinéraire qui les relie. » (MF p. 10)

| | S1 — bleu (MF p. 10) | S2 — jaune (MF p. 12) | S3 — orange (MF p. 13) |
|---|---|---|---|
| Texte | « Le nombre maximum de changements de direction ou angles entre 2 postes doit être de 3 » ; « choix d'itinéraire simples » ; « la position du poste ne doit pas induire le choix d'itinéraire (poste devant ou derrière un élément infranchissable par exemple) » ; « les définitions doivent rester simples » | « Nombre maximum de changements de direction ou angles entre 2 postes = 5 » ; « Proposer des obstacles, zones interdites sur l'itinéraire et non en approche de poste » ; « Le tracé peut inclure des dénivelées qui ne doivent pas obliger les coureurs à marcher » | « planifier son itinéraire rapidement dans un environnement complexe » ; « une utilisation optimale du maillage des rues » ; « des sorties de poste qui doivent générer des problèmes de planification » ; « l'utilisation de tous les obstacles infranchissables ou non (clôtures, murs), des escaliers, passages souterrains » |
| Commun à S1 et S2 | « La découverte des postes ne doit pas être difficile. » | | |

« Changement de direction » est défini p. 10 : « les carrefours de rues, les rues "sinueuses"
comportant des angles, les obstacles ou tout autre élément pouvant provoquer un angle ».

| Paramètre (`LevelSpec`) | S1 bleu | S2 jaune | S3 orange | Source |
|-------------------------|---------|----------|-----------|--------|
| `max_turns_leg` | 3 | 5 | sans limite | MF p. 10, p. 12 |
| `turn_angle_deg` : angle à partir duquel on compte un changement | 45 | 45 | 45 | plan |
| `barrier_at_control` : poste collé à un infranchissable qui commande l'itinéraire | interdit | interdit | permis | MF p. 10, p. 12 |
| `barrier_on_route` : obstacles et interdits sur l'itinéraire | à éviter | recherchés | recherchés | MF p. 10 (« vigilant »), p. 12, p. 13 |
| `site_max_obviousness` | 4 | 4 | 4 | En ville, tout élément cartographié convient : « l'enjeu ne réside pas dans la découverte des postes » (MF p. 10) |
| `site_max_similar_nearby` : autres éléments de même nature à moins de 30 m | 2 | 2 | sans limite | MF « La découverte des postes ne doit pas être difficile » ; seuil : plan |
| `route_choice` | simple | libre | libre | MF |
| `multi_level` : passages souterrains, structures à étages | interdit | interdit | exclu tant que non modélisé | MF p. 13 ; A1 §3.3 |
| `pace_factor` | 2,0 | 1,5 | 1,2 | plan |

Distances minimales entre postes, tous niveaux de sprint : « pour des échelles 1:4000 et 1:3000 :
la distance minimum entre 2 postes est de 25m en distance de course et de 15m à vol d'oiseau »
(RTS, « Distance minimale entre les postes », p. 9/12).
Échelles 1:7 500, 1:10 000 et 1:15 000 : « les postes ne doivent pas être placés à moins de
30 mètres à vol d'oiseau les uns des autres. Deux postes disposés sur deux éléments de même nature
ne peuvent être à moins de 60m à vol d'oiseau l'un de l'autre » (RTS p. 9/12 ; même règle dans
TP §3.5.6, p. 10).

## 6. Formats et distances

« Les épreuves de longue distance (LD) doivent privilégier les choix d'itinéraire, les épreuves de
moyenne distance (MD) doivent privilégier la recherche de postes, les épreuves de sprint doivent
privilégier les choix d'itinéraire sous une charge mentale et une pression du temps important. »
(GC p. 3)

Distances indicatives (GC p. 4-5). En forêt, ce sont des distances « optimum comprenant le
dénivelé sur la base de la règle 100 mètres de dénivelé positif = 1 kilomètre en terrain plat » ;
en sprint, des distances « réelles de course en prenant en compte les itinéraires les plus courts ».

| Couleur | Longue distance (circuit « long ») | Moyenne distance | Sprint |
|---------|------------------------------------|------------------|--------|
| noir ou violet | 8 – 12 km | 4 – 6 km | — |
| orange | 5 – 8 km | 3 – 4 km | 2,3 – 3,8 km |
| jaune | 4 – 5 km | 2 – 4 km | 1,8 – 2,8 km |
| bleu | 3 – 4 km | 2 – 3 km | 1 – 1,8 km |
| vert | 2 – 3 km | 2 – 2,5 km | — |

Dénivelé : « La dénivelée positive ne doit pas excéder 4 % de la longueur totale du parcours par
l'itinéraire le plus logique » (TP §3.11.6, p. 17 ; le RTS, p. 8/12, en fait une recommandation).

Conséquence pour le moteur : en forêt, la longueur d'un circuit se mesure sur les **itinéraires**
(et non à vol d'oiseau) et s'exprime en « kilomètres-effort » ; tant que le relief n'est pas connu
(avant la phase 10), le dénivelé vaut zéro et l'interface l'affiche (« dénivelé non pris en
compte »).

## 7. Paramètres à valider avec le traceur (revue de calage, phase 4)

Ce sont tous les « choix du plan » ci-dessus. Le traceur les valide ou les corrige une fois ; sa
réponse est consignée dans `levels/ffco_levels.json` avec `source: "traceur, <date>"`.

| # | Paramètre | Valeur de départ | Question posée au traceur |
|---|-----------|------------------|---------------------------|
| 1 | `site_max_dist_to_line_m` (bleu) | 30 m | Jusqu'à quelle distance d'un chemin un poste bleu reste-t-il « à proximité » ? |
| 2 | `attack_max_m` (bleu, jaune) | 50 m, 150 m | À quelle distance maximale doit se trouver le point d'attaque ? |
| 3 | Distance de recherche de la ligne d'arrêt (bleu, jaune, orange) | 50, 100, 150 m | Au-delà de quelle distance une ligne derrière le poste n'arrête plus le coureur ? |
| 4 | `max_unmarked_turns_leg` (vert) | 1 | Tolère-t-on un changement de direction sans poste sur un circuit vert ? |
| 5 | Seuil de « un seul itinéraire » (vert) | variante ≥ +50 % | À partir de quel écart une variante n'en est-elle plus une pour un enfant ? |
| 6 | `turn_angle_deg` (sprint) | 45° | Quel angle compte comme un changement de direction ? |
| 7 | `speed_classes_allowed` | voir §4 | Accepte-t-on du vert 2 (marche) sur un circuit orange ? |
| 8 | `pace_factor` | voir §4 et §5 | Allures de référence par couleur sur ses terrains. |
| 9 | Classement des lignes à astérisque (A1 §3.1) | L2\* ou L3\* | Une falaise, une ravine sont-elles des lignes pour un niveau bleu ? |
| 10 | Part des postes violets sans ligne d'arrêt | un tiers | Proportion attendue. |

## 8. Ce que cette annexe ne couvre pas

- La correspondance catégorie (H10, D14, H21E…) ↔ circuit : seuls les plafonds par âge du RTS sont
  repris (§2). Le fichier actuel `backend/data/ffco_categories.json` cite un « Guide du Traceur FFCO
  2023 » absent de `docs/` : ses distances par catégorie restent affichées à titre indicatif, avec
  la mention « source non vérifiée » (registre A3, V04), jusqu'à ce que le traceur fournisse le
  document.
- Relais, course de nuit, VTT, ski : hors plan.
