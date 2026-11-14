# Phase 6 — Le moteur « jambes d'abord »

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

## But

Construire le moteur v2 sur le principe fondateur : **on choisit d'abord les interpostes, les postes
en découlent**.

1. *Conformité* : dire si une jambe est permise pour une couleur, et sinon pourquoi.
2. *Intérêt* : parmi les jambes permises, dire lesquelles valent d'être courues, selon le format.
3. *Catalogue* : toutes les jambes conformes d'une carte pour un niveau, avec leur intérêt.
4. *Assemblage* : enchaîner des jambes en circuits qui respectent les règles de circuit.
5. *Jugement* : comparer à l'aveugle avec le moteur v1. C'est le traceur qui tranche (K7).

## Ce que le traceur verra

- Un mode **pas à pas** : depuis un poste, « les meilleures jambes d'ici », classées, chacune avec
  ses itinéraires et sa justification ; il construit son circuit jambe après jambe.
- Un mode **propositions** : trois circuits complets différents pour un brief (couleur, format,
  départ, arrivée, postes imposés) ; pour chaque poste, « un autre poste ici ».
- Pour toute jambe refusée : le motif, avec la règle FFCO citée.
- Un écran de **comparaison à l'aveugle** : deux circuits sans étiquette, il choisit.

## Prérequis

- Phase 5 terminée, validation 5.6 comprise.
- Lire `A2_referentiel_niveaux_ffco.md` §3 à §6 et `03_REGLES_DE_TRAVAIL.md` §6.

## Contexte vérifié

- « Les parcours entre postes sont les parties les plus importantes d'un parcours d'orientation et
  déterminent sa qualité. […] Il est préférable qu'un circuit d'orientation ait quelques très bons
  parcours entre postes dont les liaisons sont conçues pour les mettre en valeur plutôt qu'un grand
  nombre de parcours entre postes de qualité moyenne. » (TP §3.4.1, p. 8)
- « Un parcours plaisant est un parcours varié, c'est-à-dire qui présente des changements de
  direction, de longueurs différentes entre les postes et qui impose d'utiliser les diverses
  techniques d'orientation. » (TP §2.3.3, p. 3)
- « L'objectif principal d'un poste de contrôle est de marquer le début et la fin d'un parcours
  entre postes. » (TP §3.5.3, p. 9)
- Distances minimales entre postes : RTS p. 8/12 (A2 §5). Angles : TP §3.5.5, p. 10. Arrivée :
  « du dernier poste vers l'arrivée, […] un itinéraire balisé et obligatoire » (TP §3.6, p. 10).
- Le moteur v1 fait l'inverse : il tire des postes puis note le dessin obtenu ; son interface
  demande 1,5 fois le nombre de postes voulu et les propose un par un (`App.jsx` l.979 et
  l.1066-1103), ce qui défait tout enchaînement.
- Les temps sont proportionnels à l'allure : un seul jeu de champs de temps par carte (phase 5)
  sert toutes les couleurs.

## Étapes

### 6.1 — Conformité d'une jambe

**Fichier** : `aitraceur/legs/fit.py`.

```python
@dataclass(frozen=True)
class Violation:
    param: str                 # paramètre de LevelSpec en cause
    measured: object; allowed: object
    detail_fr: str             # "210 m hors ligne ; 100 m au plus en bleu (Traçage – Aspects pratiques, p. 9)"

@dataclass(frozen=True)
class Conformity:
    ok: bool
    violations: tuple[Violation, ...]
    reference_route: int | str      # indice de l'itinéraire physique retenu, ou "L1" / "L1L2L3" (itinéraire conduit)

def leg_conformity(leg: LegFacts, a: Site, b: Site, spec: LevelSpec, lines: LineIndex) -> Conformity: ...
def min_color(leg: LegFacts, a: Site, b: Site, fmt: Format, lines: LineIndex) -> Color | None: ...
```

**Itinéraire de référence** du niveau : l'itinéraire conduit s'il existe et que le niveau est vert
ou bleu ; sinon l'itinéraire physique le plus rapide.

Règles de forêt (chaque règle lit un paramètre de `LevelSpec` ; valeur `null` = règle sautée) :

| Paramètre | Test |
|-----------|------|
| sites | `site_verdict(b, spec)` admis (et `a`, sauf si c'est le départ). |
| `speed_classes_allowed` | au plus 10 % de la longueur de l'itinéraire de référence dans une classe non permise. |
| `handrail_classes`, `max_offline_m` | sur l'itinéraire de référence, chaque tronçon hors ligne (`offline_runs(classes, open_counts)`) est ≤ la limite. Bleu : ≤ 100 m ; toléré jusqu'à 200 m si `all_open` et `ends_on` non nul. Vert : aucun tronçon de plus de 10 m, donc l'itinéraire conduit `L1` doit exister. |
| `route_choice = aucun` (vert) | `guided_alt_ratio["L1"]` est `None` ou ≥ 1,5. |
| `route_choice = sur lignes` (bleu) | tout itinéraire physique à moins de `choice_eps` du plus rapide respecte lui aussi la limite hors ligne. |
| `route_choice = simple` (jaune) | `n_choices ≤ 2`. |
| `max_unmarked_turns_leg` (vert) | `n_turns` de l'itinéraire de référence ≤ la limite. |
| `attack_max_m` | `attack_dist_m[attack_max_obviousness]` ≤ la limite ; satisfait d'office si `b` est sur une ligne permise avec une évidence ≤ 2 (le poste est son propre point d'attaque). |
| `catching` exigée à D | une ligne d'arrêt d'une classe permise à ≤ D ; satisfait d'office si `b` est sur une ligne. |
| `handrail_fastest_forbidden` (violet, noir) | refus si l'itinéraire le plus rapide suit une ligne L1 sur 80 % ou plus de sa longueur. |

Règles de sprint :

| Paramètre | Test |
|-----------|------|
| sites | `site_verdict`, dont `site_max_similar_nearby`. |
| `max_turns_leg` | `n_turns` de l'itinéraire le plus rapide ≤ la limite. |
| `barrier_at_control = interdit` | `leg.barrier_at_control` faux. |
| `multi_level` | aucun itinéraire à moins de `choice_eps` ne porte le drapeau `multi_niveaux`. |

`detail_fr` nomme la mesure, la limite et la source du paramètre (citation ou « choix du plan »).

**Tests** (`test_fit.py`) — cartes `croix()`, `bois()`, `village()`, et jambes de la phase 5 :

| Jambe | vert | bleu | jaune | orange |
|-------|------|------|-------|--------|
| `croix()` (100, 200) → croisement (300, 200) | conforme | conforme | conforme | conforme |
| `croix()` (100, 200) → (300, 100), deux chemins, un changement de direction sans poste | conforme (1 toléré) | conforme | conforme | conforme |
| `bois()` croisement → coin de CLAIRIERE (400, 250) | refus : site | conforme si le tronçon hors ligne ≤ 100 m, sinon refus `max_offline_m` (valeur à calculer dans le test) | conforme | conforme |
| `bois()` croisement → ROCHER_2 (350, 260), 78 m du croisement | refus : site | refus : site | conforme (point d'attaque = croisement, à moins de 150 m) | conforme |
| `bois()` (20, 390) → ROCHER_1 (150, 300) en pleine zone lente | refus | refus | refus `attack_max_m` | refus `attack_max_m` ou `catching` |

`min_color` de la première jambe = vert ; de la jambe vers ROCHER_2 = jaune. Sprint, sur le « pâté
de maisons » : la jambe ouest → est a 2 changements de direction ou plus par itinéraire ; avec trois
pâtés en enfilade (6 changements), refus en bleu (`max_turns_leg` 3), refus en jaune (5), conforme en
orange. Carte « piège » de la phase 5 : refus `barrier_at_control` en bleu et jaune, conforme en
orange. Chaque refus porte un `detail_fr` contenant la mesure et la source.

### 6.2 — Intérêt d'une jambe

**Fichier** : `aitraceur/legs/interest.py`.

```python
@dataclass(frozen=True)
class Interest:
    score: float                         # 0..1
    parts: Mapping[str, float]           # composantes, chacune 0..1
    reasons_fr: tuple[str, ...]          # "deux itinéraires à 4 % d'écart, séparés de 60 m"

def leg_interest(leg: LegFacts, a: Site, b: Site, spec: LevelSpec, config: InterestConfig) -> Interest: ...
```

Composantes (définitions dans `InterestConfig`, `source="implementation"` ; la colonne « fondement »
dit pourquoi la composante existe) :

| Composante | Calcul | Fondement |
|------------|--------|-----------|
| `choix` | 0 s'il n'y a qu'un itinéraire ; sinon `1 − spread ÷ choice_eps`, multiplié par un facteur de séparation (1 si les itinéraires s'écartent d'au moins 15 % de la longueur de la jambe, proportionnel en dessous). | TP §3.8 ; GC p. 3 (longue distance, sprint). |
| `lecture` | `1 −` (plus long tronçon suivi sur une même ligne L1 ÷ longueur). | TP §3.7 : « Des itinéraires ne nécessitant aucune lecture de carte […] sont à éviter ». |
| `approche` | moyenne de (évidence de `b` ÷ évidence maximale du niveau) et de (`attack_dist_m` ÷ `attack_max_m`, plafonné à 1). | GC p. 3 (moyenne distance : « recherche de postes ») ; TP §3.9. |
| `clarte` | 1 si `b` est à un point de décision (jonction, croisement, changement de ligne) ; 0,5 sinon. | MF T1 ; TAP p. 8 et p. 10. |
| `variete` | nombre de types de lignes et de classes de vitesse empruntés, ramené à 0..1 (1 à partir de 3). | MF T5 ; TP §2.3.3. |
| `virages` (sprint) | `n_turns ÷ max_turns_leg` (plafonné à 1 ; S3 : `n_turns ÷ 6`). | MF p. 10-13. |
| `obstacles` (sprint) | franchissements et contournements d'infranchissables sur l'itinéraire, ramenés à 0..1 (1 à partir de 2) ; compté 0 en S1. | MF p. 12-13. |

Poids de départ, par niveau et par accent du format (les poids d'une ligne somment à 1) :

| Niveau | Accent | choix | lecture | approche | clarté | variété | virages | obstacles |
|--------|--------|-------|---------|----------|--------|---------|---------|-----------|
| vert, bleu (forêt) | tous | 0 (vert) ; 0,2 (bleu) | 0 | 0 | 0,6 ; 0,4 | 0,4 | — | — |
| jaune à noir | `choix` (LD) | 0,5 | 0,3 | 0,2 | 0 | 0 | — | — |
| jaune à noir | `recherche_de_postes` (MD) | 0,2 | 0,3 | 0,5 | 0 | 0 | — | — |
| sprint | `choix_sous_pression` | 0,6 | 0 | 0 | 0 | 0 | 0,2 | 0,2 |

Ces poids sont un point de départ **gelé** pour toute la phase. Ils ne se règlent pas à l'œil : la
phase 9 les remplace par un modèle appris, et tout changement d'ici là passe par le banc (règles de
travail §6, point 1).

**Tests** (`test_interest.py`) : monotonie plutôt que valeurs — à mesures égales par ailleurs, une
jambe à deux itinéraires proches a un `choix` supérieur à une jambe à itinéraire unique ; `choix`
décroît quand `spread` croît ; en moyenne distance, un poste d'évidence 4 avec point d'attaque à
180 m a une `approche` supérieure à un poste d'évidence 2 avec point d'attaque à 20 m ; les poids de
chaque ligne somment à 1 ; `reasons_fr` n'est jamais vide.

### 6.3 — Le catalogue de jambes

**Fichier** : `aitraceur/legs/catalog.py`.

```python
@dataclass(frozen=True)
class LegEntry:
    a: int; b: int                         # indices dans LegCatalog.sites
    time_s: float; route_m: float; straight_m: float
    effort_m: float                        # route_m + 10 × dénivelé positif (0 avant la phase 10)
    interest: float; reasons_fr: tuple[str, ...]
    exit_bearing_deg: float; approach_bearing_deg: float
    n_midleg_line_changes: int; has_catching: bool

@dataclass
class LegCatalog:
    spec: LevelSpec
    sites: tuple[Site, ...]                # sites admis au niveau, plus départ, arrivée, postes imposés
    legs: Mapping[tuple[int, int], LegEntry]      # jambes conformes seulement
    examined: int
    refused: Mapping[str, int]             # paramètre → nombre de jambes refusées pour ce motif

def build_catalog(ctx: LegContext, spec: LevelSpec, *, start, finish, required=(), seed: int = 0,
                  config: CatalogConfig = CatalogConfig(), progress=None) -> LegCatalog: ...
```

Construction :

1. **Sites** : ceux que `site_verdict` admet, plus départ, arrivée et postes imposés (un poste imposé
   non admis est gardé, avec un avertissement).
2. **Champs** : un champ de temps par site (`FieldStore`), calculé une fois par carte.
3. **Paires candidates** : distance à vol d'oiseau dans la fourchette `leg_length_m` du niveau ;
   temps fini ; détour ≤ 3.
4. **Tirage stratifié** : par site d'origine, répartir les candidates en 8 secteurs de direction ×
   3 tiers de longueur et en tirer au plus `per_stratum` (1 par défaut, soit 24 par site) avec le
   générateur issu de `seed`. Sans ce tirage, 300 sites donneraient des dizaines de milliers
   d'analyses ; avec lui, environ 3 600.
5. **Analyse** : `analyze_leg` une fois par paire (les itinéraires servent aux deux sens), puis
   `leg_conformity` et `leg_interest` dans chaque sens. Les analyses se répartissent sur
   `ProcessPoolExecutor` (cœurs − 1).
6. **Résultat** : seules les jambes conformes entrent dans `legs` ; les refus sont comptés par
   paramètre.

Cache : `{DATA_DIR}/maps/{map_id}/catalog_<clé>.pkl.gz` ; la clé dépend du terrain, du niveau (avec
les réponses de calage), du format, de `seed` et des configurations.

`refused` est un diagnostic de premier ordre : « 3 600 jambes examinées, 410 conformes au bleu ;
refus : 1 950 hors ligne, 700 sans ligne d'arrêt, 540 site » dit en une ligne si la carte se prête au
niveau demandé.

**Tests** (`test_catalog.py`) : sur `bois()` en vert, le catalogue ne contient que des jambes entre
sites posés sur les chemins ; en jaune il contient une jambe croisement → ROCHER_2 ; deux
constructions avec la même graine sont identiques ; avec deux graines différentes, les jambes
communes ont les mêmes valeurs ; `sum(refused.values()) + len(legs) == 2 × examined` à l'unité près
(deux sens par paire).

### 6.4 — Circuit et brief

**Fichier** : `aitraceur/courses/model.py`.

```python
@dataclass(frozen=True)
class CourseBrief:
    color: Color; fmt: Format
    start_id: str; finish_id: str
    effort_km: tuple[float, float] | None = None      # défaut : fourchette du Guide (A2 §6)
    n_controls: tuple[int, int] | None = None
    required_ids: tuple[str, ...] = ()                # à passer dans cet ordre
    avoid_ids: tuple[str, ...] = ()
    max_cluster: int = 2                              # K2
    max_crossings: int | None = None                  # défaut : 1 en forêt, 3 en sprint
    n_proposals: int = 3
    seed: int = 0

@dataclass(frozen=True)
class Course:
    site_ids: tuple[str, ...]                         # départ, postes, arrivée
    legs: tuple[LegEntry, ...]
    effort_m: float; time_s: float
    score: float; parts: Mapping[str, float]
    warnings: tuple[str, ...]
```

### 6.5 — Règles de circuit

**Fichier** : `aitraceur/courses/constraints.py`.

Contraintes **dures** (un circuit qui en viole une n'est jamais proposé) :

| Règle | Test | Source |
|-------|------|--------|
| Jambes conformes | toutes les jambes sont dans le catalogue | A2 |
| Distance entre postes, forêt | toute paire de postes : ≥ 30 m à vol d'oiseau ; ≥ 60 m si même `label_fr` | RTS p. 8/12 |
| Distance entre postes, sprint | toute paire : ≥ 15 m à vol d'oiseau **et** ≥ 25 m en distance de course (longueur de l'itinéraire le plus rapide) | RTS p. 8/12 |
| Pas de retour sur ses pas | au poste, le cap de sortie ne fait pas moins de 30° avec l'inverse du cap d'approche (caps des itinéraires, pas des segments) | TP §3.5.5, p. 10 |
| Amas | au plus `max_cluster` postes dans un rayon de 60 m (sprint) ou 150 m (forêt) | K2 ; plan |
| Croisements | au plus `max_crossings` croisements entre itinéraires de jambes non consécutives | TP p. 17 ; valeur : plan |
| Longueur | effort total dans `effort_km` | GC p. 4-5 |
| Temps | temps estimé ≤ `max_time_min` quand le niveau en a un | RTS §3.2.1 |
| Changements de ligne (vert) | somme des `n_midleg_line_changes` ≤ 2 | MF T3 |
| Lignes d'arrêt (violet) | au moins un tiers des postes sans ligne d'arrêt | MF T13 ; proportion : plan |
| Postes imposés | présents, dans l'ordre | brief |

Termes **souples** (la note d'un circuit, 0..1) :

| Terme | Poids de départ | Calcul | Source |
|-------|-----------------|--------|--------|
| `sommet` | 0,45 | moyenne de l'intérêt du meilleur tiers des jambes | TP §3.4.1 |
| `fond` | 0,20 | moyenne de l'intérêt de toutes les jambes | — |
| `variete` | 0,20 | moitié : coefficient de variation des longueurs de jambe ÷ 0,5 (plafonné à 1) ; moitié : part des enchaînements dont le changement de cap atteint 45° | TP §2.3.3 |
| `couverture` | 0,15 | K4 : part des 16 cases de la zone utile (enveloppe des sites admis) contenant un poste | constat du traceur |

L'arrivée : la liaison dernier poste → arrivée est un itinéraire balisé (TP §3.6) ; elle doit
exister, n'est pas soumise à la conformité, et ne compte pas dans l'intérêt.

**Tests** (`test_constraints.py`) : un circuit avec deux postes à 20 m est refusé (30 m) ; deux
rochers à 45 m sont refusés (60 m, même nature), un rocher et une jonction à 45 m sont acceptés ;
en sprint, deux postes à 18 m à vol d'oiseau de part et d'autre d'un mur (120 m de course) sont
acceptés, deux postes à 18 m sans obstacle (18 m de course) sont refusés ; un aller-retour sur le
même chemin est refusé pour retour sur ses pas ; quatre postes dans un cercle de 60 m sont refusés.

### 6.6 — Assemblage

**Fichier** : `aitraceur/courses/assemble.py`.

```python
def assemble(catalog: LegCatalog, brief: CourseBrief, config: AssembleConfig = AssembleConfig()) -> list[Course]: ...

@dataclass(frozen=True)
class AssembleConfig:
    beam_width: int = 200
    expand: int = 12                 # successeurs gardés par état
    temperature: float = 0.0         # 0 = toujours les meilleurs ; > 0 = tirage (expérience 6.9)
    max_similarity: float = 0.6      # entre deux propositions (indice de Jaccard des postes)
```

Recherche en faisceau, déterministe pour une graine :

1. **État** : dernier site, ensemble des sites visités, effort cumulé, jambes, compteurs des règles
   (amas, croisements, changements de ligne), note partielle.
2. **Successeurs** d'un état : les jambes du catalogue partant du dernier site vers un site non
   visité, compatibles avec toutes les contraintes dures **incrémentales** (distances aux postes déjà
   posés — matrice de compatibilité précalculée —, retour sur ses pas, amas, croisements, ordre des
   postes imposés) et telles que l'arrivée reste atteignable sans dépasser la borne haute de
   longueur.
3. **Choix** : classer les successeurs par `intérêt + bonus de nouveauté` (0,1 si la jambe mène dans
   une case de la grille 4 × 4 encore vide) ; en garder `expand`, au plus deux par secteur de
   direction. Si `temperature > 0`, tirer `expand` successeurs avec une probabilité proportionnelle
   à `exp(valeur ÷ temperature)`.
4. **Faisceau** : garder les `beam_width` meilleurs états par note partielle, en imposant qu'aucun
   couple (dernier site, tranche d'effort de 250 m) ne dépasse 5 états (diversité).
5. **Fin** : un état dont l'effort, liaison d'arrivée comprise, entre dans la fourchette donne un
   circuit candidat ; on vérifie alors les contraintes dures globales et on calcule la note.
6. **Sortie** : les `n_proposals` circuits de meilleure note deux à deux assez différents
   (`max_similarity`). Aucun circuit valable : renvoyer une liste vide **et** le motif dominant
   (« aucune jambe conforme ne quitte le départ », « longueur minimale inatteignable : 2,1 km au
   plus »).

**Tests** (`test_assemble.py`) sur des catalogues construits à la main (graphes de 8 à 12 sites,
sans carte) : le circuit optimal connu est trouvé ; une contrainte de distance élimine le circuit
qui la viole ; les postes imposés sont respectés dans l'ordre ; même graine → mêmes circuits ; trois
propositions demandées → similarité deux à deux ≤ 0,6 ; catalogue sans jambe au départ → liste vide
et motif. Sur `bois()` en jaune, moyenne distance réduite (0,8 à 1,2 km), départ et arrivée au
croisement : au moins un circuit, toutes contraintes vérifiées par une fonction de contrôle
indépendante de l'assembleur.

### 6.7 — Finition et retouches

**Fichier** : `aitraceur/courses/polish.py`.

```python
def polish(course: Course, catalog: LegCatalog, brief: CourseBrief) -> Course:
    """Pour chaque poste : essayer chaque site de remplacement dont les deux jambes adjacentes
    existent au catalogue ; accepter si toutes les contraintes tiennent et que la note monte.
    Trois passes au plus."""

def alternatives_at(course: Course, index: int, catalog, brief, k: int = 5) -> list[Course]:
    """« Un autre poste ici » : les k meilleurs circuits obtenus en remplaçant ce seul poste."""

def best_legs_from(catalog: LegCatalog, site_id: str, visited: Collection[str], k: int = 8) -> list[LegEntry]:
    """Mode pas à pas : les meilleures jambes conformes au départ d'un site, compatibles avec les
    postes déjà posés."""
```

**Tests** : `polish` ne dégrade jamais la note ni ne viole de contrainte ; `alternatives_at` ne
change qu'un poste ; `best_legs_from` exclut les sites visités et ceux à moins de 30 m d'un poste
posé.

### 6.8 — API et interface

**Fichiers** : `backend/src/api/v2/courses.py` ; `frontend/src/components/v2/StepByStepPanel.jsx`,
`CourseProposals.jsx`, `LegCard.jsx`.

| Route | Rôle |
|-------|------|
| `POST /api/v2/maps/{map_id}/catalog` | Corps `{color, format, start, finish, required}`. Tâche de fond avec avancement. Réponse finale : nombre de sites admis, de jambes examinées, conformes, refus par motif. |
| `GET /api/v2/maps/{map_id}/legs/from/{site_id}?…` | Mode pas à pas (`best_legs_from`). |
| `POST /api/v2/maps/{map_id}/courses` | Corps = `CourseBrief`. Tâche de fond. Réponse : propositions, chacune avec ses jambes (itinéraires en WGS84, `reasons_fr`), sa note détaillée, ses avertissements. |
| `POST /api/v2/maps/{map_id}/courses/alternatives` | « Un autre poste ici ». |
| `POST /api/v2/maps/{map_id}/courses/check` | Vérifie un circuit **dessiné par le traceur** : conformité de chaque jambe et règles de circuit, avec motifs. |

Interface :

- Un commutateur « Moteur : actuel / nouveau » tant que les deux coexistent.
- **Pas à pas** : clic sur le dernier poste → huit jambes proposées, tracées sur la carte ; une carte
  de jambe (`LegCard`) par proposition : longueur, temps, « deux itinéraires à 4 % », « point
  d'attaque : jonction à 60 m », intérêt ; clic → le poste est ajouté.
- **Propositions** : trois circuits en onglets ; liste des jambes ; « un autre poste ici » ;
  « verrouiller ce poste » (il devient imposé au prochain calcul) ; « adopter » → le circuit passe
  dans l'éditeur existant de l'application, où il se retouche et s'exporte comme aujourd'hui.
- **Vérifier mon circuit** : le traceur dessine, l'application juge chaque jambe pour la couleur
  choisie et cite la règle en cas de refus.
- Le diagnostic `refused` s'affiche après la construction du catalogue.

**Tests** : client HTTP sur `bois()` — catalogue en jaune puis `courses` → au moins une
proposition ; `check` d'un circuit dont une jambe mène à ROCHER_1 depuis (20, 390) → cette jambe
est signalée avec son motif. Vitest : `LegCard` affiche les motifs reçus.

### 6.9 — Expérience : tirage ou pas

Expérience **réversible**, derrière le réglage `AssembleConfig.temperature`.

- Protocole : sur chaque carte d'essai × 2 briefs × 5 graines, comparer `temperature` 0 et 0,3 :
  note du meilleur circuit, similarité moyenne entre les trois propositions, K2, K3, K4, durée.
- Décision écrite **avant** de regarder les résultats : on adopte 0,3 si la similarité moyenne
  baisse d'au moins 0,1 sans que la meilleure note baisse de plus de 0,02 ; sinon on garde 0.
- Consigner au registre, résultat et décision.

### 6.10 — Le banc du moteur v2

**Fichier** : `aitraceur/evalbench/run.py` (sous-commande `v2`).

`python -m src.aitraceur.evalbench.run v2 --packages <dossier> --briefs briefs.json --seeds 0 1 2 3 4 --out ../runs/p6_v2`

Pour chaque carte × brief × graine : K1 (doit valoir 0), K2, K3, K4, K5 (deux exécutions identiques
octet pour octet), K6 (part des jambes conformes : 100 % par construction — toute autre valeur est
un défaut), durées de catalogue et d'assemblage (K9). Tableau comparé à la référence v1 de la
phase 3 dans `docs/plan/mesures/P6_v2_contre_v1.md`.

### 6.11 — Le juge : comparaison à l'aveugle (K7)

**Fichiers** : `frontend/src/components/v2/BlindCompare.jsx`, `backend/src/api/v2/blind.py`.

1. Préparer au moins 20 comparaisons sur au moins 4 cartes (2 de sprint, 2 de forêt), couleurs
   variées : pour chaque (carte, brief), un circuit du moteur v1 (banc de la phase 0, avec le pont)
   et un du moteur v2, mêmes départ, arrivée et longueur visée.
2. L'écran montre « circuit A » et « circuit B » côte à côte, ordre tiré au hasard et **consigné
   côté serveur seulement**, sans aucun indice du moteur. Le traceur répond : A, B, ou « aucun des
   deux n'est acceptable », et peut cocher un motif (amas, croisements, jambes sans intérêt, niveau
   inadapté, carte mal exploitée, autre).
3. Réponses dans `{DATA_DIR}/prefs/blind_v1_v2.jsonl`. Résultat : part des comparaisons gagnées par
   v2 parmi celles où un circuit a été choisi, et nombre de « aucun des deux ».

**Porte** : K7 ≥ 70 % et moins d'un quart de « aucun des deux ». Sinon : lire les défaites une à une
avec le traceur, classer les causes, corriger (une cause = une correction mesurée), refaire une
série avec de **nouvelles** graines. Le moteur v1 reste le moteur par défaut tant que la porte n'est
pas franchie.

### 6.12 — Garder la trace des choix du traceur

**Fichier** : `aitraceur/learn/prefs.py`. Dès cette phase, chaque geste du traceur est consigné
(fichier `{DATA_DIR}/prefs/events.jsonl`, ajout seul) : proposition adoptée, poste remplacé (ancien,
nouveau), jambe choisie en pas à pas parmi celles proposées, circuit vérifié. Chaque événement
porte `map_id`, couleur, format, les identifiants de sites et la version du moteur. C'est la matière
de la phase 9 ; rien n'est appris ici.

### 6.13 — Ménage

Après la porte 6.11 : supprimer `backend/src/aitraceur_proto/` et `backend/tests/aitraceur_proto/`
(vérifier d'abord, par `grep`, qu'aucun import ne subsiste) ; poser auparavant l'étiquette git
`prototype-2026-03` sur le commit qui les contient encore. Le moteur v2 devient le moteur par
défaut de l'interface ; le moteur v1 reste accessible par le commutateur jusqu'à la phase 11.

## Critères d'acceptation

1. Tous les tests de 6.1 à 6.8 passent.
2. Banc v2 : K1 = 0, K5 = 100 %, K6 = 100 % sur toutes les cartes ; K2 ≤ 2 ; K3 et K4 meilleurs que
   la référence v1, ou l'écart est expliqué.
3. K9 sur le PC du traceur : catalogue d'un niveau ≤ 3 min (puis en cache) ; trois propositions
   ≤ 20 s.
4. Porte K7 franchie (6.11).
5. Le traceur a construit au moins un circuit en mode pas à pas et un en mode propositions sur une
   carte réelle, et vérifié un de ses anciens circuits avec « Vérifier mon circuit ». Ses remarques
   sont au compte rendu.
6. Expérience 6.9 conclue et consignée.

## Hors périmètre

- Rapport de contrôle complet et explications rédigées (phase 7).
- Apprentissage des poids (phase 9).
- Dénivelé (phase 10) : `effort_m` vaut la longueur d'itinéraire ; l'interface l'affiche.
- Circuits multiples partageant des postes, relais, boucles papillon : après le plan.

## Pièges

- Ne jamais « réparer » un circuit en relâchant une contrainte dure en silence. S'il n'y a pas de
  circuit, dire pourquoi : c'est une information sur la carte ou sur le brief.
- La conformité se juge sur des **itinéraires**, la distance minimale entre postes sur des positions
  d'éléments (`xy`), la distance de course du sprint sur des itinéraires entre `stand_xy`.
- Le tirage stratifié du catalogue dépend de la graine : pour comparer deux réglages, garder la
  même graine de catalogue.
- Un poste imposé peut rendre le brief infaisable (aucune jambe conforme ne le relie) : le dire
  tout de suite, à la construction du catalogue.
- Ne pas réintroduire l'ancien flux « 1,5 fois le nombre de postes, à valider un par un » : il
  détruit l'enchaînement des jambes. Les retouches passent par « un autre poste ici », qui
  recalcule les deux jambes voisines.
- La note d'un circuit ne se compare qu'entre circuits du même brief.
