# Phase 0 — Socle et mesure

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

## But

Poser le terrain de travail : un dépôt propre, des tests qui tournent, un emplacement vide pour le
moteur v2, et un **banc d'essai** qui chiffre les défauts du moteur actuel de façon reproductible.
Sans ce banc, aucune phase suivante ne peut prouver qu'elle améliore quoi que ce soit.

## Ce que le traceur verra

Rien de nouveau dans l'application. Un tableau `docs/plan/mesures/P0_baseline.md` qui chiffre, sur
ses propres cartes, les amas de postes, les croisements, la couverture de la carte et les postes en
zone interdite produits aujourd'hui.

## Prérequis

- Accès au dépôt local du traceur, avec ses cartes `.ocd` d'essai hors dépôt.
- Les trois services démarrent (`start_all.bat`).

## Contexte vérifié

- `main` = `e321816` ; `origin/arena/01a100b3-aitraceur` = `60b624a`, 5 commits d'avance, uniquement
  du frontend (étapes 14c–14d). Fusion en avance rapide possible.
- 198 fonctions de test backend, 47 tests frontend. `backend/pytest.ini` : `asyncio_mode = auto`.
- `backend/requirements.txt` mêle exécution et entraînement (torch, torchvision, xgboost) ;
  `shapely`, `networkx`, `Pillow`, `sentence-transformers` sont importés mais non déclarés.
- Forêt : `_circuit_impl(body)` (`main.py` l.2111) lit `ga_seed` (l.2168). Sprint :
  `_sprint_impl(task_id, body)` (l.4023) ne lit aucune graine.
- `.gitignore` ignore `*.gz` : les fichiers de test du dépôt doivent être en `.json` simple.
- Le service de tuiles garde sur disque `uploads/<mapId>.ocd` et `renders/<mapId>.png` : un
  `map_id` capturé reste valable tant que ces dossiers ne sont pas vidés.

## Étapes

### 0.1 — Point de départ git

Le traceur a seulement glissé le dossier du plan dans `docs/plan/` ; tout le reste est fait ici, par
Claude Code (le traceur l'autorise en lançant la phase 0) :

1. `git status` : si des fichiers modifiés ou nouveaux existent **en dehors** de `docs/plan/`,
   s'arrêter et demander.
2. Mettre `main` à jour et y intégrer les étapes 14c–14d, en avance rapide seulement :
   ```bash
   git switch main && git pull && git fetch origin
   git merge --ff-only origin/arena/01a100b3-aitraceur
   git tag avant-plan-2026-11
   ```
   « Already up to date » convient. Si l'avance rapide est refusée, s'arrêter et demander.
3. Enregistrer le plan sur `main` : `git add docs/plan` puis
   `git commit -m "docs: plan de refondation 2026-11"`.
4. Créer la branche `plan/p0-socle` (règles §1, point 4).

**Test** : `cd frontend && npm test` → 47 tests passent.

### 0.2 — Installer le plan dans le dépôt

- Vérifier que `docs/plan/` est complet : 20 fichiers `.md` (`00` à `21`, `A1` à `A4`) et le dossier
  `mesures_2026-11/`. S'il en manque, s'arrêter et demander.
- Créer `docs/plan/REGISTRE.md` à partir de `A3_registre_etabli_refute.md` (même contenu ; c'est ce
  fichier qui vivra).
- Créer `docs/plan/comptes-rendus/` et `docs/plan/mesures/` (avec un `.gitkeep`).
- Modifier `CLAUDE.md` comme indiqué dans `03_REGLES_DE_TRAVAIL.md` §10.1.
- Créer la commande `/phase` et le sous-agent `verificateur` (règles §10.2 et §10.3 ; raccourcis
  facultatifs : le traceur peut aussi lancer chaque phase par « Exécute docs/plan/<fichier> »).
- Ajouter à `.gitignore` : `runs/`, `backend/data/local/`, `captures/`.

### 0.3 — Dépendances et ligne de base des tests

1. Écrire `backend/tools/check_imports.py` : parcourt `backend/src/**/*.py` avec `ast`, liste les
   modules tiers importés (hors bibliothèque standard et hors `src.`), et les compare aux paquets
   déclarés. Sortie : un tableau `module | fichiers | déclaré oui/non | import protégé par try oui/non`.
2. Scinder les dépendances :
   - `backend/requirements.txt` : ce qu'il faut pour lancer le backend et les tests. Y ajouter au
     minimum `shapely>=2.0`, `networkx`, `Pillow`, `scipy` (aujourd'hui rangé à tort sous
     « entraînement »).
   - `backend/requirements-train.txt` : `torch`, `torchvision`, `xgboost`, `opencv-python`
     (entraînement du CNN uniquement).
   - `backend/requirements-assistant.txt` : `sentence-transformers`, `chromadb` et tout ce que
     `check_imports.py` attribue au seul dossier `knowledge_base/` (sera revu en phase 8).
3. Dans un environnement virtuel neuf : `pip install -r backend/requirements.txt`, puis
   `cd backend && python -m pytest tests -q`. Noter le résultat exact (passés, échoués, erreurs).
   Ne **rien** corriger à cette étape : c'est la ligne de base. Les échecs préexistants vont au
   registre, rubrique « À vérifier ».

**Critère** : les tests démarrent (plus d'erreur d'import à la collecte) ; le décompte est écrit dans
le compte rendu.

### 0.4 — Libérer le nom `aitraceur`

Le prototype non branché (constat C1) garde ses tests mais change de nom.

```bash
git mv backend/src/aitraceur backend/src/aitraceur_proto
git mv backend/tests/aitraceur backend/tests/aitraceur_proto
```

- Remplacer `src.aitraceur.` par `src.aitraceur_proto.` dans `backend/tests/aitraceur_proto/` et
  dans `backend/scripts/run_generator.py`, `backend/scripts/visualize_leg.py` (vérifier par
  `grep -rn "aitraceur" backend/scripts backend/tests`). Les imports internes du paquet sont
  relatifs : rien à changer dedans.
- Ajouter en tête de `backend/src/aitraceur_proto/__init__.py` :
  `"""PROTOTYPE GELÉ (mars 2026). Ne pas modifier, ne pas importer. Supprimé en phase 6 du plan."""`
- Mettre à jour les mentions du README et d'`ARCHITECTURE.md`.

**Test** : `python -m pytest tests/aitraceur_proto -q` donne le même résultat qu'en 0.3.

### 0.5 — Squelette du moteur v2 et tests d'architecture

Créer `backend/src/aitraceur/__init__.py` (docstring : « Moteur v2 — voir docs/plan ») et les
sous-paquets vides `mapmodel`, `symbols`, `terrain`, `sites`, `levels`, `routes`, `legs`, `courses`,
`rules`, `io`, `learn`, `relief`, `evalbench`, chacun avec un `__init__.py` d'une ligne décrivant
son rôle et la phase qui le remplit.

Créer `backend/tests/aitraceur/test_architecture.py` :

| Test | Vérifie |
|------|---------|
| `test_engine_has_no_forbidden_imports` | Aucun fichier de `backend/src/aitraceur/` n'importe `fastapi`, `sqlalchemy`, `requests`, `src.services`, `src.api`, `src.main`, `src.aitraceur_proto` (analyse `ast`). |
| `test_no_global_random` | Aucun appel `random.<fn>(` ni `np.random.<fn>(` hors `default_rng` / `Random(` dans `backend/src/aitraceur/`. |
| `test_no_silent_except` | Aucun `except` dont le corps est uniquement `pass` dans `backend/src/aitraceur/`. |

### 0.6 — Les indicateurs : `aitraceur/evalbench/metrics.py`

Module indépendant de tout moteur. Entrée : des points en **mètres**.

```python
@dataclass(frozen=True)
class CourseMetrics:
    n_controls: int              # postes hors départ et arrivée
    length_m: float              # somme des jambes à vol d'oiseau
    leg_min_m: float
    leg_max_m: float
    leg_cv: float                # écart-type / moyenne des longueurs de jambe
    min_pair_dist_m: float       # plus petite distance entre deux points (toutes paires, sauf la paire départ–arrivée)
    n_pairs_below_30m: int       # paires de postes à moins de 30 m (strict)
    n_pairs_below_60m: int
    crossings: int               # paires de jambes non adjacentes qui se coupent
    doglegs: int                 # postes où le changement de cap est >= 150 degrés
    max_in_radius: int           # K2 : plus grand nombre de postes dans un disque de rayon R centré sur un poste (lui compris)
    n_clustered: int             # postes ayant au moins 2 autres postes à moins de R
    coverage_4x4: float          # K4 : part des 16 cases de la zone contenant au moins un point
    hull_ratio: float            # aire de l'enveloppe convexe des points / aire de la zone
    is_loop: bool                # départ et arrivée à moins de 1 m
    forbidden_hits: int          # points strictement à l'intérieur d'un polygone interdit

def course_metrics(
    points_xy: Sequence[tuple[float, float]],   # départ, postes…, arrivée, dans l'ordre
    *,
    area_bbox: tuple[float, float, float, float],            # (xmin, ymin, xmax, ymax)
    forbidden: Sequence["shapely.Polygon"] = (),
    cluster_radius_m: float,
) -> CourseMetrics: ...

def lnglat_to_local_m(points_lnglat, center_lnglat) -> list[tuple[float, float]]:
    """Projection azimutale équidistante centrée (pyproj, +proj=aeqd). Pour les sorties du moteur v1."""
```

Définitions à respecter :

- Les amas (`max_in_radius`, `n_clustered`, `n_pairs_below_*`) ne portent que sur les postes, pas
  sur le départ ni l'arrivée.
- Deux jambes sont adjacentes si elles partagent une extrémité ; un circuit en boucle rend la
  première et la dernière adjacentes. Un croisement est une intersection de deux jambes non
  adjacentes.
- Changement de cap en un poste = angle entre le vecteur d'arrivée et le vecteur de départ
  (0° = tout droit, 180° = demi-tour).

Tests chiffrés (`backend/tests/aitraceur/test_metrics.py`) :

| Cas | Points | Attendu |
|-----|--------|---------|
| Carré | (0,0) (100,0) (100,100) (0,100) (0,0) | `n_controls=3`, `length_m=400`, `leg_cv=0`, `crossings=0`, `doglegs=0`, `is_loop=True`, `min_pair_dist_m=100` |
| Papillon | (0,0) (100,100) (100,0) (0,100) | `crossings=1`, `doglegs=0`, `is_loop=False` |
| Aller-retour | (0,0) (100,0) (10,5) (200,200) | `doglegs=1` (cap changé de 176,8° au 2ᵉ point) |
| Amas, R = 60 | départ (−200,−200) ; postes (0,0) (30,0) (0,30) (500,500) ; arrivée (700,700) | `max_in_radius=3`, `n_clustered=3`, `n_pairs_below_30m=0`, `n_pairs_below_60m=3` |
| Couverture | zone (0,0,400,400) ; points (50,50) (150,50) (350,350) | `coverage_4x4=0.1875` |
| Interdit | carré interdit (40,40)-(60,60) ; points (50,50) (100,100) | `forbidden_hits=1` |

### 0.7 — Capturer les requêtes du moteur v1

Trois petites retouches du backend, sans effet quand les variables d'environnement sont absentes.

1. **Capture.** Nouveau fichier `backend/src/api/capture.py` :

   ```python
   def capture_request(kind: str, body: dict) -> Path | None:
       """Si AITRACEUR_CAPTURE_DIR est défini, écrit le corps de requête en JSON
       (clés triées, UTF-8) sous <dir>/<kind>_<AAAAMMJJTHHMMSSZ>_<sha8>.json et renvoie le chemin."""
   ```

   Appels : dans `generate_circuit_async` (`main.py`, vers l.2501) avec `kind="circuit"` et dans
   `generate_sprint_with_validation` (vers l.4941) avec `kind="sprint"`, avant la soumission de la
   tâche.
2. **Graine en sprint.** Dans `_sprint_impl`, lire `body.get("ga_seed")` exactement comme
   `_circuit_impl` le fait (l.2168-2174) et le passer au `GenerationRequest` construit vers l.4300.
3. **Drapeau réseau.** Nouveau réglage `AITRACEUR_ONLINE` dans `src/core/config.py`
   (`bool`, **défaut `True` dans cette phase** pour ne rien changer au comportement). Quand il vaut
   `False` : `_sprint_impl` saute l'étape « 1b : enrichissement OSM » (l.4094 et suivantes) ;
   `_circuit_impl` saute la construction du `RouteAnalyzer` OSM (vers l.2343) ; les deux sautent
   `build_elevation_cache` et le repli MapAnt. Chaque saut écrit une ligne de journal
   `[offline] <étape> ignorée`.

**Tests** (`backend/tests/test_capture.py`) : sans variable, aucun fichier écrit ; avec variable, un
fichier JSON relisible et identique au corps envoyé ; deux corps identiques donnent le même `sha8`.

### 0.8 — Rejouer : `evalbench/replay_v1.py` et `evalbench/run.py`

`replay_v1.py` est le **seul** module du moteur v2 autorisé à importer `src.main` (exception à
inscrire dans `test_architecture.py`).

```python
def replay(capture_path: Path, seed: int) -> ReplayResult:
    """Charge le corps capturé, force ga_seed=seed, appelle _circuit_impl(body) ou
    _sprint_impl(task_id, body) dans le processus courant, et renvoie les points produits."""

@dataclass(frozen=True)
class ReplayResult:
    capture: str; kind: str; seed: int
    ok: bool; error: str | None
    points_lnglat: list[tuple[float, float]]     # départ, postes, arrivée
    runtime_s: float
```

- Écrire l'adaptateur `extract_points(result)` **après avoir inspecté une vraie sortie** de chaque
  endpoint ; figer un échantillon de chaque dans `backend/tests/aitraceur/fixtures/v1_outputs/`
  (JSON réduit à quelques postes) et le tester.
- En sprint, la sortie se lit dans `src.main._sprint_tasks[task_id]` ; si `_sprint_impl` renvoie un
  dictionnaire contenant `error`, le résultat est `ok=False` (c'est le défaut corrigé en phase 1).

`run.py` — interface en ligne de commande :

```bash
cd backend
python -m src.aitraceur.evalbench.run v1 --captures ../captures --seeds 0 1 2 3 4 --out ../runs/p0_baseline
```

Produit dans le dossier de sortie :

| Fichier | Contenu |
|---------|---------|
| `results.jsonl` | Une ligne par (capture, graine) : tous les champs de `CourseMetrics`, `runtime_s`, `ok`, `error`. |
| `summary.md` | Par capture : médiane et écart interquartile de chaque indicateur ; ligne de total. |
| `determinism.json` | Pour chaque capture, la graine 0 est jouée deux fois : `identical: true/false`. |
| `run_metadata.json` | Commit, dépôt propre ou non, `AITRACEUR_ONLINE`, état du service de tuiles (joignable ou non), versions de Python, numpy, scipy, date UTC, ligne de commande. |

Rayon d'amas : 60 m si `kind == "sprint"`, 150 m sinon. Zone : `bounding_box` du corps capturé.
Polygones interdits : `forbidden_zones_polygons` du corps capturé (c'est la vérité *selon le moteur
v1* ; la vraie vérité arrive en phase 3).

### 0.9 — Ligne de base sur les cartes du traceur

À faire avec le traceur (15 à 30 minutes de sa part) :

1. Démarrer les services avec `AITRACEUR_CAPTURE_DIR=<dépôt>/captures`.
2. Pour chaque carte d'essai — au minimum deux cartes de sprint (dont Caen) et trois de forêt (parmi
   airelles, cerisy, grochot, llose, montmirel, steanne) — charger la carte, créer un circuit, poser
   un départ, cliquer une fois sur « Générer ». Profils : sprint par défaut ; forêt moyenne distance
   H21E par défaut ; et, sur une carte de forêt, un circuit de couleur « Jaune ».
3. Noter dans `captures/LISEZMOI.md` : quel fichier correspond à quelle carte et à quel profil.
4. Lancer le banc (commande de 0.8), une fois avec `AITRACEUR_ONLINE=1`, une fois avec `=0`.
5. Copier `summary.md` dans `docs/plan/mesures/P0_baseline.md` avec `run_metadata.json` en annexe.

### 0.10 — Remettre la documentation d'accord avec le code

- `CLAUDE.md`, `README.md`, `ARCHITECTURE.md` : remplacer toute description des « termes A→L »
  comme pilotes de la génération par l'énoncé exact du constat C2 (`01_ETAT_DES_LIEUX.md`).
- Déplacer dans `backend/scripts/archive_2026-05/` les scripts d'analyse des expériences de mai
  (`analyze_*.py`, `atlas_*.py`, `benchmark_lri.py`, `benchmark_diversity.py`,
  `build_lri_model.py`, `plot_manifold.py`, `collect_fitness_data.py`), **après** avoir vérifié par
  `grep` qu'aucun module de `backend/src` ne les importe. Y ajouter un `LISEZMOI.md` de cinq
  lignes : ce que mesuraient ces scripts, et pourquoi leurs conclusions sont classées « non
  établies » (constat C2).
- Garder en place `annotate_legs.py`, `annotate_legs.html`, `generate_intent_legs.py` et les
  fichiers `output/annotations_*.csv`, `output/intent_legs_*.csv` : ils servent en phase 5.

## Critères d'acceptation

1. `git log` montre les commits 14c–14d sur `main` ; l'étiquette `avant-plan-2026-11` existe.
2. `python -m pytest tests -q` démarre dans un environnement neuf ; le décompte est consigné.
3. `backend/src/aitraceur/` ne contient que le squelette v2 et `evalbench/` ; les trois tests
   d'architecture passent.
4. Les six cas de `test_metrics.py` passent avec les valeurs exactes du tableau.
5. Le banc rejoue au moins une capture forêt et une capture sprint, 5 graines chacune, et produit
   les quatre fichiers.
6. `docs/plan/mesures/P0_baseline.md` existe et contient, par carte, K2 (`max_in_radius`),
   K3 (`crossings`), K4 (`coverage_4x4`), `forbidden_hits`, `is_loop`, et le résultat de
   déterminisme (K5).
7. `REGISTRE.md` contient les valeurs de base et le verdict de déterminisme.
8. Aucune phrase de `CLAUDE.md`, du README ou d'`ARCHITECTURE.md` n'affirme que les termes A→L
   pilotent la génération.

## Hors périmètre

- Corriger quoi que ce soit dans le comportement du moteur v1 (phase 1).
- Toute lecture de symbole (phase 2).

## Pièges

- `import src.main` exécute le démarrage de l'application (base SQLite, routeurs). Le banc doit
  tourner depuis `backend/` pour que les chemins relatifs fonctionnent.
- Les corps capturés pèsent plusieurs mégaoctets (`ocad_geojson_features`) : ils restent hors dépôt.
- Si le service de tuiles est arrêté, le moteur v1 change de comportement (pas de carte de chaleur,
  pas de zones interdites vectorielles). `run_metadata.json` doit le dire ; comparer deux exécutions
  qui diffèrent sur ce point n'a pas de sens.
- Si `determinism.json` dit `false` malgré la graine, ne pas chercher à corriger ici : le consigner
  au registre. C'est une donnée sur le moteur v1.
