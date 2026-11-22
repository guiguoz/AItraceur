# Phase 1 — Assainissement du moteur actuel

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

## But

Corriger dans le moteur v1 les défauts **avérés, localisés et sans débat** : ceux qui produisent
directement les symptômes signalés et qui ne dépendent pas de la lecture des symboles. Aucun réglage.
Le moteur v1 reste en service pendant la construction du v2 ; autant qu'il cesse de nuire.

## Ce que le traceur verra

- Les circuits sprint ne sont plus poussés à regrouper des postes.
- Si une arrivée est posée, le circuit y arrive.
- Le nombre de postes demandé est respecté.
- Un circuit « Vert » est plus court et plus facile qu'un « Jaune ».
- Une erreur de génération sprint s'affiche tout de suite au lieu d'une attente de 150 secondes.
- L'application ne va plus chercher de données sur Internet sans qu'on le lui demande.

## Prérequis

- Phase 0 terminée ; `docs/plan/mesures/P0_baseline.md` existe.

## Étapes

Chaque étape est un commit avec son test. L'ordre est libre sauf 1.12 (dernière).

### 1.1 — Rendre visibles les erreurs de génération sprint

**Constat** : `_sprint_impl` fait `return {"error": …}` (`main.py` l.4330 et l.4357) ;
`_run_sprint_task` (l.4925) ignore la valeur de retour ; la tâche reste `processing`.

**À faire** dans `_run_sprint_task` :

```python
result = _sprint_impl(task_id, body)
if isinstance(result, dict) and result.get("error"):
    _sprint_tasks[task_id] = {"status": "error", "result": result}
elif _sprint_tasks.get(task_id, {}).get("status") == "processing":
    _sprint_tasks[task_id] = {"status": "error",
                              "result": {"error": "Fin de traitement sans résultat.", "dialogue": []}}
```

Vérifier dans `App.jsx` que la boucle d'attente sprint affiche le champ `error` quand
`status === "error"` ; sinon l'ajouter (message dans la zone d'erreur existante `generationError`).

**Test** (`backend/tests/test_endpoints.py`) : en remplaçant `AIGenerator.generate` par une fonction
qui lève une exception, `POST /generate-sprint` puis `GET /sprint-status/{id}` renvoie
`status == "error"` et un champ `error` non vide.

### 1.2 — Ne plus récompenser les amas de postes

**Constat** : C3. Aucune source ne porte cette règle.

**À faire** :

1. `genetic_algo.py`, `_default_scoring` : supprimer le calcul de `cluster_bonus` (bloc l.3320-3350
   et son aperçu de journal l.3275-3285) ; poser `cluster_weight = 0.0` et `base_weight_adj = 1.0` ;
   retirer les deux termes `+ cluster_bonus * cluster_weight` (l.3369 et l.3383). Vérifier que les
   quatre expressions de retour (l.3364-3414) restent syntaxiquement identiques par ailleurs.
2. `ffco_rules_engine.py` : supprimer le champ `w_cluster` de `GAWeights` et sa valeur en sprint.
3. `placement_rules.json` : supprimer les neuf clés `disorientation_cluster_*`.
4. `controleur.py` : supprimer l'appel (l.205-207) et la méthode
   `_check_c16_disorientation_clusters` ; `controleur_rules.json` : supprimer l'entrée `C16`.
   Supprimer ou adapter les tests de `test_controleur.py` qui portent sur C16.

**Test** (`backend/tests/test_no_cluster_rule.py`) : la chaîne `disorientation_cluster` n'apparaît
plus dans `backend/src` (hors `aitraceur_proto`) ; `ControleurSprint.validate` sur un circuit sprint
sans aucun amas ne produit aucun problème de code `C16`.

### 1.3 — Transmettre et respecter l'arrivée

**Constat** : le frontend n'envoie jamais `end_position` ; `ai_generator.py` l.298 :
`end = request.end_position or start`.

**À faire** :

1. Frontend — extraire la construction des paramètres de `handleAiGenerate` (`App.jsx` l.888 et
   suivantes) dans une fonction pure `buildGenerationParams({ circuit, circuitParams, bbox,
   candidatePoints, oobZones, … })` placée dans `frontend/src/services/generationParams.js`. Elle
   renvoie `{ forestParams, sprintParams }`. Y ajouter, pour les deux :
   `...(finishControl && { end_position: [finishControl.lng, finishControl.lat] })`, où
   `finishControl` est le premier poste de type `finish` du circuit actif. `App.jsx` appelle cette
   fonction ; aucun autre changement de comportement.
2. Backend — `_circuit_impl` : lire `body.get("end_position")` (liste de deux nombres, sinon `None`)
   et le passer à `GenerationRequest(end_position=…)`. La seconde construction de
   `GenerationRequest` (l.2358-2375) recopie les champs un à un et en perdrait de nouveaux : la
   remplacer par `dataclasses.replace(request, heatmap_cache=…, elevation_cache=…,
   route_analyzer=…)`.
3. Backend — `_sprint_impl` : même lecture, même transmission (construction vers l.4300).

**Tests** :
- `frontend/src/__tests__/generationParams.test.js` : avec un poste `finish`, `end_position` est
  présent dans les deux jeux de paramètres ; sans, il est absent.
- `backend/tests/test_genetic_algo.py` : `GeneticAlgorithm(config).generate(start, end, [])` avec
  `end` à 500 m de `start` et une graine fixée → le dernier point du meilleur circuit est `end`.

### 1.4 — Respecter le nombre de postes demandé

**Constat** : `App.jsx` l.979, `target_controls: Math.ceil((circuitParams.target_controls ?? 12) * 1.5)`.

**À faire** : dans `buildGenerationParams`, `target_controls: circuitParams.target_controls ?? 12`.

**Test** (même fichier de test que 1.3) : `forestParams.target_controls` égale la valeur d'entrée.

### 1.5 — Mètres et degrés : une seule conversion, dans toutes les directions

**Constat** : C10.

**À faire** :

1. Nouveau module `backend/src/services/generation/geo_utils.py` :

   ```python
   M_PER_DEG_LAT = 111_320.0
   def m_per_deg_lng(lat_deg: float) -> float:
       return M_PER_DEG_LAT * math.cos(math.radians(lat_deg))
   def offset_lnglat(lng: float, lat: float, dx_m: float, dy_m: float) -> tuple[float, float]:
       return lng + dx_m / m_per_deg_lng(lat), lat + dy_m / M_PER_DEG_LAT
   ```

2. `_mutate_random_walk` (l.1957) et `_mutate_perturbation` (l.2067) : remplacer le tirage unique
   par un déplacement de direction uniforme et de rayon uniforme dans `[0, r_max]`
   (`r_max = 0.12 × leg_m`, respectivement `0.25 × leg_m`), appliqué par `offset_lnglat`.
   Corriger au passage la docstring de `_mutate_perturbation` (elle annonce 40 %, le code fait autre
   chose : écrire ce que fait le code).
3. `_mutate_leg_improvement` (l.2030-2041) : calculer la perpendiculaire **en mètres** (convertir
   `dx`, `dy` avant de normaliser), puis appliquer le décalage par `offset_lnglat`.
4. `_create_smart_circuit` (l.1254) : `lng_deg = target_leg_m / m_per_deg_lng(start[1])`.
5. `main.py` l.4368 et l.4830 ; `services/analysis/gpx_parser.py` l.211 : remplacer `72600` par
   `m_per_deg_lng(lat)`.

**Tests** (`backend/tests/test_geo_utils.py`) :
- `m_per_deg_lng(49.18)` = 72 760 ± 50 ; `m_per_deg_lng(43.60)` = 80 615 ± 50.
- `offset_lnglat` puis distance géodésique (pyproj `Geod`) : erreur < 0,5 % pour 100 m dans les
  quatre directions.
- Isotropie : avec une graine fixée, 400 appels de `_mutate_random_walk` sur le même circuit ; les
  déplacements du poste modifié tombent dans les quatre quadrants, chacun avec au moins 15 % des cas.
- Garde : la chaîne `72600` n'apparaît plus dans `backend/src` (hors `aitraceur_proto`).

### 1.6 — Zones interdites : additionner, et filtrer les candidats ajoutés

**Constat** : C5, points 2 et 3.

**À faire** :

1. `main.py` l.4088 : `oob_polygons = list(forbidden_zones) + list(_ocad_fz)` (union, plus de
   remplacement).
2. Extraire la fusion des candidats OSM (l.4104-4111) dans une fonction pure
   `merge_candidates(base, extra, forbidden_rings, dedup_deg=0.00009, limit=800)` placée dans
   `backend/src/services/generation/candidate_merge.py`. Elle écarte tout candidat de `extra` situé
   dans un anneau interdit (réutiliser `_ray_cast` de `main.py`, à déplacer dans ce module) ou trop
   proche d'un candidat déjà retenu.

**Tests** (`backend/tests/test_candidate_merge.py`) : un candidat supplémentaire à l'intérieur d'un
anneau interdit est écarté ; un doublon à moins de `dedup_deg` est écarté ; les autres sont gardés ;
l'ordre de `base` est conservé.

### 1.7 — Couleurs FFCO dans le bon ordre (correction provisoire)

**Constat** : C8. Correction complète en phase 4 ; ici on remet l'ordre et les distances.

**À faire** :

1. `backend/data/ffco_categories.json`, bloc `couleur` : réécrire dans l'ordre
   Vert, Bleu, Jaune, Orange, Violet, Noir avec les distances indicatives **moyenne distance** du
   Guide des circuits de couleur (éd. déc. 2024, §4.2), en mètres :

   | Couleur | `min_m` | `max_m` | `td` provisoire | Plafond `winning_min` |
   |---------|---------|---------|-----------------|-----------------------|
   | Vert | 2000 | 2500 | TD1 | 30 |
   | Bleu | 2000 | 3000 | TD2 | 40 |
   | Jaune | 2000 | 4000 | TD3 | 60 |
   | Orange | 3000 | 4000 | TD4 | 80 |
   | Violet | 4000 | 6000 | TD5 | (valeur actuelle) |
   | Noir | 4000 | 6000 | TD5 | (valeur actuelle) |

   Les plafonds de temps viennent du RTS mai 2025 §3.2.1 (niveaux maximaux et temps préconisés pour
   les jeunes). `max_climb_pct` = 4 pour toutes les couleurs (Principes de traçage §3.11.6).
   `target_controls` : reprendre les valeurs actuelles par rang (1ʳᵉ ligne actuelle → Vert, etc.).
   Mettre `_source` à jour : « Guide de mise en place des circuits de couleur, FFCO, éd. déc. 2024 ;
   RTS CO éd. mai 2025 §3.2.1 ; correspondance TD provisoire (plan, phase 1) ».
2. Déplacer `_FALLBACK_COLOR` (`App.jsx` l.24-31) dans `frontend/src/services/ffcoDefaults.js`,
   l'exporter, et l'aligner sur le même tableau.

**Tests** :
- Backend : en parcourant Vert → Noir, `td` ne décroît jamais et `max_m` ne décroît jamais ;
  `max_climb_pct <= 4` partout.
- Frontend : même vérification d'ordre sur `_FALLBACK_COLOR`.

### 1.8 — Distance minimale entre postes : toutes les paires

**Constat** : C9, dernière ligne.

**À faire** dans `_check_c02_too_close` (`controleur.py` l.338) : comparer **toutes** les paires de
postes de type `control`. Seuil : valeur de `controleur_rules.json` si présente, sinon 30 m, et
15 m en sprint. `rule_reference` : « FFCO, Règles techniques et de sécurité en Course
d'Orientation, éd. mai 2025, "Distance minimale entre les postes", p. 9/12 » — le texte : « pour
les échelles 1:7500, 1:10000 et 1:15000 : les postes ne doivent pas être placés à moins de
30 mètres à vol d'oiseau les uns des autres. Deux postes disposés sur deux éléments de même nature
ne peuvent être à moins de 60m à vol d'oiseau l'un de l'autre, – pour des échelles 1:4000 et
1:3000 : la distance minimum entre 2 postes est de 25m en distance de course et de 15m à vol
d'oiseau ». Le moteur v1 ne connaît ni la nature des éléments
ni la distance de course : il n'applique que les seuils à vol d'oiseau (30 m, 15 m en sprint) ; les
deux autres arrivent avec le contrôleur de la phase 7. Le message nomme les deux postes par leur
numéro d'ordre.

**Test** (`test_controleur.py`) : un circuit où les postes 2 et 5 sont à 10 m l'un de l'autre et tous
les postes consécutifs à plus de 100 m produit un problème `C02` citant 2 et 5.

### 1.9 — Hors ligne par défaut

**À faire** :

1. Comparer dans `P0_baseline.md` les deux séries (`AITRACEUR_ONLINE=1` et `=0`). Consigner l'écart
   au registre.
2. Passer le défaut de `AITRACEUR_ONLINE` à `False` (`src/core/config.py`, `.env.example`).
3. Hors ligne et sans aucun candidat issu d'une carte : `_sprint_impl` et `_circuit_impl` renvoient
   une erreur explicite — « Génération hors ligne : chargez une carte OCAD, ou activez le mode en
   ligne (AITRACEUR_ONLINE=1) pour utiliser OpenStreetMap. »
4. `startup_event` (`main.py` l.169-189) : ne lancer le fil `check_and_download` que si
   `AITRACEUR_ONLINE` est vrai.

**Test** : avec `AITRACEUR_ONLINE=0`, un rejeu de capture ne fait aucun appel à `requests.get` /
`requests.post` vers un hôte autre que `localhost` (remplacer `requests` par un espion dans le test).

### 1.10 — Retirer le document hors sujet du corpus de l'assistant

**Constat** : C11, dernier paragraphe.

**À faire** (avec l'accord du traceur ; le fichier reste dans l'historique git) :
supprimer `docs controleur/20241209_WL_FeuerungskontrolleurIn_Fz.pdf` ; retirer de
`backend/data/pdf_knowledge.jsonl` les lignes dont `source` est ce fichier (141 lignes attendues,
2 254 restantes).

**Test** : aucune ligne du fichier n'a ce `source` ; le nombre de lignes est 2 254.

### 1.11 — Arrêter la collecte automatique sur Livelox

**Constat** (registre E34, E35) : `services/importers/livelox_client.py` se connecte à Livelox avec
un compte personnel (`login`, l.53-101), recopie le jeton de session et se présente comme un
navigateur Chrome (`User-Agent`, `Origin`, `Referer`) pour interroger `api.livelox.com` sans clé
d'API. `livelox_importer.py` et `backend/ingest_livelox.py` l'utilisent pour des collectes par lots
(`--from`, `--to`, `--country`) ; `knowledge_base/scrapers/livelox.py` (`LiveloxScraper`) alimente la
route `/api/v1/knowledge/load-livelox` (`main.py` l.1692-1739). Les conditions d'utilisation de
Livelox (7 août 2026) interdisent d'extraire systématiquement des données « except through
authenticated and authorized API access ».

**À faire** :

1. Supprimer `services/importers/livelox_client.py`, `services/importers/livelox_importer.py`,
   `backend/ingest_livelox.py`, `services/knowledge_base/scrapers/livelox.py`, la route
   `/api/v1/knowledge/load-livelox`, et les exports correspondants dans
   `knowledge_base/__init__.py`, `knowledge_base/scrapers/__init__.py` et l'import de `main.py` l.51.
2. Lister les données déjà collectées dans la base locale (`source_format = "livelox_osm"`) et
   demander au traceur s'il les supprime ; ne rien effacer sans sa réponse.
3. Ajouter au test d'architecture (phase 0) : aucune occurrence de `livelox.com` dans
   `backend/src`, `backend/*.py` ni `frontend/src`.
4. Même question, sans rien supprimer à ce stade, pour `backend/scripts/scrape_rg2.py` (collecte
   des sites RouteGadget de clubs britanniques), les scripts Vikazimut et les quatre jeux de
   données Kaggle du CNN : vérifier les conditions de chaque site et la visibilité des jeux Kaggle
   (publics, ils rediffuseraient des extraits de cartes de clubs) ; consigner au registre (V22).

**Test** : le test d'architecture ci-dessus ; `pytest` et le démarrage du backend passent sans les
fichiers supprimés.

### 1.12 — Mesurer

Relancer le banc d'essai sur les mêmes captures et les mêmes graines qu'en phase 0, hors ligne.
Écrire `docs/plan/mesures/P1_apres.md` : tableau avant / après par carte pour K2
(`max_in_radius`, `n_clustered`), K3, K4, `is_loop`, `n_controls`, `leg_cv`. Mettre le registre à
jour, y compris si un indicateur ne bouge pas ou se dégrade.

Remarque : les captures de la phase 0 contiennent `target_controls` déjà multiplié par 1,5 et pas
d'`end_position`. Pour mesurer l'effet de 1.3 et 1.4, refaire **en plus** une capture par carte
après ces corrections (avec une arrivée posée) et la rejouer.

## Critères d'acceptation

1. Tous les tests listés passent ; aucun test préexistant ne régresse (hors tests C16 supprimés).
2. En sprint, médiane de `max_in_radius` en baisse sur au moins deux cartes de sprint, ou — si ce
   n'est pas le cas — une entrée « Réfuté » au registre l'explique chiffres à l'appui.
3. Avec une arrivée posée à plus de 200 m du départ, `is_loop` est faux sur toutes les graines.
4. `n_controls` du circuit produit égale la demande à ± 1 près.
5. Un circuit « Vert » demandé par l'interface part avec `target_length_m` ≤ 2 500.
6. Le backend démarre et génère un circuit, réseau coupé (câble débranché ou pare-feu), carte OCAD
   chargée.

## Hors périmètre

- Les tables de symboles et l'extraction des candidats (phase 2).
- Les postes imposés (`required_controls`) : le moteur v1 continue de les ignorer ; traité par le
  moteur v2 (phase 6). L'inscrire au registre comme limite connue.
- Le contrôle des circuits forêt (phase 7).
- Toute modification de poids ou de seuil de `_default_scoring`.

## Pièges

- `_default_scoring` fait plus de 350 lignes et quatre sorties ; supprimer le bloc d'amas sans
  toucher au reste. Relire le diff ligne à ligne.
- La suppression de C16 change le score du contrôleur sprint (`100 − 15×erreurs − 5×avertissements`)
  : des circuits auparavant « avertis » deviennent conformes. C'est attendu.
- L'extraction de `buildGenerationParams` ne doit changer **que** les deux champs prévus (1.3, 1.4).
  Comparer l'objet envoyé avant et après sur un cas réel (journal du navigateur).
