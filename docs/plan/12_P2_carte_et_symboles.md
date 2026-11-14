# Phase 2 — Carte et symboles

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

## But

Faire que l'application **lise la carte juste**, quelle que soit sa norme, et le montre :

1. un format neutre, le *paquet de carte*, qui porte les symboles et les objets en mètres ;
2. un *registre de symboles* unique : norme détectée, rôle de chaque symbole, corrections du traceur ;
3. un *pont* qui alimente le moteur v1 avec des entrées justes, en remplacement des tables fausses.

C'est la phase la plus importante du plan : tout le reste repose dessus.

## Ce que le traceur verra

- À l'import d'une carte : « Norme reconnue : ISSOM 2007 (confiance 0,84) », modifiable.
- Un onglet « Lecture de la carte » : pour chaque symbole, ce que l'application en a compris
  (interdit, bâtiment, chemin net, végétation lente…), avec une pastille (norme / hérité / à
  confirmer / inconnu / corrigé) et une liste déroulante pour corriger.
- Plus aucun poste proposé dans une zone interdite, sur toutes ses cartes de sprint.

## Prérequis

- Phases 0 et 1 terminées.
- Lire `A1_symboles_reference.md` en entier.

## Contexte vérifié

- `OcadUploader.jsx` calcule déjà `rawObjectsGeojson = ocadToGeoJson(ocadMap, { generateSymbolElements: false })`
  (objets seuls, **coordonnées projetées en mètres** : `applyCrs` vaut `true` par défaut), le
  SHA-256 du fichier (`fileHash`), `crs` (`getCrs()` : `easting`, `northing`, `scale`, `grivation`
  en radians, `code` EPSG ou 0).
- `ocad2geojson` : `properties.sym` = numéro brut (`majeur × 1000 + mineur`), `properties.objectIndex`,
  courbes de Bézier déjà discrétisées, symboles masqués exclus par défaut (`exportHidden: false`).
- `ocadInventory.js` construit l'inventaire par `symNum` et expose `OCAD_PARSER_VERSION`.
- Le dépôt `OpenOrienteering/mapper` (GPL-3.0, compatible AGPL-3.0) contient les jeux de symboles
  des quatre normes dans `symbol sets/src/*.xmap` et des tables de correspondance entre normes
  (`symbol sets/*.crt`, une ligne = « nouveau code, ancien code »). Comptes vérifiés : ISOM 2017-2,
  191 symboles ; ISSprOM 2019, 185 ; ISSOM (2007), 169 ; ISOM 2000, 157.
- **Les sous-numéros ne sont pas fiables** d'un jeu de symboles à l'autre (OCAD écrit `521.001`,
  OpenOrienteering `521.1` ou `526.1.3`, les clubs ajoutent les leurs). Le sens se décide au
  **numéro principal + type d'objet** ; sous-numéro, nom et largeur de trait ne servent qu'à affiner.

## Étapes

### 2.1 — Tables de référence des quatre normes

**Fichiers** : `backend/tools/build_symbol_refs.py` ; sorties dans
`backend/src/aitraceur/symbols/standards/`.

Le script lit un dossier local contenant les fichiers d'OpenOrienteering Mapper (à télécharger une
fois à la main depuis le dépôt `OpenOrienteering/mapper`, dossier `symbol sets/`) :

| Entrée | Sortie |
|--------|--------|
| `src/ISOM 2017-2_15000.xmap` | `isom2017_2.json` |
| `src/ISSprOM 2019_4000.xmap` | `issprom2019.json` |
| `src/ISOM2000_15000.xmap` | `isom2000.json` |
| `src/ISSOM_5000.xmap` | `issom2007.json` |
| `ISOM2000-ISOM 2017-2.crt` | `crossref_isom2000.json` (ancien code → nouveau code) |
| `ISSOM-ISSprOM 2019.crt` | `crossref_issom2007.json` |

Format d'une table : `{"standard": "...", "source": "...", "symbols": [{"code": "521", "kind": "A", "name_en": "Building"}, …]}`.
`kind` vient de l'attribut `type` du symbole OOM : 1 → `P`, 2 → `L`, 4 → `A`, 8 → `T`, 16 → `C`
(combiné : compte pour `A` et `L`). Retirer les balises HTML des noms (présentes dans le jeu ISSOM).
Écrire `standards/CREDITS.md` (origine, licence GPL-3.0, date de téléchargement, commit OOM), sur le
modèle de `lidar-o/assets/CREDITS.md`.

**Tests** (`backend/tests/aitraceur/test_symbol_refs.py`) :
- nombres de symboles : 191, 185, 157, 169 ;
- `isom2017_2` : `521` est `A` « Building », `520` est `A`, `109` est `P` « Small knoll » ;
- `issprom2019` : `410` est `A` « Impassable vegetation », `501.1` est `L` ;
- `isom2000` : `526` est `A` « Building », `521` est `L` « High stone wall », `528` est `A` ;
- `issom2007` : `528.1` est `A`, `526.1` est `C`, `421` est `A` ;
- `crossref_isom2000["526"] == "521"`, `crossref_issom2007["528.1"] == "520"`.

### 2.2 — Rôles des symboles

**Fichiers** : `aitraceur/symbols/roles.py`, `aitraceur/symbols/semantics/{isom2017_2,issprom2019,isom2000,issom2007}.json`.

```python
class Passability(str, Enum):
    FREE = "libre"                  # sans effet sur le déplacement
    SLOW = "lent"                   # franchissable avec une pénalité de temps
    IMPASSABLE = "infranchissable"  # mur, clôture, falaise, eau, bâtiment…
    FORBIDDEN = "interdit"          # interdit par la règle : olive, hors limites
    OPENING = "ouvre"               # rouvre un passage : pont, tunnel, point de passage

class SpeedClass(str, Enum):        # classes de la norme ISOM 2017-2 (tableau des vitesses)
    V1 = "V1"   # > 100 %   pelouse, zone pavée, chemin
    V2 = "V2"   # 80–100 %  forêt ouverte, terrain découvert encombré
    V3 = "V3"   # 60–80 %   course ralentie
    V4 = "V4"   # 20–60 %   marche
    V5 = "V5"   # < 20 %    progression difficile

class LineClass(str, Enum):         # « types de lignes » de la FFCO (Traçage – Aspects pratiques, p. 8 et 10 ; annexe A1 §3.1)
    L1 = "L1"   # route, chemin, sentier, clôture, mur, rivière, ligne électrique, voie ferrée, bâtiment
    L2 = "L2"   # sentier peu visible, talus, fossé net, ruisseau, lisière, haie, layon, levée de terre, tour de lac
    L3 = "L3"   # limite de végétation ou de culture, fossé intermittent, mur ou clôture en ruine

@dataclass(frozen=True)
class SymbolSemantics:
    family: str                     # "batiment", "interdit", "chemin", "vegetation", "eau", "relief", "roche", "ouvrage", "mise_en_page", "parcours"
    passability: Passability = Passability.FREE
    speed: SpeedClass | None = None         # surfaces et emprises de chemins
    cross_penalty_s: float = 0.0            # pour SLOW (valeur initiale, à caler en phase 9)
    line: LineClass | None = None
    site: str | None = None                 # rôle de site : "coin", "jonction", "ponctuel", "petite_surface", "extremite", None
    obviousness: int | None = None          # 1 évident … 4 difficile (annexe A1 §3.2)
    label_fr: str = ""
    flags: frozenset[str] = frozenset()     # "ouvert", "saisonnier", "voie_ferree", "circulation", "multi_niveaux", "directionnel", "danger", "courbe" (annexe A1 §3.3)
    source: str = ""                        # "ISOM 2017-2 §…" ou "implementation"
```

Les fichiers `semantics/*.json` se remplissent à partir de l'annexe A1 : §2 pour ISOM 2017-2 et
ISSprOM 2019 ; pour ISOM 2000 et ISSOM 2007, **générer** la table par
`ancien code → crossref → sémantique du nouveau code`, puis appliquer les exceptions de l'annexe A1 §4.
Clé d'une entrée : `"<numéro principal>/<type>"` (ex. `"521/A"`), avec des entrées plus précises
facultatives `"<code complet>/<type>"` (ex. `"410.1/L"`).

**Tests** (`test_symbol_semantics.py`) :
- chaque entrée d'une table de sémantique désigne un `(numéro principal, type)` qui existe dans la
  table de référence de la même norme ;
- chaque symbole de type `P`, `L`, `A`, `C` des codes 101 à 599 de chaque norme a une sémantique
  (aucun trou) ;
- contrôles ciblés : ISSprOM `520/A` interdit ; ISSprOM `410/A` infranchissable ; ISOM 2017-2
  `410/A` franchissable `V5` ; ISOM 2017-2 `406/A` et `407/A` franchissables `V3` ; ISSOM `528/A`
  interdit ; ISSOM `526/A` famille `batiment` infranchissable ; ISOM 2000 `527/A` et `528/A`
  interdits ; ISOM 2017-2 `412/A` **non** interdit (drapeau `saisonnier`).

### 2.3 — Le paquet de carte

#### 2.3.0 Sonde (à faire en premier)

Écrire `frontend/scripts/probe_ocd.mjs <fichier.ocd>` : lit le fichier avec `ocad2geojson`, affiche
les clés réellement présentes sur une définition de symbole de chaque type (point, ligne, surface,
texte), sur les `properties` d'un objet, sur `getCrs()` et sur `ocadFile.colors[0]`. L'exécuter sur
deux cartes du traceur (une de sprint, une de forêt) et consigner la sortie dans
`docs/plan/mesures/P2_sonde_ocad.md`. Les noms de champs ci-dessous sont ceux attendus ; **la sonde
fait foi** et le schéma s'y adapte avant d'aller plus loin.

#### 2.3.1 Schéma `aitraceur.mappackage/1`

```jsonc
{
  "schema": "aitraceur.mappackage/1",
  "source": { "format": "ocd", "file_name": "caen_centre.ocd", "sha256": "<64 hex>",
              "parser": "ocad2geojson@2.1.20", "ocad_version": 12 },
  "georef": { "georeferenced": true,       // crs.code != 0
              "epsg": 2154,                // ou null
              "scale": 4000,
              "easting": 453210.0, "northing": 6903410.0,
              "grivation_deg": 0.75 },
  "bbox": [xmin, ymin, xmax, ymax],        // mètres
  "symbols": [
    { "sym_num": 521000, "code": "521.0", "major": 521, "minor": 0,
      "name": "Bâtiment", "sym_type": 3,             // type de la définition OCAD si présent
      "kinds": ["A"],                                // types de géométrie réellement observés
      "line_width_mm": null,                         // symboles de ligne : largeur du trait principal
      "n_objects": 412 }
  ],
  "objects": [
    { "i": 0, "oi": 17, "s": 521000, "k": "A", "c": [[[x, y], …], …] },   // surface : anneaux
    { "i": 1, "oi": 18, "s": 515000, "k": "L", "c": [[x, y], …] },
    { "i": 2, "oi": 19, "s": 311000, "k": "P", "c": [x, y] }
  ]
}
```

Règles : coordonnées arrondies au centimètre ; objets de texte exclus ; objets sans symbole connu du
fichier conservés avec `"s": null` et comptés ; `i` = rang dans le paquet, `oi` =
`properties.objectIndex` (identité stable déjà retenue par l'étape 14d).

#### 2.3.2 Construction (JavaScript, un seul code pour deux hôtes)

**Fichiers** : `frontend/src/services/mapPackage.js`, `frontend/scripts/ocd2package.mjs`.

```js
export const MAP_PACKAGE_SCHEMA = 'aitraceur.mappackage/1'
/** Fonction pure : aucune dépendance au DOM. */
export function buildMapPackage({ ocadFile, objectsGeoJson, fileName, sha256, parserVersion }) { … }
export function gzipMapPackage(pkg) { /* pako.gzip(JSON.stringify(pkg)) */ }
```

- Dans `OcadUploader.jsx` : appeler `buildMapPackage` avec `rawObjectsGeojson` (avant
  reprojection WGS84) et l'ajouter à l'objet passé à `onOcadLoaded` (`mapPackage`).
- `ocd2package.mjs <entrée.ocd> <sortie.json>` : même fonction sous Node (lecture par
  `readOcad(chemin)`, SHA-256 par `node:crypto`). Sert au banc d'essai et aux mesures.

**Tests** (`frontend/src/__tests__/mapPackage.test.js`) avec un faux `ocadFile` minimal :
- un objet surface à trou garde ses deux anneaux ; les coordonnées sont arrondies à 0,01 ;
- `kinds` reflète les géométries observées ; `n_objects` est exact ;
- carte non géoréférencée (`crs.code` = 0) → `georeferenced: false`, `epsg: null` ;
- deux appels sur les mêmes entrées donnent le même JSON, octet pour octet.

#### 2.3.3 Lecture (Python)

**Fichier** : `aitraceur/mapmodel/package.py`.

```python
@dataclass(frozen=True)
class MapSymbol:
    sym_num: int; code: str; major: int; minor: int; name: str
    kinds: frozenset[str]; line_width_mm: float | None; n_objects: int

@dataclass(frozen=True)
class MapObject:
    index: int; object_index: int | None; sym_num: int | None; kind: str   # "P" | "L" | "A"
    geom: "shapely.Geometry"                                              # mètres

@dataclass(frozen=True)
class GeoRef:
    georeferenced: bool; epsg: int | None; scale: int
    easting: float; northing: float; grivation_deg: float

@dataclass(frozen=True)
class MapPackage:
    source: dict; georef: GeoRef; bbox: tuple[float, float, float, float]
    symbols: Mapping[int, MapSymbol]; objects: tuple[MapObject, ...]
    n_repaired: int            # surfaces invalides réparées par shapely.make_valid

def load_map_package(data: bytes | str | Path | dict) -> MapPackage:
    """Accepte JSON ou JSON gzippé. Erreur explicite (ValueError) si le schéma n'est pas
    'aitraceur.mappackage/1' ou si un champ obligatoire manque."""

def to_wgs84(pkg: MapPackage, xy: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """(x, y) → (lng, lat) par pyproj si georeferenced ; ValueError sinon."""
```

#### 2.3.4 Cartes d'essai synthétiques

**Fichier** : `backend/tests/aitraceur/fixtures/maps.py` — deux constructeurs de paquets, réutilisés
jusqu'en phase 6. Coordonnées en mètres, `y` vers le nord, carte non géoréférencée.

**`village(standard="ISSPROM2019", gap_m=1.5)`** — 200 m × 150 m, échelle 1:4000.

| Nom | Type | Géométrie | Code ISSprOM 2019 | Code ISSOM 2007 |
|-----|------|-----------|-------------------|-----------------|
| RUE_EO (zone pavée) | A | rectangle x 0–200, y 60–90 | 501.0 | 529.0 |
| RUE_NS (zone pavée) | A | rectangle x 90–110, y 0–150 | 501.0 | 529.0 |
| PARC_O (terrain découvert) | A | rectangle x 0–90, y 0–60 | 401.0 | 401.0 |
| PARC_E (terrain découvert) | A | rectangle x 110–200, y 0–60 | 401.0 | 401.0 |
| OLIVE_NO (propriété privée) | A | rectangle x 0–90, y 90–150 | 520.0 | 528.1 |
| OLIVE_NE (propriété privée) | A | rectangle x 110–200, y 90–150 | 520.0 | 528.1 |
| B1 (maison au fond du jardin) | A | rectangle x 30–60, y 105–135 | 521.0 | 526.1 |
| B2 (maison sur rue) | A | rectangle x 130–170, y 90–125 | 521.0 | 526.1 |
| AUVENT | A | rectangle x 92–108, y 100–112 | 522.0 | 526.2 |
| FERME (zone fermée, surimpression) | A | rectangle x 0–15, y 60–90 | 709.0 | 709.0 |
| MUR_1 (infranchissable) | L | (0,60) → (45 − gap/2, 60) | 515.0 | 521.1 |
| MUR_2 (infranchissable) | L | (45 + gap/2, 60) → (90,60) | 515.0 | 521.1 |
| MUR_3 (infranchissable) | L | (90,0) → (90,60) | 515.0 | 521.1 |
| ENCLOS (clôture infranchissable fermée) | L | (140,15) (180,15) (180,45) (140,45) (140,15) | 518.0 | 524.0 |
| CLOTURE (franchissable) | L | (110,30) → (140,30) | 516.0 | 522.0 |
| FONTAINE_O | P | (40,30) | 311.0 | 312.0 |
| FONTAINE_ENCLOS | P | (160,30) | 311.0 | 312.0 |
| ARBRE | P | (125,48) | 417.0 | 418.0 |
| PILIER | P | (100,106) | 522.1 | 526.3 |

Avec `gap_m=0`, MUR_1 et MUR_2 forment un seul mur continu. Noms de symboles en français
(« Bâtiment », « Zone interdite d'accès », « Zone pavée », « Mur infranchissable »…).

**`bois()`** — 600 m × 400 m, échelle 1:10000, ISOM 2017-2.

| Nom | Type | Géométrie | Code |
|-----|------|-----------|------|
| FORET (fond) | A | rectangle x 0–600, y 0–400 | 405.0 |
| CHEMIN_EO | L | (0,200) → (600,200) | 505.0 |
| CHEMIN_NS | L | (300,0) → (300,400) | 505.0 |
| LAC (infranchissable) | A | rectangle x 420–560, y 40–160 | 301.0 |
| CLAIRIERE | A | rectangle x 400–500, y 250–350 | 401.0 |
| LENT (course ralentie) | A | rectangle x 50–250, y 220–380 | 406.0 |
| MARCHE | A | rectangle x 80–220, y 20–180 | 408.0 |
| ROCHER_1 | P | (150,300) | 204.0 |
| ROCHER_2 (gros) | P | (350,260) | 205.0 |
| BUTTE | P | (540,300) | 109.0 |
| DEPRESSION | P | (60,100) | 111.0 |

**Tests** (`test_map_package.py`) : les trois paquets se chargent ; `village()` a 19 objets,
`bois()` en a 11 ; les surfaces sont valides ; un schéma inconnu lève `ValueError`.

### 2.4 — Détection de la norme

**Fichiers** : `aitraceur/symbols/detect.py`, `aitraceur/symbols/detect_rules.json`.

```python
@dataclass(frozen=True)
class StandardDetection:
    standard: str | None          # "ISOM2017_2" | "ISSPROM2019" | "ISOM2000" | "ISSOM2007" | None
    confidence: float             # écart de score entre le 1er et le 2e
    scores: Mapping[str, float]
    evidence: tuple[str, ...]     # phrases lisibles : "521 est une surface (bâtiment en norme 2017)"
    needs_confirmation: bool      # confidence < 0.10 ou couverture < 0.60

def detect_standard(symbols: Iterable[MapSymbol], scale: int) -> StandardDetection: ...
```

Algorithme (déterministe) — ne considérer que les symboles ayant au moins un objet et un numéro
principal entre 100 et 599 :

1. **Couverture** de chaque norme : part des couples `(numéro principal, type observé)` de la carte
   présents dans la table de référence de la norme (un symbole `C` de la référence vaut `A` et `L`).
2. **Tests discriminants**, décrits en données dans `detect_rules.json` (chaque test donne +1 aux
   normes qu'il soutient, −1 à celles qu'il contredit) :

   | Test | Soutient | Contredit |
   |------|----------|-----------|
   | 521 observé en surface | ISOM2017_2, ISSPROM2019 | ISOM2000, ISSOM2007 |
   | 526 observé en surface | ISOM2000, ISSOM2007 | ISOM2017_2, ISSPROM2019 |
   | 520 observé en surface | ISOM2017_2, ISSPROM2019 | ISOM2000, ISSOM2007 |
   | 528 observé en surface | ISOM2000, ISSOM2007 | ISOM2017_2, ISSPROM2019 |
   | 529 observé en surface | ISOM2000, ISSOM2007 | ISOM2017_2, ISSPROM2019 |
   | 109 observé en point | ISOM2017_2, ISSPROM2019 | ISOM2000, ISSOM2007 |
   | 109 observé en ligne | ISOM2000, ISSOM2007 | ISOM2017_2, ISSPROM2019 |
   | 206 observé en point | ISOM2000, ISSOM2007 | ISOM2017_2, ISSPROM2019 |
   | échelle ≤ 5000 | ISSPROM2019, ISSOM2007 | ISOM2017_2, ISOM2000 |
   | échelle ≥ 7500 | ISOM2017_2, ISOM2000 | ISSPROM2019, ISSOM2007 |
   | 502, 503 ou 504 observé en ligne | ISOM2017_2, ISOM2000 | ISSPROM2019 |
   | 421 observé | ISSOM2007 | les trois autres |
   | 527 observé en surface | ISOM2000 | les trois autres |

3. `score = 0,6 × couverture + 0,4 × (points obtenus / points possibles, ramené dans [0, 1])`.
4. Norme = meilleur score ; `confidence` = écart avec le second ; `needs_confirmation` si
   `confidence < 0,10` ou si la couverture de la norme retenue est inférieure à 0,60.

Les poids 0,6 / 0,4 et les seuils sont des choix d'implémentation (`source="implementation"`),
à réviser sur les cartes réelles en 2.10.

**Tests** (`test_detect_standard.py`) :
- chacune des quatre tables de référence, donnée comme carte (tous ses symboles « observés », échelle
  15000 pour les normes forêt, 4000 pour les normes sprint), est reconnue comme elle-même avec
  `confidence ≥ 0,25` ;
- `village("ISSPROM2019")` → `ISSPROM2019` ; `village("ISSOM2007")` → `ISSOM2007` ; `bois()` →
  `ISOM2017_2` ;
- une carte de trois symboles sans rapport (800, 801, 802) → `standard is None`.

### 2.5 — Lecture d'une carte : classement de ses symboles

**Fichiers** : `aitraceur/symbols/classify.py`, `aitraceur/symbols/name_hints.json`,
`aitraceur/symbols/overrides.py`.

```python
@dataclass(frozen=True)
class SymbolReading:
    symbol: MapSymbol
    semantics: SymbolSemantics | None
    status: str    # "norme" | "herite" | "nom" | "conflit" | "corrige" | "inconnu" | "ignore"
    note: str      # phrase lisible expliquant le statut

@dataclass(frozen=True)
class MapReading:
    detection: StandardDetection
    readings: Mapping[int, SymbolReading]       # par sym_num
    n_unknown_symbols: int; n_unknown_objects: int

def read_map(pkg: MapPackage, *, forced_standard: str | None = None,
             overrides: Mapping[int, str] = {}) -> MapReading: ...
```

Ordre de décision pour un symbole (premier cas qui s'applique) :

1. **corrige** — le traceur a choisi un rôle (2.6).
2. **ignore** — numéro principal ≥ 600 hors symboles de surimpression à effet (708, 709, 710, 711,
   714 : voir annexe A1 §2.7), ou symbole sans objet.
3. **norme** — une entrée `"<code complet>/<type>"` ou `"<numéro principal>/<type>"` existe dans la
   sémantique de la norme retenue.
4. **herite** — le numéro principal existe dans la norme mais pas avec ce type : pas de sémantique
   sûre → traité comme **inconnu** pour les décisions, avec une note qui le dit.
5. **nom** — code absent de la norme, mais le nom correspond à un indice (`name_hints.json`,
   expressions régulières français / anglais, annexe A1 §5). Seul l'indice « interdit » est appliqué
   d'office (prudence) ; les autres attendent la confirmation du traceur.
6. **inconnu**.

Un symbole classé par la norme dont le nom correspond à un indice d'une **autre** famille passe en
**conflit** (ex. code 406 nommé « Zone interdite ») : la sémantique la plus restrictive est appliquée
et le traceur est invité à trancher.

Précision par la largeur de trait (annexe A1 §2.5) : une ligne de numéro principal 501 est un chemin
pavé si `line_width_mm ≥ 0,30`, un simple bord de zone pavée sinon.

**Tests** (`test_read_map.py`) :
- `village("ISSPROM2019")` et `village("ISSOM2007")` : mêmes familles pour les mêmes objets (les
  deux olives « interdit », B1 et B2 « batiment », murs et enclos « infranchissable », clôture
  « lent », auvent « libre ») ;
- un symbole 521.7 de type surface, absent de la table, → **norme** par le numéro principal ;
- un symbole 850.0 nommé « Propriété privée » → statut **nom**, sémantique « interdit » ;
- un symbole 406.0 nommé « Zone interdite » → **conflit**, sémantique « interdit » ;
- les noms français réels relevés par lidar-o (`scripts/mappings/ffco_fr.yaml` et `isom_fr.yaml`,
  à recopier avec crédit dans `backend/tests/aitraceur/fixtures/noms_ffco.json`, y compris les noms
  tronqués à 32 caractères) reçoivent tous un indice cohérent avec leur groupe d'origine.

### 2.6 — API v2 : cartes

**Fichiers** : `backend/src/api/v2/__init__.py`, `backend/src/api/v2/maps.py`,
`backend/src/api/v2/storage.py` ; inclusion du routeur dans `main.py` (une ligne).
Nouveau réglage `AITRACEUR_DATA_DIR` (défaut : `backend/data/local`).

Stockage : `{DATA_DIR}/maps/{map_id}/` avec `map_package.json.gz`, `symbol_overrides.json`,
`forced_standard.txt` ; `map_id` = 16 premiers caractères de `source.sha256`.
Bibliothèque de corrections réutilisables : `{DATA_DIR}/symbol_library.json`, clé
`"<nom normalisé>|<type>"`.

| Route | Rôle |
|-------|------|
| `POST /api/v2/maps` (multipart, champ `package`) | Valide et enregistre le paquet. Réponse : `{map_id, created, n_objects}`. |
| `GET /api/v2/maps/{map_id}/reading` | `MapReading` en JSON : détection, puis par symbole : code, nom, types, nombre d'objets, famille, passabilité, vitesse, ligne, site, statut, note. |
| `PUT /api/v2/maps/{map_id}/standard` | Corps `{ "standard": "ISSOM2007" \| null }` : force ou libère la norme. |
| `PUT /api/v2/maps/{map_id}/symbols/{sym_num}` | Corps `{ "role": "<modèle>" \| null, "remember": bool }` : correction du traceur. |
| `GET /api/v2/maps/{map_id}/v1-inputs?mode=sprint\|forest` | Pont v1 (2.8). |

Modèles de rôle proposés au traceur (liste fermée, définie dans `overrides.py`, chacun associé à
une `SymbolSemantics`) : `interdit`, `infranchissable`, `batiment`, `auvent`, `zone_pavee`,
`chemin_net`, `chemin_peu_visible`, `ligne_nette`, `ligne_peu_nette`, `vegetation_V1` … `vegetation_V5`,
`eau_franchissable`, `ponctuel_evident`, `ponctuel_moyen`, `ponctuel_fin`, `courbe_de_niveau`,
`ignorer`.

**Tests** (`backend/tests/test_api_v2_maps.py`, avec le client HTTP de test existant) : envoi de
`village()` → `created: true` ; second envoi → `created: false` ; `reading` renvoie la norme ;
`PUT symbols` change le statut en `corrige` et survit à un rechargement ; paquet au mauvais schéma →
422 avec un message clair.

### 2.7 — Interface : « Lecture de la carte »

**Fichiers** : `frontend/src/services/apiV2.js`, `frontend/src/components/v2/MapReadingPanel.jsx`,
retouches de `App.jsx` et `OcadDiagPanel.jsx`.

- À l'import d'une carte, après le rendu existant : envoyer le paquet (`POST /api/v2/maps`), garder
  `mapIdV2` dans l'état, puis charger `reading`.
- Bandeau en tête du panneau : norme reconnue, confiance, phrases de preuve ; bouton « Ce n'est pas
  la bonne norme » → liste des quatre normes.
- Tableau des symboles (reprendre la mise en forme de l'inventaire 14a) : code, nom, nombre d'objets,
  « compris comme », pastille de statut, liste déroulante de correction, case « retenir pour mes
  autres cartes ». Clic sur une ligne → surbrillance des objets sur la carte (mécanisme existant de
  14c, `resolveHighlightFeatures`).
- Filtre rapide : « à confirmer » (statuts `nom`, `conflit`, `inconnu`, `herite`).
- Compteur visible en permanence tant qu'il reste des symboles à confirmer :
  « 3 symboles (41 objets) à confirmer ».
- Le panneau de diagnostic 14a reste **factuel** et inchangé ; la lecture est un panneau distinct.

**Tests** (vitest) : fonctions pures de tri et de filtrage du tableau ; comptage des symboles à
confirmer.

### 2.8 — Pont v1 : nourrir le moteur actuel avec des entrées justes

**Fichier** : `backend/src/api/v2/v1_bridge.py` (hors du paquet `aitraceur` : il connaît le
vocabulaire privé du moteur v1).

`GET /api/v2/maps/{map_id}/v1-inputs?mode=…` renvoie, en WGS84 :

```jsonc
{
  "forbidden_zones_polygons": [ [[lng, lat], …], … ],   // surfaces interdites + surfaces infranchissables hors bâtiments
  "building_polygons":        [ [[lng, lat], …], … ],
  "candidate_points": [ { "x": lng, "y": lat, "isom": 401, "attractiveness": 0.70,
                          "description": "jonction de chemins", "role": "jonction" } ],
  "line_features": [ { "type": "Feature", "geometry": { "type": "LineString", "coordinates": […] },
                       "properties": { "sym": 505 } } ]
}
```

Candidats (version simple ; la phase 3 la remplace par les vrais sites) :

- tout objet ponctuel dont la sémantique a un rôle de site ;
- sur les chemins (famille `chemin`, ligne L1) : jonctions (au moins trois branches après découpage aux
  intersections), coudes (changement de direction ≥ 45° mesuré sur 10 m de part et d'autre),
  extrémités libres ;
- sur les bâtiments et auvents : sommets dont l'angle est ≥ 60° et dont les deux côtés font ≥ 3 m ;
- sur les autres lignes à rôle de site (clôtures, murs, cours d'eau) : coins ≥ 60° et extrémités ;
- petites surfaces à rôle `petite_surface` (plus grande dimension ≤ 30 m, ≤ 10 m en sprint) : leur
  centroïde ;
- **jamais** le centroïde d'une grande surface ;
- retirer tout candidat situé dans une surface interdite ou infranchissable ; fusionner les
  candidats à moins de 3 m (sprint) ou 10 m (forêt).

Le moteur v1 attend ses propres codes. Table de traduction `V1_CODE_BY_ROLE`, à établir à partir des
commentaires de `ISOM_ATT` (`App.jsx` l.353-376) et des listes `preferred_isom_codes` de
`placement_rules.json`, et à **vérifier contre ces deux fichiers avant de coder** :

| Rôle du registre | Code v1 | `attractiveness` |
|------------------|---------|------------------|
| jonction de chemins | 401 | 0,70 |
| coude de chemin | 404 | 0,65 |
| extrémité de chemin | 405 | 0,60 |
| butte | 107 | 1,00 |
| dépression, trou | 109 | 1,00 |
| rocher | 118 | 1,00 |
| groupe de rochers | 119 | 1,00 |
| falaise (pied, extrémité) | 120 | 0,80 |
| talus, ravine | 106 | 0,80 |
| fontaine, source, trou d'eau | 209 | 0,80 |
| coin de végétation, petite surface | 301 | 0,60 |
| arbre remarquable | 416 | 0,90 |
| coin de bâtiment | 521 | 0,50 |
| coin ou extrémité de clôture, de mur | 516 | 0,50 |

Lignes pour le modèle perceptif du v1 (`extract_line_segments`, `isom_semantics.json`) :
route et chemin pavé → 501 ; chemin carrossable → 516 ; chemin, sentier → 505 ; sentier peu visible
→ 507 ; layon → 504 ; courbes → 101 / 102 / 103 ; cours d'eau et fossés franchissables → 305 ;
rive infranchissable → 306 ; limite de végétation ou de culture → 215. Les autres lignes ne sont
pas transmises.

**Branchement** :

1. `buildGenerationParams` (créée en phase 1) : si `mapIdV2` existe, appeler `v1-inputs` et utiliser
   ses `candidate_points`, `forbidden_zones_polygons` et `line_features` (à la place
   d'`extractCandidatePoints`, des zones `OOB_ISOM` et d'`ocadLineFeatures`) ; ajouter
   `zones_source: "registry"` au corps.
2. `_sprint_impl` et `_circuit_impl` : si `zones_source == "registry"`, ne plus appeler
   `fetch_ocad_forbidden_zones` ; les zones du corps font foi.
3. Une fois le pont validé sur les cartes réelles (2.10), **supprimer** :
   - dans `App.jsx` : `ATTRACTIVE_ISOM`, `ATTRACTIVE_ISSOM`, `OOB_ISOM`, `BUILDING_ISOM`,
     `PATH_ISOM`, `BUILDING_ISSOM`, `PATH_ISSOM`, `ISOM_ATT`, `extractCandidatePoints`,
     `LINE_SEG_CODES` et les fonctions qui ne servent plus qu'à eux ;
   - dans `backend/tile-service/server.js` : `FORBIDDEN_SYMS`, `BUILDING_SYMS` et la route
     `/map/:mapId/forbidden-zones` ;
   - dans `services/learning/ocad_pipeline.py` : `fetch_ocad_forbidden_zones`.
   Les fichiers `ocad_semantics.json`, `isom_semantics.json`, `isom_navigation_roles.json`,
   `control_descriptions.json` et `ISOM_DESCRIPTIONS` restent : c'est le vocabulaire **privé** du
   moteur v1, désormais alimenté par le pont ; ils disparaîtront avec lui (phase 11). Ajouter en
   tête de chacun une mention : « Vocabulaire interne du moteur v1. Ce ne sont pas des numéros de
   norme. Ne pas réutiliser. »

**Tests** (`backend/tests/test_v1_bridge.py`) sur `village()` dans ses deux normes :
- les deux olives et la zone fermée sont dans `forbidden_zones_polygons` ; les parcs et les rues
  n'y sont pas ;
- aucun candidat n'est à l'intérieur d'une olive ; les quatre coins de B1 sont absents ;
- les coins sud de B2, (130, 90) et (170, 90), sont présents (ses coins nord, en bordure d'olive,
  ne seront écartés qu'en phase 3) ;
- les deux normes donnent les mêmes candidats à 0,01 m près.
Sur `bois()` : la jonction (300, 200) est candidate avec le code 401 ; aucun candidat au centre de
FORET, LENT ou MARCHE ; les quatre éléments ponctuels sont candidats.

### 2.9 — Tests d'architecture : plus de numéro de symbole hors du registre

- `backend/tests/aitraceur/test_architecture.py` : dans `backend/src/aitraceur/` (hors `symbols/`)
  et `backend/src/api/v2/` (hors `v1_bridge.py`), aucun littéral entier de 100 à 799 n'apparaît dans
  un ensemble, une liste ou un dictionnaire d'au moins trois éléments du même ordre de grandeur
  (analyse `ast`).
- `frontend/src/__tests__/noSymbolTables.test.js` : aucun fichier de `frontend/src` (hors tests)
  ne contient `new Set([` suivi de trois nombres ou plus compris entre 100 et 799.

### 2.10 — Mesure sur les cartes réelles

Avec le traceur :

1. Pour chaque carte d'essai : `node frontend/scripts/ocd2package.mjs carte.ocd carte.json`, puis un
   petit script `backend/tools/read_map_report.py carte.json` qui imprime la norme, la confiance, les
   preuves, et la liste des symboles à confirmer. Rassembler dans `docs/plan/mesures/P2_cartes.md` :

   | Carte | Échelle | Norme détectée | Confiance | Symboles | À confirmer | Objets concernés |
   |-------|---------|----------------|-----------|----------|-------------|------------------|

2. Le traceur valide ou corrige la norme de chaque carte (c'est la vérité terrain de la détection).
   Si une détection est fausse, ajuster `detect_rules.json`, ajouter la carte (réduite à sa liste de
   symboles, sans géométrie) aux tests, recommencer.
3. Le traceur passe en revue l'onglet « Lecture de la carte » sur deux cartes de sprint et classe
   les symboles à confirmer.
4. Refaire les captures de la phase 0 (les entrées ont changé), rejouer le banc avec le pont actif.
   `forbidden_hits` est désormais calculé contre les surfaces interdites **du registre**.
   Écrire `docs/plan/mesures/P2_apres.md` (avant / après).

## Critères d'acceptation

1. Tous les tests de 2.1 à 2.9 passent.
2. Sur les cartes réelles, la norme détectée égale la norme validée par le traceur pour toutes les
   cartes, sans intervention manuelle, ou bien `needs_confirmation` est vrai pour celles qui échouent.
3. Sur chaque carte de sprint réelle, toutes graines confondues : `forbidden_hits == 0`, la vérité
   étant les surfaces interdites du registre après corrections du traceur.
4. Dans le navigateur, sur une carte ISSOM 2007 ou ISOM 2000 (s'il en existe une dans le lot), le
   traceur voit l'olive listée comme « interdit » dans l'onglet de lecture.
5. Les tables listées en 2.8 (3) ont disparu ; les deux tests d'architecture passent.
6. Le compte rendu liste, carte par carte, les symboles que le traceur a dû classer à la main :
   c'est la matière première pour enrichir `name_hints.json`.

## Hors périmètre

- Atteignabilité, côté d'accès, calque de terrain (phase 3).
- Niveaux et couleurs (phase 4).
- Lecture des fichiers `.omap` (phase 10) et des parcours contenus dans un fichier OCAD (phase 9).
- Toute retouche du moteur v1 autre que le branchement du pont.

## Pièges

- Un fichier OCAD peut contenir des symboles de parcours (701 à 799) et leurs objets : ils ne
  décrivent pas le terrain. Ils sont ignorés ici et repris en phase 9.
- Les surfaces OCAD peuvent être invalides (auto-intersections) : `shapely.make_valid`, et compter
  les réparations.
- En norme 2017, le blanc de la carte (forêt 405) est souvent **l'absence d'objet**. Ne jamais
  conclure « hors carte » ou « interdit » d'une absence d'objet dans cette phase ; la notion de zone
  cartographiée arrive en phase 3.
- Un paquet de carte pèse de quelques mégaoctets à quelques dizaines : l'envoyer compressé, et ne
  jamais le renvoyer à chaque génération (le moteur le relit par `map_id`).
- Ne pas « corriger » les numéros des tables privées du moteur v1 : elles sont fausses comme normes
  mais cohérentes entre elles ; le pont parle leur langue.
