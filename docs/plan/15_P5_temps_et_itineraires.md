# Phase 5 — Temps et itinéraires

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

## But

Pour deux points quelconques de la carte, savoir répondre aux questions que se pose un traceur :

- par où passe-t-on, et en combien de temps ?
- y a-t-il **plusieurs** itinéraires qui se valent — un vrai choix — ou un seul ?
- quelle part de l'itinéraire suit une ligne, et de quel type ? quel est le plus long passage sans
  aucun appui ?
- qu'est-ce qui précède le poste (point d'attaque) et qu'est-ce qui l'arrête (ligne d'arrêt) ?

Ces réponses sont des **mesures** : des nombres attachés à la jambe, sans jugement. Le jugement
(« conforme au bleu », « intéressant pour une moyenne distance ») est la phase 6.

## Ce que le traceur verra

Un outil « inspecteur de jambe » : il clique deux points (ou deux postes), l'application trace les
itinéraires qu'elle a trouvés, du plus rapide au plus lent, et affiche un tableau : temps, longueur,
détour, nombre de choix, part sur chemin, plus long tronçon hors ligne, point d'attaque, ligne
d'arrêt. C'est un outil utile en soi, avant toute génération.

## Prérequis

- Phases 3 et 4 terminées (terrain, sites, `LineIndex`, niveaux).
- Relire `02_VISION_ARCHITECTURE.md` §7 (durées mesurées).

## Contexte vérifié

- `skimage.graph.MCP_Geometric(costs, fully_connected=True, sampling=(res, res))` calcule depuis un
  point le temps minimal vers toutes les cellules ; le coût d'un pas est la moyenne des deux
  cellules multipliée par la distance. Durées mesurées (un cœur) : 0,16 s pour une fenêtre de
  ±300 m à 0,5 m ; 0,53 s pour ±500 m ; 1,08 s pour 3 km × 3 km à 2 m ; tracé d'un itinéraire :
  5 ms. `find_costs` n'a plus de borne de coût utilisable (scikit-image 0.26) : on borne par fenêtre.
- Le coût est **isotrope** : ce solveur ne sait pas qu'une pente coûte plus à la montée qu'à la
  descente. Le relief n'entre donc pas dans cette phase (phase 10).
- ISOM 2017-2 §2.3 (p. 9-10 du PDF) : la référence « 100 % » est une forêt ouverte et plate courue
  à 4 min/km ; cinq catégories : > 100 %, 80–100 %, 60–80 %, 20–60 %, < 20 %.
- Le dépôt contient **338 annotations** de jambes par le traceur : `output/annotations_<carte>.csv`
  (colonnes `map, circuit_id, leg_index, label, timestamp`) pour huit cartes, à joindre à
  `output/intent_legs_<carte>.csv` (`map_name, circuit_id, leg_index, leg_m, start_lat, start_lon,
  end_lat, end_lon, …`). Étiquettes de forêt : `suivi` (127), `attaque` (61), `uncertain` (104).
  Étiquettes de sprint, 46 jambes, au format `<choix>_<impact>` (`backend/scripts/annotate_legs.html`
  l.186-212) : choix 0 = itinéraire évident, 1 = deux variantes, 2 = plusieurs ; impact 0 = peu
  importe, 1 = influence, 2 = déterminant. Ces jambes viennent de circuits produits par le moteur
  v1 ; les étiquettes, elles, sont le jugement du traceur : c'est un jeu de validation, pas un
  corpus de bons interpostes.
- Le prototype calculait un itinéraire par paire de points (`route_through_array`) et prenait
  « détour × 2 » pour mesure du choix : un détour imposé n'est pas un choix. Ne rien en reprendre.

## Étapes

### 5.1 — Du terrain au coût

**Fichier** : `aitraceur/routes/cost.py`.

```python
@dataclass(frozen=True)
class CostConfig:
    pace_ref_s_per_m: float = 0.24          # 4 min/km                       source="ISOM 2017-2 §2.3"
    speed_ratio: Mapping[str, float] = MappingProxyType(
        {"V1": 1.10, "V2": 0.90, "V3": 0.70, "V4": 0.40, "V5": 0.15})   # milieux des catégories ; V1 : source="implementation"
    penalty_strip_cells: float = 1.5        # largeur de la bande de pénalité, en cellules (rastérisation de la phase 3)

def cost_grid(terrain: Terrain, config: CostConfig = CostConfig()) -> np.ndarray:
    """float32, secondes par mètre POUR L'ALLURE DE RÉFÉRENCE ; np.inf hors terrain.passable.
    coût = pace_ref ÷ speed_ratio[classe]
         + terrain.cross_penalty_s ÷ (penalty_strip_cells × rés)     # franchir la bande coûte ≈ la pénalité"""

def guided_mask(terrain: Terrain, lines: LineIndex, classes: Collection[str], *,
                open_counts: bool, open_mask: np.ndarray, corridor_m: float) -> np.ndarray:
    """Cellules où un coureur « conduit » peut se trouver : à moins de corridor_m d'une ligne des
    classes données, ou (open_counts) en terrain ouvert. corridor_m ≥ 2,5 × rés, imposé."""

def open_mask(terrain: Terrain, pkg: MapPackage, reading: MapReading) -> np.ndarray:
    """Cellules des surfaces portant le drapeau `ouvert` (A1 §3.3)."""
```

**L'allure du niveau ne change pas les itinéraires** : `pace_factor` (A2 §4 et §5) multiplie tous
les temps — course et franchissements — par le même nombre. Les champs se calculent donc une seule
fois par carte, à l'allure de référence ; tout temps affiché ou comparé à une limite est multiplié
par `pace_factor` au moment de l'usage (`LegFacts` garde les temps de référence).
Couloir par défaut : 2 m en ville, 6 m en forêt (`source="implementation"`).

**Tests** (`test_cost.py`) sur `bois()` : coût en (300, 200) = 0,24 ÷ 1,10 ;
en (20, 390) = 0,24 ÷ 0,90 ; en (150, 300) = 0,24 ÷ 0,70 ; en (150, 100) = 0,24 ÷ 0,40 ; `inf` dans
LAC. Sur `village()` : traverser CLOTURE perpendiculairement de (125, 20) à (125, 40) coûte le temps
de 20 m de pelouse plus la pénalité de la clôture, à ±40 % de la pénalité près.
`guided_mask` sur `bois()`, classes {L1}, sans terrain ouvert : (300, 100) dedans, (310, 100)
dehors ; avec terrain ouvert : (450, 300) (CLAIRIERE) dedans.

### 5.2 — Champ de temps et tracé

**Fichier** : `aitraceur/routes/timefield.py`.

```python
@dataclass(frozen=True)
class Route:
    xy: np.ndarray            # (n, 2) mètres, de l'origine vers la destination
    time_s: float
    length_m: float

@dataclass
class TimeField:
    grid: Grid
    origin_xy: tuple[float, float]
    window: tuple[int, int, int, int]      # r0, r1, c0, c1 dans la grille
    t_s: np.ndarray                        # float32, np.inf si inatteignable dans la fenêtre
    def at(self, xy) -> float: ...
    def route_to(self, xy) -> Route | None: ...

def time_field(cost: np.ndarray, grid: Grid, origin_xy, *, radius_m: float | None = None) -> TimeField: ...
def trace(t_s: np.ndarray, cost: np.ndarray, grid: Grid, window, dest_xy) -> Route | None:
    """Remonte le champ sans l'objet MCP (champ relu depuis le cache) : à chaque pas, le voisin n
    qui minimise t_s[n] + coût du pas (n → courant), le coût du pas étant celui de MCP_Geometric."""
```

- L'origine et la destination sont des `stand_xy` (phase 3), jamais le centre d'un bâtiment.
- `radius_m` borne la fenêtre ; `None` = toute la grille.
- Un champ se sauve en `.npy` (`t_s` en float32) ; `trace` suffit à en tirer des itinéraires.

Carte ajoutée aux fixtures pour cette phase — **`croix()`** : 600 m × 400 m, 1:10 000, ISOM 2017-2 ;
fond entier en végétation « marche » (408) ; CHEMIN_EO (0,200) → (600,200) et CHEMIN_NS (300,0) →
(300,400) en 505. Hors des chemins, tout est lent : l'itinéraire le plus rapide suit les chemins.
(Sur `bois()`, dont le fond est une forêt courante, couper l'angle à travers bois est plus rapide
que suivre deux chemins à angle droit : ce n'est pas un bon cas d'essai pour le suivi de ligne.)

**Tests** (`test_timefield.py`) :

- `croix()`, de (100, 200) à (300, 100) : l'itinéraire suit les chemins par le croisement ; longueur
  300 m à 5 % près ; temps = 300 × 0,24 ÷ 1,10 = 65,5 s à 5 % près ;
- `bois()`, de (100, 200) à (500, 200) : 400 m le long du chemin, 87,3 s à 3 % près ;
- `bois()`, de (400, 100) à (580, 100) : contourne LAC ; longueur 266,5 m à 5 % près (géométrie :
  63,2 + 140 + 63,2) ;
- `village(gap_m=1.5)`, de (100, 75) à (40, 30) : passe par la brèche — un point de l'itinéraire à
  moins de 1,5 m de (45, 60) ; avec `gap_m=0` : `route_to` renvoie `None` ;
- `village()`, de (100, 75) à un point d'ENCLOS : `None` ;
- `route_to` et `trace` donnent le même temps à 1 % près et des tracés à moins d'une cellule ;
- champ borné à 100 m : `inf` au-delà.

### 5.3 — Les itinéraires qui se valent

**Fichier** : `aitraceur/routes/alternatives.py`.

Principe : pour deux champs `Ta` (depuis A) et `Tb` (depuis B), `S = Ta + Tb` vaut en chaque cellule
le temps du meilleur itinéraire A → B **passant par cette cellule**. Tout itinéraire franchit les
« lignes de niveau » de `Ta − Tb`. Sur une telle ligne, chaque **minimum local** de `S` est le point
de passage d'une famille d'itinéraires distincte.

```python
@dataclass(frozen=True)
class RouteSet:
    routes: tuple[Route, ...]         # triées par temps ; routes[0] = le plus rapide
    best_time_s: float

def route_alternatives(fa: TimeField, fb: TimeField, cost, *, eps: float = 0.25, sep_m: float,
                       max_routes: int = 4, bands: tuple[float, ...] = (-0.5, 0.0, 0.5)) -> RouteSet: ...
```

Algorithme :

1. `T* = Ta(B)`. Si infini : aucun itinéraire.
2. Pour chaque bande `c` de `bands` : cellules où `|Ta − Tb − c·T*| ≤ δ`, avec `δ` = temps de
   traversée de deux cellules au coût médian. Dans la bande, garder `S ≤ (1 + eps)·T*` ; chaque
   composante connexe (8-connexité) est une **porte** ; son représentant est la cellule de `S` minimal.
3. Itinéraire d'une porte `g` : tracé de `g` vers A dans `Ta`, retourné, puis tracé de `g` vers B
   dans `Tb` ; temps `S(g)`.
4. Dédoublonnage : deux itinéraires sont **le même** si au moins 80 % des points de l'un sont à moins
   de `sep_m` de l'autre ; garder le plus rapide. `sep_m` : 10 m en ville, 40 m en forêt
   (`source="implementation"`).
5. Trier par temps ; garder `max_routes`.

Trois bandes et non une : deux variantes qui se séparent puis se rejoignent avant le milieu
franchissent la bande centrale par la même porte.

**Tests** (`test_alternatives.py`) :

- **pâté de maisons** (carte du test, ISSprOM 2019, 1:4000) : place pavée 120 m × 80 m, un bâtiment
  40 m × 30 m centré ; A et B au milieu des côtés ouest et est → deux itinéraires, nord et sud,
  temps égaux à 3 % près, chacun de longueur géométrique attendue à 3 % près ;
- même carte, bâtiment décalé de 5 m vers le nord : l'itinéraire sud est le plus rapide ; écart de
  longueur conforme à la géométrie à 1 m près ;
- `bois()`, autour de LAC, de (400, 100) à (580, 100) : deux itinéraires (nord, sud), temps égaux à
  3 % près ;
- `bois()`, de (100, 200) à (500, 200) le long de CHEMIN_EO : un seul itinéraire ;
- **séparation précoce** (carte du test) : deux obstacles en enfilade, le premier contournable des
  deux côtés à temps égal, le second d'un seul : deux itinéraires trouvés (une seule bande centrale
  n'en trouverait qu'un — le test le vérifie avec `bands=(0.0,)`).

### 5.4 — Mesures d'un itinéraire et d'une jambe

**Fichier** : `aitraceur/routes/features.py`.

```python
@dataclass(frozen=True)
class RouteFacts:
    time_s: float; length_m: float
    s_m: np.ndarray                 # abscisse des échantillons (pas : 1 m en ville, 5 m en forêt)
    line_class: np.ndarray          # uint8 par échantillon : 0 aucune, 1, 2, 3 = L1, L2, L3 suivie
    line_id: np.ndarray             # int32 : identité de la ligne suivie (-1 si aucune)
    in_open: np.ndarray             # bool : terrain ouvert
    speed_class: np.ndarray         # uint8
    n_turns: int                    # changements de direction ≥ turn_angle_deg après simplification à 2 m
    crossings: Mapping[str, int]    # franchissements de lignes « lent », par famille
    n_collecting: int               # points d'appui : lignes L1/L2 coupées + sites d'évidence ≤ 2 frôlés (à moins de 10 m)
    exit_bearing_deg: float; approach_bearing_deg: float     # cap des 30 premiers et des 30 derniers mètres

    def on_line_m(self, classes: Collection[str]) -> float: ...
    def offline_runs(self, classes: Collection[str], open_counts: bool) -> list["OfflineRun"]: ...
    def n_line_changes(self, classes: Collection[str]) -> int: ...

@dataclass(frozen=True)
class OfflineRun:
    start_s_m: float; length_m: float
    all_open: bool                  # tout le tronçon en terrain ouvert
    ends_on: str | None             # classe de la ligne qui le termine (sa « ligne d'arrêt »), None si aucune

@dataclass(frozen=True)
class LegFacts:
    a_xy: tuple[float, float]; b_xy: tuple[float, float]
    straight_m: float
    routes: tuple[RouteFacts, ...]             # physiques, triées par temps
    n_choices: int                             # itinéraires à moins de choice_eps du plus rapide
    spread: float | None                       # (t2 − t1) ÷ t1 ; None s'il n'y a qu'un itinéraire
    detour: float                              # longueur du plus rapide ÷ distance à vol d'oiseau
    guided: Mapping[str, RouteFacts | None]    # "L1" (vert), "L1L2L3" (bleu) : meilleur itinéraire « conduit », None s'il n'existe pas
    guided_alt_ratio: Mapping[str, float | None]   # temps de la 2e variante conduite ÷ 1re ; None si unique
    attack_dist_m: Mapping[int, float | None]  # par évidence maximale (2, 3) : distance, le long de l'itinéraire, du dernier élément évident au poste
    catching_dist_m: Mapping[str, float | None]    # par classe ("L1", "L2", "L3") : distance de la première ligne en travers derrière B
    barrier_at_control: bool                   # sprint : B collé à un infranchissable qui commande l'approche
    flags: tuple[str, ...]                     # "multi_niveaux" si un itinéraire traverse une zone à étages…

def route_facts(route: Route, terrain, lines: LineIndex, sites: Sequence[Site], config) -> RouteFacts: ...
def analyze_leg(a: Site | tuple, b: Site | tuple, ctx: "LegContext", *, levels: Collection[str]) -> LegFacts: ...
```

Définitions exactes (toutes les constantes dans `FeatureConfig`, `source="implementation"` sauf
mention) :

| Mesure | Définition |
|--------|------------|
| ligne **suivie** en un échantillon | la ligne de plus petite classe à moins de `corridor_m` (2 m ville, 6 m forêt) dont la direction locale fait moins de 35° avec celle de l'itinéraire. Une ligne seulement coupée n'est pas suivie. |
| changement de ligne | passage d'un `line_id` à un autre, en ignorant les interruptions de moins de 10 m. |
| tronçon hors ligne | suite maximale d'échantillons qui ne suivent aucune ligne des classes données et (si `open_counts`) ne sont pas en terrain ouvert. |
| changement de direction (`n_turns`) | sommet de l'itinéraire simplifié (Douglas-Peucker, 2 m) dont la déviation atteint `turn_angle_deg` (45°, A2 §5). |
| `n_choices` | nombre d'itinéraires de temps ≤ (1 + `choice_eps`) × le meilleur ; `choice_eps` = 0,10 en ville, 0,15 en forêt. |
| point d'attaque | en remontant l'itinéraire le plus rapide depuis B sur 300 m au plus : premier site valable d'évidence ≤ k situé à moins de 10 m de l'itinéraire (5 m en ville), ou première jonction ou premier croisement de lignes franchi. `attack_dist_m[k]` = distance restante jusqu'à B. |
| ligne d'arrêt | secteur de sommet B, d'axe `approach_bearing_deg`, de demi-angle 45° et de rayon 200 m : première ligne de la classe qui le traverse en faisant un angle ≥ 45° avec l'axe. Un bord de surface nette compte (A1). |
| `barrier_at_control` | il existe un infranchissable à moins de 3 m de B et un point franchissable de l'autre côté, à moins de 6 m à vol d'oiseau de B, qui demande plus de 20 s de course depuis `stand_xy`. (« poste devant ou derrière un élément infranchissable », MF p. 10.) |
| itinéraire **conduit** | meilleur itinéraire dans `cost` restreint à `guided_mask` (classes du niveau, terrain ouvert compris). Calculé seulement si `levels` contient vert ou bleu. |

**Tests** (`test_features.py`) :

- `croix()`, (100, 200) → (300, 100) : `on_line_m({"L1"})` ≥ 95 % de la longueur ; aucun tronçon
  hors ligne de plus de 10 m ; `n_line_changes` = 1 (CHEMIN_EO puis CHEMIN_NS) ; `n_turns` = 1 ;
  `guided["L1"]` existe et a le même temps à 2 % près ;
- `croix()`, (100, 200) → (330, 320), un point à 30 m à l'est de CHEMIN_NS : l'itinéraire passe par
  le croisement, remonte le chemin et le quitte peu avant l'arrivée ; dernier tronçon hors ligne
  entre 30 et 45 m ; `attack_dist_m[2]` = distance du croisement (300, 200) à l'arrivée le long de
  l'itinéraire, soit 140 m à 15 m près ; `guided["L1"]` est `None` (le point n'est sur aucun
  chemin) ;
- `croix()`, (100, 320) → (270, 320), arrivée par l'ouest à 30 m de CHEMIN_NS :
  `catching_dist_m["L1"]` = 30 m à 5 m près ; (300, 100) → (300, 300), arrivée par le sud le long du
  chemin : `None` (la ligne est parallèle, elle n'arrête rien) ;
- `bois()`, (350, 300) → (550, 300) à travers CLAIRIERE : `offline_runs({"L1"}, open_counts=False)`
  contient un tronçon de 200 m ; avec `open_counts=True`, le tronçon dans la clairière disparaît ;
- pâté de maisons : `n_choices` = 2, `spread` < 0,03 ; chaque itinéraire a `n_turns` = 2 ou plus ;
- **piège** (carte du test) : poste au pied d'un mur infranchissable de 60 m, accessible d'un seul
  côté → `barrier_at_control` vrai ; même poste à 10 m du mur → faux.

### 5.5 — Contexte de calcul et cache

**Fichier** : `aitraceur/routes/context.py`.

```python
@dataclass
class LegContext:
    pkg: MapPackage; reading: MapReading; terrain: Terrain; reach: Reachability
    lines: LineIndex; sites: tuple[Site, ...]
    cost: np.ndarray; guided_cost: Mapping[str, np.ndarray]
    fields: "FieldStore"

class FieldStore:
    """Champs de temps par (clé de coût, cellule d'origine). Mémoire : les `ram_fields` derniers
    utilisés (défaut 64). Disque : {DATA_DIR}/maps/{map_id}/fields/<clé>/<row>_<col>.npy, plafonné à
    `disk_mb` (défaut 2 000 Mo ; les plus anciens sont effacés)."""
    def get(self, cost_key: str, origin_xy, radius_m: float) -> TimeField: ...
```

La clé de coût est l'empreinte de (clé du terrain, `CostConfig`, classes du masque conduit) —
sans l'allure, qui n'y entre pas. Rayon de fenêtre : la borne haute des longueurs d'interposte du format (phase 4) × 1,5.

**Tests** : deux `get` identiques → un seul calcul ; plafond de mémoire respecté ; un champ relu du
disque donne les mêmes itinéraires.

### 5.6 — Validation sur les jambes annotées par le traceur

**Fichier** : `backend/tools/validate_leg_facts.py`.

1. Joindre `annotations_<carte>.csv` et `intent_legs_<carte>.csv` sur
   `(map, circuit_id, leg_index)` ; en cas d'annotations multiples d'une même jambe, garder la plus
   récente. Écarter `uncertain`.
2. Pour chaque carte dont le paquet est disponible dans le dossier local du traceur
   (`AITRACEUR_MAPS_DIR`) : convertir les extrémités en mètres, les accrocher à la cellule
   franchissable la plus proche (au-delà de 15 m : jambe écartée et comptée), calculer `LegFacts`
   au niveau orange.
3. Mesurer, et écrire `docs/plan/mesures/P5_validation_jambes.md` :

   | Question | Mesure | Seuil pour « établi » |
   |----------|--------|-----------------------|
   | Forêt : `suivi` contre `attaque` | Aire sous la courbe ROC de la part de l'itinéraire suivant une ligne (`on_line_m` ÷ longueur) | ≥ 0,75 |
   | Forêt : `attaque` | Part des jambes `attaque` dont le dernier tronçon hors ligne dépasse 50 m | ≥ 70 % |
   | Sprint : nombre de choix (0, 1, 2) | Corrélation de rang (Spearman) avec `n_choices` (1, 2, 3 ou plus) | ≥ 0,5 |
   | Sprint : impact (0, 1, 2) | Corrélation de rang avec `spread` (sens inverse) parmi les jambes à 2 itinéraires ou plus | consigné, sans seuil (trop peu de jambes) |

4. Sous le seuil : ne **pas** régler les constantes à l'aveugle. Sortir les vingt jambes les plus en
   désaccord (image : carte, itinéraires, étiquette), les regarder avec le traceur, classer chaque
   désaccord — erreur de lecture de carte, définition de mesure à revoir, étiquette discutable — et
   corriger la cause. Chaque constante modifiée l'est avec la mesure avant / après au registre.

Si aucune des huit cartes n'est disponible, l'étape est reportée et la porte de sortie de la phase
le dit ; la phase 6 ne démarre pas sans elle.

### 5.7 — API et interface : l'inspecteur de jambe

**Fichiers** : `backend/src/api/v2/legs.py`, `frontend/src/components/v2/LegInspector.jsx`.

| Route | Rôle |
|-------|------|
| `POST /api/v2/maps/{map_id}/prepare` | Construit et met en cache terrain, sites, lignes, coûts. Tâche de fond avec état (`GET …/prepare/{task_id}`), sur le modèle existant de la génération sprint. |
| `POST /api/v2/maps/{map_id}/leg` | Corps `{ "a": {"site_id"} \| {"lnglat"}, "b": …, "color", "format" }`. Réponse : `LegFacts` sérialisé, itinéraires en WGS84, et pour chaque itinéraire les tronçons colorés (ligne L1 / L2 / L3 / ouvert / hors ligne). |

Interface : outil « Inspecter une jambe » — deux clics sur la carte ou sur deux postes existants ;
itinéraires tracés (le plus rapide en trait plein, les autres en tirets) avec leur temps ; panneau :

```
A → B   à vol d'oiseau 310 m
Itinéraire 1   1 min 52   355 m   sur chemin 82 %   hors ligne max 40 m   3 changements de direction
Itinéraire 2   1 min 58   390 m   (+5 %)            …
Choix : 2 itinéraires à moins de 15 %
Point d'attaque : jonction de chemins à 60 m du poste
Ligne d'arrêt : ruisseau (L2) 35 m derrière le poste
```

Aucun verdict de niveau ici (phase 6) ; seulement les mesures, en clair.

**Tests** : client HTTP sur `bois()` — `leg` de (100, 200) à (300, 100) renvoie un itinéraire de
300 m à 5 % près ; point de départ dans LAC → 422 « point non franchissable » ; deuxième appel
identique servi par le cache des champs.

### 5.8 — Budget de temps (K9)

`backend/tools/bench_routes.py carte.json` mesure sur le PC du traceur, pour chaque carte d'essai :
construction du coût, un champ de temps (médiane sur 20 sites), une analyse de jambe complète
(médiane sur 50 paires), et l'extrapolation « préparer la carte » = nombre de sites × temps d'un
champ. Résultats dans `docs/plan/mesures/P5_budget.md`.

Si la préparation extrapolée dépasse 3 minutes : d'abord réduire la fenêtre au strict nécessaire,
puis calculer les champs en parallèle (`concurrent.futures.ProcessPoolExecutor`, un processus par
cœur moins un), en dernier lieu seulement dégrader la résolution — et alors rejouer les tests
d'étanchéité de la phase 3 à la nouvelle résolution.

La carte graphique du traceur (RTX 3060) n'accélère pas ces calculs : `MCP_Geometric` tourne
sur le processeur. Ne pas chercher à porter les champs de temps sur la carte graphique tant que
K9 est tenu avec le calcul en parallèle.

## Critères d'acceptation

1. Tous les tests de 5.1 à 5.7 passent.
2. Validation 5.6 faite sur au moins une carte de forêt et une de sprint ; les deux seuils
   « établi » sont atteints, ou chaque écart est expliqué au registre avec la décision prise.
3. Budget mesuré sur le PC du traceur : une analyse de jambe en moins de 3 s à froid, moins de
   0,3 s quand les deux champs sont en cache ; préparation extrapolée ≤ 3 min par carte.
4. Le traceur utilise l'inspecteur sur dix jambes de son choix (cinq en ville, cinq en forêt) et
   note pour chacune si les itinéraires affichés sont ceux qu'il attend. Les désaccords deviennent
   des tests ou des entrées « à vérifier » du registre.

## Hors périmètre

- Relief, dénivelé, solveur sensible à la pente (phase 10).
- Verdict de conformité et intérêt d'une jambe (phase 6).
- Calage des vitesses sur des traces GPS (phase 9) : ici les vitesses sont celles de la norme.
- Structures à plusieurs niveaux : un itinéraire qui les traverse est signalé (`flags`), pas corrigé.

## Pièges

- Jamais de `np.inf` remplacé par un « grand nombre » : le prototype le faisait, et ses itinéraires
  traversaient les murs en payant cher. Une cellule interdite reste infinie.
- La pénalité de franchissement est une densité de coût sur une bande : courir **le long** d'une
  clôture, dans ses cellules, coûterait très cher ; c'est voulu (on court à côté), mais un point de
  départ ou d'arrivée ne doit jamais tomber dans la bande — les `stand_xy` sont décalés d'une
  cellule si besoin.
- `Ta + Tb` n'a de sens que si les deux champs sont calculés avec le **même** coût.
- Les deux champs d'une jambe doivent couvrir la même fenêtre : prendre l'intersection.
- Une ligne « suivie » demande direction et proximité ; sans le test de direction, chaque chemin
  traversé compterait comme main courante.
- Ne pas afficher de temps « à la seconde » comme une vérité : tant que les vitesses ne sont pas
  calées (phase 9), ce sont des temps relatifs, bons pour comparer deux itinéraires.
