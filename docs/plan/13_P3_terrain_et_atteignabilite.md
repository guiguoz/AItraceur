# Phase 3 — Terrain et atteignabilité

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

## But

Transformer la carte lue (phase 2) en un **terrain** sur lequel on peut raisonner :

1. une grille qui dit, cellule par cellule, si l'on peut passer et à quelle vitesse ;
2. les **zones atteignables** depuis le départ, sans traverser ni interdit ni infranchissable ;
3. les **sites** : emplacements de poste réels, chacun avec le côté par lequel on y accède.

C'est cette phase qui corrige pour de bon le second bug d'origine : un bâtiment au fond d'un jardin
privé ne fournit plus aucun poste, un bâtiment sur la rue n'en fournit que sur ses coins côté rue.

## Ce que le traceur verra

- Trois calques sur la carte : interdit, infranchissable, inaccessible (franchissable mais enfermé).
- Les sites retenus (points) et les sites refusés (croix grises) avec le motif au survol :
  « interdit », « inaccessible », « bord de carte », « absent sur le terrain »…
- Une alerte quand l'accès à une zone dépend d'un passage trop étroit pour être garanti.
- Dans le moteur actuel (via le pont) : plus aucun poste en zone interdite ni inaccessible.

## Prérequis

- Phase 2 terminée (paquet de carte, registre, pont v1).
- Lire `02_VISION_ARCHITECTURE.md` §7 (mesures d'étanchéité) et `A1_symboles_reference.md` §3.

## Contexte vérifié

- Mesures du 10 et du 12 novembre 2026 (scripts repris en 3.2, résultats en annexe A3, E12 à E16) :
  - un **trait** tamponné de 0,75 × la résolution ne fuit jamais (0 sur 400) ; à 0,5 × il fuit
    399 fois sur 400 ;
  - deux **surfaces** qui se touchent par un coin fuient 224 fois sur 300 quand on ne marque que les
    cellules dont le centre est dans la surface ; la rastérisation **prudente** (ci-dessous) ne fuit
    jamais (0 sur 200, à 0,25 m, 0,5 m et 1 m) ;
  - en rastérisation prudente, un passage est toujours conservé à partir de 3,2 cellules de large
    (à 0,5 m : 1,6 m ouvert 200 fois sur 200 ; 1,2 m, 36 fois sur 200) ;
  - en rastérisation au centre, un passage d'une cellule de large reste ouvert en 8-connexité
    (300 sur 300 à 1 m pour une ruelle de 1 m), mais pas en 4-connexité.
- ISOM 2017-2 (`docs/ISOM2017_2_FR_EN  (mars2022).pdf`) : « L'espace minimum indiquant un passage
  entre deux bâtiments ou entre un bâtiment et un autre élément infranchissable devrait être de
  0,4 mm » (symbole 521, p. 70) ; même valeur pour les ouvertures dans une clôture ou un mur
  infranchissable, 0,25 mm pour les autres éléments linéaires (p. 21). Soit 4 m au 1:10 000 : deux
  cellules de 2 m, ce qui reste ouvert en politique « centre ». ISSprOM 2019 n'est pas dans
  `docs/` : **vérifier sa valeur** (attendue : 0,40 mm) dans la spécification avant de figer la
  règle de résolution en ville, et la consigner au registre.
- Le prototype (`aitraceur_proto/profiles.py`) fixait 2 m en ville : une ruelle de 1,6 m y est
  fermée deux fois sur trois. Ne rien en reprendre.
- `terrainAudit.js` (étape 14b) enregistre des observations de terrain par carte
  (`to_verify`, `ok`, `absent`, `inaccessible`), identifiées par `ocadObjectId`, exportables en JSON
  (`exportToJson` : `{_aitraceur_terrain_audit, fingerprint, exportedAt, observations}`).

## Étapes

### 3.1 — Grille et choix de la résolution

**Fichier** : `aitraceur/terrain/grid.py`.

```python
@dataclass(frozen=True)
class Grid:
    x0: float; y0: float            # coin nord-ouest, mètres
    res_m: float
    n_rows: int; n_cols: int
    def cell_of(self, x: float, y: float) -> tuple[int, int] | None: ...   # None hors grille
    def center_of(self, row: int, col: int) -> tuple[float, float]: ...
    def frac_rows_cols(self, xs, ys) -> tuple[np.ndarray, np.ndarray]:
        """Coordonnées fractionnaires pour skimage.draw : row = (y0 - y)/res - 0.5 ; col = (x - x0)/res - 0.5."""
    @classmethod
    def covering(cls, bbox, res_m: float, margin_m: float = 0.0) -> "Grid": ...

@dataclass(frozen=True)
class GridChoice:
    res_m: float
    policy: str              # "prudente" | "centre"
    min_passage_m: float     # largeur à partir de laquelle un passage est garanti ouvert
    reason: str              # phrase lisible, affichée dans le résumé de terrain

def choose_grid(standard: str, scale: int, bbox) -> GridChoice: ...
```

Règle de `choose_grid` (constantes dans `TerrainConfig`, `source` indiquée) :

| Norme | Politique | Résolution | Passage garanti |
|-------|-----------|------------|-----------------|
| `ISSPROM2019`, `ISSOM2007` | `prudente` | `0,40 mm × échelle ÷ 3,2`, arrondie par défaut au multiple de 0,125 m, bornée à [0,25 ; 0,5] | `3,2 × résolution` |
| `ISOM2017_2`, `ISOM2000` | `centre` | 2 m si l'échelle ≤ 1:10 000, 3 m au-delà | `1 × résolution` |

Soit 0,5 m au 1:4 000, 0,375 m au 1:3 000, 2 m au 1:10 000, 3 m au 1:15 000.
Pourquoi deux politiques : en ville, les contacts coin à coin entre bâtiments sont fréquents et une
fuite fabrique un itinéraire à travers un mur ; en forêt ils sont rares, alors que fermer le chemin
qui passe entre deux jardins rendrait tout un secteur inaccessible.

Garde-fou mémoire : si `n_rows × n_cols > 25 000 000`, multiplier la résolution par
`sqrt(cellules / 25 000 000)` (arrondi au 0,125 m supérieur) et ajouter un avertissement
« résolution dégradée : passages de moins de X m non garantis ».

**Tests** (`test_grid.py`) : `choose_grid("ISSPROM2019", 4000, …)` → `(0.5, "prudente", 1.6)` ;
échelle 3000 → `0.375` ; `("ISOM2017_2", 10000)` → `(2.0, "centre", 2.0)` ; échelle 15000 → `3.0` ;
aller-retour `center_of(cell_of(x, y))` à moins d'une demi-cellule ; `cell_of` hors grille → `None`.

### 3.2 — Rastérisation

**Fichier** : `aitraceur/terrain/rasterize.py`. Uniquement `numpy`, `shapely`, `skimage.draw`
(pas de GDAL : l'application doit s'installer sous Windows sans compilateur).

```python
def fill_polygons(grid: Grid, geom) -> np.ndarray:
    """Masque booléen : True pour toute cellule dont le CENTRE est dans geom (Polygon ou
    MultiPolygon). Les trous sont respectés : remplir l'anneau extérieur, puis vider chaque trou,
    polygone par polygone (masque temporaire), puis OU logique dans le résultat."""

def burn_lines(grid: Grid, lines, half_width_m: float) -> np.ndarray:
    """Tamponne chaque ligne (bouts plats, jointures en onglet) puis fill_polygons.
    Lève ValueError si half_width_m < 0.75 * grid.res_m : en dessous, le trait fuit."""

def burn_points(grid: Grid, points, radius_m: float) -> np.ndarray: ...

def block_areas(grid: Grid, geom, policy: str) -> np.ndarray:
    """policy == "centre"   : fill_polygons(geom)
       policy == "prudente" : fill_polygons(geom.buffer(0.7072 * res, join_style="mitre"))
    La version prudente bloque toute cellule que l'obstacle touche, même à peine."""
```

**Tests** (`test_rasterize.py`) — ils rejouent, en petit et sans hasard, les mesures du contexte :

- carré (10,10)–(20,20) sur une grille de 30 m à 1 m → 100 cellules ; avec un trou (13,13)–(17,17)
  → 84 ;
- **trait étanche** : pour chaque angle de 0, 10, 30, 45, 60, 80 degrés, un trait traversant une
  grille de 60 m à 1 m, `half_width_m=0.75` : deux points témoins de part et d'autre sont dans des
  composantes 8-connexes différentes de la zone libre ;
- `burn_lines(…, half_width_m=0.5)` sur une grille à 1 m lève `ValueError` ;
- **coin à coin, prudente** : deux carrés de 25 m qui se touchent par un sommet, tournés de 0, 20 et
  45 degrés, résolution 0,5 m : les deux quadrants libres ne communiquent pas dans un disque de 12 m
  autour du contact ;
- **ruelle, prudente** : deux rectangles parallèles séparés de 1,6 m, tournés de 0, 15, 45 et 75
  degrés, résolution 0,5 m : la ruelle relie ses deux extrémités en 8-connexité ;
- **ruelle, centre** : séparation de 2 m, résolution 2 m, mêmes angles : ouverte en 8-connexité.

### 3.3 — Zone cartographiée

**Fichier** : `aitraceur/terrain/layers.py`, fonction `mapped_area(grid, pkg, radius_m)`.

Le blanc d'une carte n'est pas forcément « hors carte » : en norme 2017, la forêt est souvent
l'absence d'objet. La zone cartographiée est donc définie par le voisinage des objets :

1. sur une grille grossière (10 m), marquer toute cellule touchée par un objet de la carte
   (surfaces remplies, lignes et points tamponnés d'une cellule) ;
2. fermeture morphologique par un disque de rayon `radius_m` (30 m en ville, 100 m en forêt), après
   avoir bordé le tableau de `radius_m` pour éviter l'effet de bord ; puis `binary_fill_holes` ;
3. ramener à la résolution de la grille (répétition des cellules).

Le traceur peut la remplacer par une **zone de course** dessinée à la main
(`PUT /api/v2/maps/{map_id}/course-area`, un polygone) : c'est elle qui fait foi quand elle existe.

**Tests** : sur `bois()`, toute la carte est cartographiée ; un paquet fait de deux pavés d'objets
distants de 500 m donne deux zones disjointes ; une zone de course fournie remplace le calcul.

### 3.4 — Les calques de terrain

**Fichier** : `aitraceur/terrain/layers.py`.

```python
@dataclass(frozen=True)
class TerrainConfig:
    point_obstacle_radius_m: float = 0.5        # pilier, bâtiment de taille minimale    source="implementation"
    opening_half_width_m: float = 1.0           # pont, tunnel
    opening_point_radius_m: float = 1.5         # point de passage
    default_speed: SpeedClass = SpeedClass.V2   # blanc de la carte = forêt (ISOM 2017-2, symbole 405)
    mapped_radius_m: Mapping[str, float] = ...  # {"prudente": 30.0, "centre": 100.0}

@dataclass(frozen=True)
class Terrain:
    grid: Grid
    choice: GridChoice
    mapped: np.ndarray            # bool
    forbidden: np.ndarray         # bool — interdit par la règle
    impassable: np.ndarray        # bool — infranchissable physiquement
    passable: np.ndarray          # bool = mapped & ~forbidden & ~impassable
    speed_class: np.ndarray       # uint8 : 0 = non franchissable, 1..5 = V1..V5
    cross_penalty_s: np.ndarray   # float32 : secondes perdues en franchissant la cellule (lignes « lent »)
    forbidden_geom: "shapely.MultiPolygon"     # vecteur exact, pour l'affichage et les tests de point
    impassable_geom: "shapely.MultiPolygon"
    flagged_geom: Mapping[str, "shapely.MultiPolygon"]   # "multi_niveaux", "saisonnier", "voie_ferree", "circulation"
    warnings: tuple[str, ...]

def build_terrain(pkg: MapPackage, reading: MapReading, *, choice: GridChoice | None = None,
                  course_area=None, config: TerrainConfig = TerrainConfig()) -> Terrain: ...
```

Ordre de construction (déterministe ; chaque couche écrase ou complète la précédente) :

| # | Couche | Règle |
|---|--------|-------|
| 1 | `mapped` | 3.3. |
| 2 | Vitesse des surfaces de végétation, de sol et d'eau | Partir de `default_speed` ; pour chaque surface ayant une vitesse, garder la classe **la plus lente** des surfaces superposées. |
| 3 | Vitesse des zones pavées et auvents | Surfaces de famille `chemin` ou `batiment` franchissable : forcer V1. |
| 4 | Vitesse des chemins | Lignes de famille `chemin` ayant une vitesse : tampon de `max(largeur_trait_mm × échelle ÷ 2000, 0,75 × rés)` ; classe = la plus **rapide** entre l'existant et celle du chemin. |
| 5 | `impassable` | Surfaces `infranchissable` par `block_areas(policy)` ; lignes par `burn_lines(max(demi-largeur du trait au sol, 0,75 × rés))` ; points par `burn_points(point_obstacle_radius_m)`. |
| 6 | `forbidden` | Mêmes règles pour `interdit` (surfaces, lignes 708 et 711, zones 709 et 714). |
| 7 | Drapeaux en attente | `voie_ferree` et `circulation` non tranchés par le traceur : ajoutés à `impassable` (A1 §3.3) ; `saisonnier` : libre, mais consigné dans `flagged_geom` et `warnings`. |
| 8 | Ouvertures | Objets `ouvre` : lignes tamponnées de `max(opening_half_width_m, 1,5 × rés)` et prolongées de `2 × rés` à chaque bout ; points en disque de `max(opening_point_radius_m, 2,5 × rés)`. Ces cellules sont **retirées** d'`impassable` et des **lignes** interdites, jamais des surfaces interdites ; elles reçoivent la vitesse V1. |
| 9 | `passable`, `speed_class` | `passable = mapped & ~impassable & ~forbidden` ; `speed_class = 0` hors `passable`. |
| 10 | `cross_penalty_s` | Lignes `lent` : tampon de `0,75 × rés`, valeur = `cross_penalty_s` du symbole (le maximum si plusieurs). |

`forbidden_geom` et `impassable_geom` sont les unions **vectorielles** exactes (sans tampon de
prudence) : c'est contre elles que le banc compte `forbidden_hits`.

Symboles à confirmer : si des objets de la zone cartographiée ont un symbole de statut `inconnu` ou
`conflit`, `build_terrain` lève `UnresolvedSymbols` (liste des symboles) sauf si
`allow_unresolved=True` ; dans ce cas ils sont sans effet et listés dans `warnings`. Le moteur ne
devine pas (`02_VISION_ARCHITECTURE.md` §2, principe 1).

**Tests** (`test_layers.py`) sur `village()` (ISSprOM 2019, grille 0,5 m prudente) :

| Point (x, y) | Attendu |
|--------------|---------|
| (20, 120) dans OLIVE_NO | `forbidden`, pas `impassable` |
| (10, 75) dans FERME | `forbidden` |
| (45, 120) dans B1 (lui-même dans l'olive) | `impassable` et `forbidden` |
| (150, 110) dans B2 | `impassable` |
| (100, 75) carrefour des rues | `passable`, V1 |
| (100, 104) sous AUVENT | `passable`, V1 |
| (100, 106) PILIER | `impassable` |
| (45, 30) PARC_O | `passable`, V1 |
| (160, 30) dans ENCLOS | `passable` (mais pas atteignable, voir 3.5) |
| (125, 30) sur CLOTURE | `passable`, `cross_penalty_s` = pénalité de la clôture franchissable |
| (20, 60) sur MUR_1 | `impassable` |
| (45, 60) dans la brèche (`gap_m=1.5`) | `passable` |

Les deux normes de `village()` donnent des calques identiques cellule pour cellule. Sur `bois()`
(grille 2 m, centre) : (490, 100) dans LAC `impassable` ; (300, 200) V1 ; (150, 300) V3 ; (150, 100)
V4 ; (20, 390) V2.

### 3.5 — Atteignabilité

**Fichier** : `aitraceur/terrain/reach.py`.

```python
@dataclass(frozen=True)
class Reachability:
    labels: np.ndarray            # int32 ; 0 = non franchissable
    main_label: int
    n_components: int
    area_m2: Mapping[int, float]
    narrow_access: tuple[tuple[float, float], ...]   # centres des zones dont l'accès dépend d'un passage étroit

def compute_reachability(terrain: Terrain, start_xy: tuple[float, float] | None = None) -> Reachability: ...
```

- Composantes par `scipy.ndimage.label(terrain.passable, structure=np.ones((3, 3)))` (8-connexité).
- Composante principale : celle du départ s'il est donné (cellule franchissable la plus proche à
  moins de 10 m, sinon `ValueError("départ en zone non franchissable")`), sinon la plus grande.
- `narrow_access` (politique prudente seulement) : refaire le calcul avec les surfaces en politique
  `centre` ; toute composante atteignable « au centre » mais pas « en prudente » et de plus de
  200 m² est signalée par son centre. C'est l'alerte « passage étroit » du traceur.

**Tests** (`test_reach.py`) sur `village()` :
- `gap_m=1.5` : (100, 75), (45, 30) et (125, 48) sont dans la composante principale ; (160, 30) n'y
  est pas ;
- `gap_m=0` : (45, 30) n'y est plus (PARC_O est muré) ;
- départ donné en (160, 30) : la composante principale devient l'enclos, de moins de 1 200 m² ;
- `gap_m=1.0` : PARC_O reste atteignable — la brèche d'un **trait** n'est pas rétrécie par la
  prudence (bouts plats), seule l'est la distance entre deux **surfaces**.

Passage étroit — carte construite dans le test (`cour()`, ISSprOM 2019, 1:4000) : quatre bâtiments
rectangulaires entourant une cour de 20 m × 20 m, avec une seule ruelle de 1,0 m entre deux d'entre
eux. À 0,5 m en prudente la cour n'est pas dans la composante principale et `narrow_access`
contient un point de la cour ; avec une ruelle de 2,0 m, elle y est et `narrow_access` est vide.

### 3.6 — Les sites

**Fichiers** : `aitraceur/sites/model.py`, `aitraceur/sites/extract.py`.

```python
@dataclass(frozen=True)
class Site:
    id: str                          # stable : "<sym_num>:<object_index>:<rang>"
    xy: tuple[float, float]          # l'élément (centre du cercle de poste)
    stand_xy: tuple[float, float] | None   # où se tient le coureur ; extrémité des itinéraires
    kind: str                        # "jonction" | "croisement" | "coude" | "extremite" | "coin" | "ponctuel" | "petite_surface"
    family: str
    label_fr: str                    # "coin de bâtiment", "jonction de chemins", "chemin × ruisseau", "rocher"…
    obviousness: int                 # 1..4 après correction de contexte
    n_similar: int                   # autres sites de même label_fr à moins de 30 m (ville) ou 60 m (forêt)
    line_classes: tuple[str, ...]    # classes des lignes qui se rencontrent au site (vide pour un ponctuel)
    sym_num: int; object_index: int | None
    access_bearing_deg: float | None # direction élément → coureur
    rejected: str | None             # None = site valable

REJECT_REASONS = ("interdit", "inaccessible", "hors_zone", "bord_de_carte", "multi_niveaux",
                  "terrain_absent", "terrain_inaccessible", "symbole_a_confirmer")

def extract_sites(pkg, reading, terrain, reach, *, observations=(), config=SiteConfig()) -> list[Site]: ...
```

**Candidats**, selon le rôle de site du symbole (A1) :

| Rôle | Candidats |
|------|-----------|
| `ponctuel` | le point de l'objet. |
| `petite_surface` | plus grande dimension ≤ 10 m (ville) ou 30 m (forêt) : un site au point représentatif de la surface ; au-delà : ses coins, comme `coin`. |
| `coin` | sommets d'angle ≥ 60° dont les deux côtés font ≥ 3 m (ville) ou 10 m (forêt), après simplification (0,5 m ; 2 m) ; plus les extrémités libres pour une ligne. |
| `extremite` | les deux extrémités de la ligne. |
| `jonction` | réseau des lignes de ce rôle, **découpé aux intersections** (`shapely.unary_union`), extrémités à moins de `0,3 mm × échelle` regroupées (OCAD ne raccorde pas toujours les chemins) : nœud à trois branches ou plus → `jonction` (`croisement` à quatre) ; nœud à une branche → `extremite` ; changement de direction ≥ 45° mesuré sur 10 m de part et d'autre → `coude`. |
| croisements entre familles | intersection d'un chemin L1 avec une autre ligne à rôle de site (cours d'eau, clôture, mur, limite de végétation) → `croisement`, libellé « chemin × ruisseau »… |

**Évidence** : valeur de la table A1, puis règles géométriques de A1 §3.2 — jonction de deux lignes
L1 : 1 ; jonction L1 × L2, coude ou extrémité de L1 : 2 ; coude, extrémité ou jonction de L2 ou L3 :
3 ; puis +1 (plafond 4) si `n_similar >= 2`, c'est-à-dire si au moins trois sites de même
`label_fr` (lui compris) se trouvent dans un rayon de 30 m (ville) ou 60 m (forêt).

**Où se tient le coureur** (`stand_xy`) :

1. si la cellule du site est franchissable : `stand_xy = xy` ;
2. sinon, la cellule franchissable la plus proche dans un rayon de `max(1,5 m ; 2,5 × rés)` en ville,
   `max(4 m ; 2 × rés)` en forêt, telle que le segment qui la relie au site ne traverse aucune
   cellule bloquée à plus d'une cellule du site (échantillonnage tous les `rés ÷ 2`) ; à distance
   égale ou non, une cellule de la **composante principale** passe toujours avant une cellule d'une
   autre composante (un coin de clôture d'enclos se prend de l'extérieur) ;
3. aucun candidat : `stand_xy = None`.

**Refus**, dans cet ordre (le premier motif qui s'applique) :

| Motif | Condition |
|-------|-----------|
| `symbole_a_confirmer` | symbole de statut `inconnu` ou `conflit`. |
| `terrain_absent`, `terrain_inaccessible` | observation de terrain `absent` ou `inaccessible` sur l'objet (3.7). |
| `hors_zone` | hors de `mapped`. |
| `bord_de_carte` | à moins de 5 m (ville) ou 15 m (forêt) du bord de la zone cartographiée. |
| `interdit` | `xy` strictement à l'intérieur de `forbidden_geom`, ou `stand_xy` introuvable et `xy` à moins de 0,5 m d'un interdit. |
| `multi_niveaux` | `xy` dans une surface portant ce drapeau. |
| `inaccessible` | `stand_xy` introuvable, ou cellule de `stand_xy` hors de la composante principale. |

Enfin, fusionner les sites valables à moins de 2 m (ville) ou 8 m (forêt) : garder le plus évident,
puis le plus petit `id`. Trier la sortie par `id`.

**Tests** (`test_sites.py`) — on teste la présence ou l'absence de sites **nommés**, pas un total :

Sur `village(gap_m=1.5)` :

| Site | Attendu |
|------|---------|
| FONTAINE_O (40, 30) | valable, `ponctuel` |
| ARBRE (125, 48) | valable |
| coins sud de B2 : (130, 90), (170, 90) | valables, `coin`, évidence 1, `stand_xy` au sud (y < 90), `access_bearing_deg` vers le sud à ±45° |
| coins nord de B2 : (130, 125), (170, 125) | refusés `interdit` |
| quatre coins de B1 | refusés `interdit` |
| FONTAINE_ENCLOS (160, 30) | refusé `inaccessible` |
| quatre coins d'ENCLOS | valables, `stand_xy` à l'extérieur de l'enclos |
| coins d'AUVENT | valables |
| brèche du mur | un site `extremite` valable à moins de 1 m de (45, 60) (les deux extrémités, distantes de 1,5 m, sont fusionnées) |
| PILIER | aucun site (pas de rôle de site) |

Avec `gap_m=0` : FONTAINE_O devient `inaccessible`. Les deux normes donnent les mêmes sites.

Sur `bois()` : jonction (300, 200) valable, `croisement`, évidence 1 ; extrémités des chemins au bord
de la carte refusées `bord_de_carte` ; quatre éléments ponctuels valables, évidence 4 ; quatre coins
de CLAIRIERE valables, évidence 2 ; coins de LAC valables avec `stand_xy` hors du lac ; aucun site
pour LENT, MARCHE ni FORET.

### 3.7 — Observations de terrain

Les observations de l'étape 14b deviennent des entrées du moteur.

- `PUT /api/v2/maps/{map_id}/observations` : corps = le JSON d'`exportToJson`. Refus (409) si
  `fingerprint` ≠ `map_id`. Stockage : `{DATA_DIR}/maps/{map_id}/observations.json`.
- `TerrainAuditPanel.jsx` : après chaque ajout, modification ou suppression, envoyer la liste
  (le `localStorage` reste la copie de travail hors ligne).
- `extract_sites` : un objet dont `object_index` égale l'`ocadObjectId` d'une observation `absent`
  ou `inaccessible` voit tous ses sites refusés avec le motif correspondant.

**Tests** : une observation `absent` sur FONTAINE_O la fait passer en `terrain_absent` ; une
observation `ok` ne change rien ; empreinte différente → 409.

### 3.8 — API et interface

**Fichiers** : `backend/src/api/v2/terrain.py`, `frontend/src/components/v2/TerrainLayersPanel.jsx`.

| Route | Rôle |
|-------|------|
| `GET /api/v2/maps/{map_id}/terrain` | Résumé : résolution, politique, phrase de `GridChoice.reason`, taille de grille, surfaces en m² (franchissable, interdit, infranchissable, inaccessible), nombre de composantes, avertissements, `narrow_access`. |
| `GET /api/v2/maps/{map_id}/terrain/layers/{layer}` | GeoJSON WGS84 de `forbidden`, `impassable`, `inaccessible`, `mapped`, `flagged`. Les deux premiers viennent des géométries vectorielles ; `inaccessible` et `mapped` sont vectorisés depuis la grille (`skimage.measure.find_contours`, simplification d'une cellule). |
| `GET /api/v2/maps/{map_id}/sites?rejected=1` | Les sites, en mètres et en WGS84, avec motif de refus. |
| `PUT /api/v2/maps/{map_id}/course-area` | Zone de course dessinée (3.3). |
| `PUT /api/v2/maps/{map_id}/flags/{flag}` | Décision du traceur sur `saisonnier`, `voie_ferree`, `circulation` : `"libre"` ou `"interdit"`. |

Cache : `{DATA_DIR}/maps/{map_id}/terrain_<clé>.npz`, la clé étant l'empreinte (SHA-256, 16
caractères) de : norme retenue, corrections de symboles, zone de course, décisions de drapeaux,
observations, `TerrainConfig`, version du module. Aucun calcul au second appel.

Interface : trois cases à cocher (interdit, infranchissable, inaccessible), une quatrième pour les
sites ; sites refusés en croix grises avec info-bulle ; bandeau « 2 zones accessibles seulement par
un passage étroit — voir sur la carte » qui centre la vue ; boutons de décision pour les drapeaux.

**Tests** : client HTTP sur `village()` — `layers/forbidden` contient trois polygones (deux olives,
zone fermée) ; `sites?rejected=1` contient B1 avec `rejected: "interdit"` ; second appel servi par
le cache (un compteur d'appels à `build_terrain` reste à 1).

### 3.9 — Pont v1 : sites réels et projection des sorties

**Fichier** : `backend/src/api/v2/v1_bridge.py`.

1. `candidate_points` = les sites valables, à la position **`stand_xy`** (le moteur v1 teste des
   points contre des polygones : un coin de bâtiment posé exactement sur une limite d'olive y serait
   ambigu). La « version simple » de la phase 2 est supprimée.
2. `forbidden_zones_polygons` = `forbidden_geom` ∪ `impassable_geom` hors bâtiments ∪ zones
   inaccessibles.
3. **Projection des sorties** : dans `_circuit_impl` et `_sprint_impl`, quand
   `zones_source == "registry"`, chaque poste rendu par le moteur v1 est ramené sur le site valable
   le plus proche à moins de 30 m (ville) ou 80 m (forêt) ; sinon il est retiré et compté. La réponse
   gagne `n_projected` et `n_removed`. (Le moteur v1 déplace ses postes par mutation : sans cette
   étape, rien ne garantit qu'ils restent sur des sites.)

**Tests** (`test_v1_bridge.py`, mis à jour) : les coins nord de B2 ne sont plus candidats ; aucun
candidat dans l'enclos ; un poste rendu en (45, 120) (olive) est projeté ou retiré, jamais conservé.

### 3.10 — Mesure sur les cartes réelles

1. Pour chaque carte d'essai, `backend/tools/terrain_report.py carte.json` imprime et ajoute à
   `docs/plan/mesures/P3_cartes.md` :

   | Carte | Résolution | Grille | Temps de construction | Composantes | Sites valables | Refusés (par motif) | Passages étroits |
   |-------|------------|--------|-----------------------|-------------|----------------|---------------------|------------------|

2. Avec le traceur, sur deux cartes de sprint et une de forêt : parcourir les sites refusés
   (croix grises) et les zones inaccessibles. Pour chacun : refus justifié ou non. Tout refus
   injustifié devient un test (carte réduite à la zone, sans le reste) avant d'être corrigé.
3. Rejouer le banc avec le pont : `forbidden_hits` et un nouvel indicateur `unreachable_hits`
   (postes hors de la composante principale) — c'est **K1**. Écrire `docs/plan/mesures/P3_apres.md`.

## Critères d'acceptation

1. Tous les tests de 3.1 à 3.9 passent.
2. K1 = 0 sur toutes les cartes réelles, toutes graines confondues, moteur v1 alimenté par le pont.
3. Sur les deux cartes de sprint revues, le traceur ne trouve aucun site valable situé en propriété
   privée ni sur un bâtiment enclavé ; les refus injustifiés sont corrigés et couverts par un test.
4. Construction du terrain d'une carte de sprint de 1 km² : moins de 30 s sur le PC du traceur ;
   moins de 1 s au second appel (cache).
5. La valeur du passage minimal ISSprOM 2019 est vérifiée dans la spécification et consignée.

## Hors périmètre

- Vitesses chiffrées, temps, itinéraires (phase 5).
- Niveaux (phase 4) : ici un site n'a qu'une évidence, pas encore de niveau.
- Structures à plusieurs niveaux : détectées et exclues, pas modélisées.
- Éléments de relief tirés des courbes ou du MNT (phase 10).

## Pièges

- `skimage.draw.polygon` prend `(lignes, colonnes)` : utiliser `Grid.frac_rows_cols`, jamais `(x, y)`.
- Un polygone à trous rempli en une seule passe « anneau extérieur puis trous » est juste ; plusieurs
  polygones traités ensemble ne le sont pas (une île dans un trou serait vidée). Un masque
  temporaire par polygone.
- `shapely.buffer` sur l'union de milliers de bâtiments : faire l'union d'abord
  (`shapely.unary_union`), tamponner ensuite, une seule fois.
- Les ouvertures ne percent jamais une surface interdite : un pont dessiné au-dessus d'une olive ne
  la rend pas traversable.
- Un chemin dessiné **sur** une surface interdite continue (olive non interrompue sous la route) est
  ambigu : la norme demande d'interrompre la zone. Par défaut le passage reste interdit ; l'ajouter
  aux avertissements (« chemin traversant une zone interdite sans interruption »), le traceur
  tranche par une zone de course ou une correction de symbole.
- Ne pas confondre `xy` (où est l'élément) et `stand_xy` (où passe le coureur) : les distances entre
  postes se mesurent sur `xy`, les itinéraires partent de `stand_xy`.
