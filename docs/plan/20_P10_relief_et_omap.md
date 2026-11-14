# Phase 10 — Relief et fichiers OpenOrienteering Mapper

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

> Phase « lointaine » : objectif, interfaces, portes et critères. Avant de coder, écrire
> `docs/plan/P10_execution.md` (règles de travail §7).

## But

1. Donner au moteur le **relief** : dénivelé de chaque itinéraire, kilomètres-effort, règle des 4 %,
   puis éléments de relief (sommets, dépressions, rentrants, avancées) comme sites et comme lignes.
2. Lire les cartes **`.omap` / `.xmap`** d'OpenOrienteering Mapper, pour boucler la chaîne
   lidar-o → Mapper → AItraceur sans passer par OCAD.

## Ce que le traceur verra

- Pour chaque jambe et chaque circuit : dénivelé positif, longueur en kilomètres-effort,
  avertissement au-delà de 4 %.
- En forêt, des postes proposés sur des éléments de relief pour les niveaux jaune et au-delà ; des
  crêtes et des rentrants reconnus comme lignes directrices (Méthode fédérale T9).
- Le glisser-déposer d'un fichier `.omap` fonctionne comme celui d'un `.ocd`.

## Prérequis

Phase 5 terminée (itinéraires). Indépendante des phases 7, 8 et 9.

## Contexte vérifié (10 novembre 2026 — à relire au lancement)

- Le Guide des circuits de couleur compte les distances de forêt en kilomètres-effort : « 100 mètres
  de dénivelé positif = 1 kilomètre en terrain plat » (p. 4). Dénivelé : « ne doit pas excéder 4 %
  de la longueur totale du parcours par l'itinéraire le plus logique » (TP §3.11.6, p. 17).
- Méthode fédérale : relief « facile » dès le jaune (T9 : sommets, crêtes et rentrants bien
  marqués), relief comme poste à l'orange (« colline, dépression, avancée bien marquée ou
  falaise »), relief difficile au noir (T16).
- Aujourd'hui : `services/terrain/lidar_manager.py` interroge l'API d'altimétrie de l'IGN **en
  ligne** pour une grille de 30 × 30 points par carte (`build_elevation_cache`), soit un point tous
  les 30 à 100 m — insuffisant pour un itinéraire, et contraire à « tout en local ».
- IGN, MNT LiDAR HD : modèle numérique de terrain au pas de 50 cm, dalles de 1 km en GeoTIFF,
  Lambert-93, Licence Ouverte 2.0 ; la couverture progresse par départements. À revérifier au
  lancement (couverture de la zone du traceur, mode de téléchargement).
- lidar-o (même auteur) sait déjà : télécharger les dalles (`scripts/fetch.py`), calculer la
  convergence des méridiens (`src/init_terrain.py`, `compute_convergence` par `pyproj`), convertir
  mètres Lambert-93 ↔ unités `.omap` (millièmes de millimètre sur la carte, axe Y inversé :
  `src/omap_writer.py`, `_to_omap` et `_from_omap`), lire un géoréférencement (`load_georef`). Son
  gabarit `assets/ISOM 2017-2_10000.omap` contient les 191 symboles ISOM 2017-2.
- Enseignement de lidar-o (`docs/bilan_v0.md`) : le LiDAR ne prédit pas la végétation cartographiée
  de façon fiable. **La carte reste la vérité pour la végétation ; le LiDAR ne sert qu'au relief.**
- Le solveur de la phase 5 (`MCP_Geometric`) est isotrope : il ne distingue pas montée et descente.
- Dans un `.omap`, les codes de symbole peuvent avoir trois niveaux (`526.1.3`) : le registre ne
  retient que les deux premiers (A1 §1).

## Conception

### 1. Le modèle de terrain — `aitraceur/relief/dtm.py`

```python
@dataclass(frozen=True)
class Dtm:
    grid: Grid                 # même emprise que le terrain ; résolution propre (2 m par défaut)
    z_m: np.ndarray            # float32 ; NaN hors couverture
    source: str                # "lidar_hd" | "courbes" | "aucun"
    coverage: float            # part de la zone cartographiée couverte

def load_dtm(pkg: MapPackage, dtm_dir: Path, *, res_m: float = 2.0) -> Dtm: ...
```

- Les dalles sont **des fichiers locaux** : `{DATA_DIR}/dtm/` (téléchargées une fois, par l'outil de
  lidar-o ou à la main). `backend/tools/dtm_needed.py carte.json` liste les dalles nécessaires à une
  carte géoréférencée en Lambert-93.
- Lecture GeoTIFF : `rasterio` s'il s'installe sans compilateur sur le PC du traceur, sinon
  `tifffile` avec lecture des balises de géoréférencement. À décider par un essai d'installation,
  premier point de `P10_execution.md`.
- Ré-échantillonnage à 2 m par moyenne (le pas de 50 cm n'apporte rien à l'échelle d'un itinéraire).
- Carte non géoréférencée, ou zone non couverte : `source="aucun"` ; tout le reste de la phase se
  désactive proprement et l'interface le dit (« relief non disponible pour cette carte »).
- Repli possible plus tard : relief reconstruit à partir des courbes de niveau de la carte
  (interpolation). Non planifié : à n'ouvrir que si une carte importante du traceur est hors
  couverture.

### 2. Dénivelé et effort — `aitraceur/relief/slope.py`

```python
def climb_m(route: Route, dtm: Dtm, *, step_m: float = 10.0, min_step_m: float = 1.0) -> float:
    """Somme des montées le long de l'itinéraire, altitudes lissées sur 20 m ; une montée de moins
    de min_step_m entre deux points n'est pas comptée (bruit)."""
def effort_m(route_m: float, climb: float) -> float: return route_m + 10.0 * climb     # GC p. 4
```

- `RouteFacts` gagne `climb_m` ; `LegEntry.effort_m` devient réel ; les fourchettes de longueur
  (A2 §6) et la règle R08 (phase 7) s'appliquent enfin sur des valeurs vraies.
- **Itinéraires sensibles à la pente** — décision par la mesure, pas par principe :
  1. d'abord, garder les itinéraires de la phase 5 et leur ajouter le dénivelé après coup ;
  2. mesurer sur les cartes vallonnées du traceur combien de jambes changeraient d'itinéraire le
     plus rapide avec un coût dépendant de la pente (calcul de référence lent, en Python, sur 50
     jambes par carte) ;
  3. si plus de 15 % changent : écrire un solveur anisotrope (Dijkstra sur grille, compilé par
     `numba`, coût du pas selon la pente dans le sens de la marche — loi à choisir et à caler sur
     les traces de la phase 9). Sinon, en rester là.

### 3. Éléments de relief — `aitraceur/relief/landforms.py`

Principe : **le coureur lit la carte, pas le MNT**. Un élément de relief n'est un site que s'il est
**dessiné** : le MNT sert à comprendre les courbes, pas à inventer des formes que la carte ne
montre pas.

| Élément | Détection | Rôle |
|---------|-----------|------|
| Sommet, colline | courbe fermée (101, 102, 103) sans autre courbe à l'intérieur, dont le MNT dit que l'intérieur est plus haut | site `ponctuel`, évidence 3 (« sommet de colline » : jaune, MF p. 6) |
| Dépression | courbe fermée dont l'intérieur est plus bas (ou tiret de pente vers l'intérieur) | site, évidence 3 |
| Rentrant, avancée | sommet marqué d'une courbe (changement de direction ≥ 60° sur 30 m), le MNT donnant le sens de la pente : pointe vers l'amont = rentrant, vers l'aval = avancée | site, évidence 4 ; « bien marqué » si la forme se répète sur au moins trois courbes voisines → évidence 3 |
| Crête, fond de rentrant | suite de trois sommets de courbes alignés ou plus | ligne de classe `LR` (relief), utilisable comme ligne directrice à partir du jaune (MF T9) |
| Col | deux sommets voisins séparés par un point bas | site, évidence 4 |

Les sites de relief passent par les mêmes refus que les autres (phase 3) et les mêmes règles de
niveau (phase 4 : un paramètre `relief_sites` par couleur — interdit en vert et bleu, « facile » en
jaune, libre ensuite ; à ajouter à l'annexe A2 avec ses citations).

### 4. Lecture des `.omap` — `aitraceur/io/omap.py`

```python
def omap_to_map_package(path: Path) -> MapPackage: ...
```

- Lecture XML directe en Python (pas de JavaScript) : symboles (`code`, `name`, type), objets
  (coordonnées en millièmes de millimètre, Y vers le bas ; courbes de Bézier à discrétiser),
  géoréférencement (échelle, déclinaison, système projeté, point de référence).
- Conversion en mètres : reprendre, avec crédit, la logique de `lidar-o/src/omap_writer.py`
  (`_from_omap`, `load_georef`) ; carte au géoréférencement « Local » → paquet non géoréférencé.
- `code` du paquet = deux premiers niveaux du code OOM ; le reste de la chaîne (registre, terrain)
  est inchangé : c'est l'intérêt du paquet de carte.
- Envoi par l'interface : le fichier `.omap` part tel quel au serveur
  (`POST /api/v2/maps/omap`), qui construit le paquet. L'affichage du fond de carte suit le choix
  de la phase 11 (rendu dans le navigateur).

## Étapes (à détailler dans `P10_execution.md`)

1. Essai d'installation de la lecture GeoTIFF sur le PC du traceur ; `dtm_needed.py` ; chargement.
2. Dénivelé des itinéraires, kilomètres-effort, branchement dans le catalogue, les contraintes et
   R08 ; affichage.
3. Mesure « combien de jambes changeraient » ; décision sur le solveur anisotrope ; le cas échéant,
   solveur et tests.
4. Lecture `.omap` : d'abord le gabarit de lidar-o (191 symboles reconnus, norme détectée
   ISOM 2017-2), puis une vraie carte sortie de Mapper.
5. Éléments de relief : détection, tests sur reliefs synthétiques (cône, cuvette, vallon), revue
   avec le traceur sur une carte réelle.
6. Paramètres de niveau pour le relief ; mise à jour de l'annexe A2 ; calage avec le traceur.

## Portes de décision

| Porte | Condition | Sinon |
|-------|-----------|-------|
| Dénivelé | sur trois circuits réels dont le traceur connaît le dénivelé (logiciel de traçage ou montre), l'écart est inférieur à 15 % | revoir lissage et seuil de bruit avant d'afficher quoi que ce soit |
| Solveur anisotrope | plus de 15 % des jambes changent d'itinéraire le plus rapide sur au moins une carte du traceur | pas de solveur ; le dénivelé reste calculé après coup |
| Éléments de relief | sur une carte réelle, au moins 80 % des éléments détectés sont jugés justes par le traceur (50 éléments tirés au hasard), et au moins 80 % des postes de relief de ses anciens circuits sont retrouvés | les éléments de relief restent désactivés ; seuls dénivelé et effort sont livrés |
| `.omap` | une carte de Mapper et sa version OCAD (export) donnent la même lecture : même norme, mêmes surfaces interdites à 1 m² près pour mille, mêmes sites à 2 m près | corriger le lecteur avant de l'exposer |

## Critères d'acceptation

1. Sans dalle de MNT, rien ne casse : dénivelé « non disponible », moteur inchangé.
2. Avec dalles : dénivelé et kilomètres-effort affichés ; porte « dénivelé » franchie.
3. Aucune requête réseau (les dalles sont des fichiers) ; l'ancien appel en ligne à l'API
   d'altimétrie n'est plus utilisé par le moteur v2.
4. Lecture `.omap` : porte franchie ; `lidar-o` crédité dans `CREDITS.md`.
5. Chaque porte a son verdict au registre.

## Hors périmètre

- Produire ou modifier une carte : c'est le métier de lidar-o et de Mapper.
- Végétation, courabilité ou falaises déduites du LiDAR : la carte fait foi.
- Écriture de `.omap` (circuits dans un fichier Mapper) : à envisager avec les exports de la
  phase 11.

## Pièges

- Altitudes du MNT et courbes de la carte peuvent diverger (carte ancienne, équidistance
  interprétée) : en cas de désaccord sur une forme, la **carte** gagne et la forme n'est pas un site.
- Le dénivelé est très sensible au bruit : sans lissage ni seuil, un itinéraire « plat » accumule
  des dizaines de mètres fictifs.
- Convergence des méridiens et déclinaison : une carte tournée de quelques degrés décale le MNT de
  dizaines de mètres à un kilomètre du point de référence. Tester le recalage sur un point connu
  (sommet coté, bâtiment).
- Ne pas faire dépendre les phases 6 à 9 du relief : elles doivent rester justes, à plat, quand il
  n'y a pas de MNT.
