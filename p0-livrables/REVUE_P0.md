# Revue de la phase 0 (`plan/p0-socle` → `main`)

**Objet :** revue complète de la phase 0 avant fusion manuelle dans `main`.
**Branche revue :** `plan/p0-socle` (tip `672d948`)
**Base :** `main` = `e321816` · étiquette `avant-plan-2026-11` = `60b624a`
**Date de la revue :** 2026-11-22

---

## 1. Grille des critères d'acceptation

| # | Critère | Vérification | Verdict |
|---|---|---|---|
| 1 | Inventaire de **7 captures** | Bayeux, Dôme, Porten-Bessin (sprint) ; Forêt de Caen MD, Forêt de Caen Jaune, Kûti MD, Ste Anne II MD (forêt) — `captures/LISEZMOI.md` : 7 lignes, 7 correspondances vérifiées | ✅ |
| 2 | Chaque capture rejouée avec les graines `0 1 2 3 4` | 7 captures × 5 graines × 2 modes — **70 rejoues, 0 erreur** | ✅ |
| 3 | Chaque mode produit `results.jsonl`, `summary.md`, `determinism.json`, `run_metadata.json` | 8 fichiers dans `docs/plan/mesures/`, 35 lignes de données chacun | ✅ |
| 4 | Les huit artefacts versionnés, **données brutes comprises** | `P0_baseline_*` et `P0_baseline_offline_*`, commits `89dab05` et `672d948` | ✅ |
| 5 | `captures/LISEZMOI.md` complété | 7 lignes, chacune vérifiée contre le fichier réellement créé | ✅ |
| 6 | `docs/plan/mesures/P0_captures.md` | inventaire, écart §0.9, mode effectif par capture | ✅ |
| 7 | `REGISTRE.md` renseigné : E36–E43, verdict de déterminisme, V24–V27 | E36–E43, E45–E50, V24–V27 renseignés **à partir des deux bancs réels** | ✅ |
| 8 | V24–V27 avec les formulations approuvées | rejouabilité/temps · cache froid/chaud · offline/online · référence ou remplacement — **les quatre portent une réponse mesurée** | ✅ |
| 9 | `P0.md` documente l'écart au gabarit §0.9 | §0.9 « Fait » + tableau des écarts | ✅ |
| 10 | Correctif CRS réconcilié avec la forme complète E45 | E45 décrit l'état réel (correctif minimal dans la branche) ; la forme complète reste à faire | ✅ |
| 11 | Imports, tests, captures, comptes rendus vérifiés | `pytest` 226 passés / 4 échoués (pré-existants) ; `node test.js` 22/22 ; imports OK | ✅ |
| 12 | Aucun correctif du moteur v1 hors P1 ; le service de tuiles reste un prérequis | aucun correctif moteur dans la branche ; E45 le rappelle | ✅ |

## 1 bis. Conformité aux 8 critères d'acceptation du plan d'origine

`docs/plan/10_P0_socle_et_mesure.md` — « Critères d'acceptation » :

| # | Critère du plan | Constat | Verdict |
|---|---|---|---|
| 1 | Commits 14c–14d sur `main` ; étiquette `avant-plan-2026-11` | `3ccb663` (14d), `b436b34` (14c) sur `main` ; étiquette = `60b624a` | ✅ |
| 2 | `pytest tests -q` dans un environnement neuf ; décompte consigné | 226 passés, 4 échoués (pré-existants `aitraceur_proto`), 7 warnings — consigné dans `P0.md` | ✅ |
| 3 | `backend/src/aitraceur/` ne contient que le squelette v2 et `evalbench/` ; les 3 tests d'architecture passent | 13 sous-paquets vides + `evalbench/` ; 3 tests (imports interdits, hasard global, `except` silencieux) passent | ✅ |
| 4 | Les six cas de `test_metrics.py` passent avec les valeurs exactes du tableau | 6/6 | ✅ |
| 5 | Le banc rejoue au moins une capture forêt et une capture sprint, 5 graines chacune, et produit les quatre fichiers | 7 captures (3 forêts + 1 couleur + 3 sprint) × 5 graines × 2 modes → 8 fichiers | ✅ |
| 6 | **`docs/plan/mesures/P0_baseline.md` existe** et contient, par carte, K2, K3, K4, `forbidden_hits`, `is_loop` et le déterminisme | fichier créé le 22/11/2026 : les 7 cartes × les 2 modes, avec les six indicateurs demandés | ✅ |
| 7 | `REGISTRE.md` contient les valeurs de base et le verdict de déterminisme | E36–E43 (valeurs de base), E46 (déterminisme) | ✅ |
| 8 | Aucune phrase de `CLAUDE.md`, du README ou d'`ARCHITECTURE.md` n'affirme que les termes A→L pilotent la génération | les trois mentions disent explicitement « télémétrie uniquement, non branchée sur la sélection (constat C2) » | ✅ |

**Un écart de fond subsiste, documenté :** l'inventaire demandé au §0.9 point 2 (« au minimum deux cartes
de sprint (**dont Caen**) et trois de forêt (parmi … **steanne**) ») n'est **pas** celui du plan — pas de sprint
Caen, et seule Ste Anne II figure dans la liste des forêts. C'est un écart de **données disponibles**, pas de
méthode : il est consigné dans `P0.md` § Écarts et `P0_captures.md` § 3, et il n'a pas été masqué.

### Corrections apportées à cette revue

* `apply_p0_crc.py` n'était pas **idempotent** : il remplace `## À tester à la main (étape 0.9)` par
  `## Rejouer le banc (procédure vérifiée)`, donc un second passage sur un `P0.md` déjà corrigé échouait.
  `replace_section` reconnaît désormais le remplacement déjà fait.
* `finalize.sh` visait `origin/plan/p0-socle`, branche supprimée après fusion : la référence de base est
  maintenant paramétrable (`P0_BASE_REF`, `origin/main` par défaut).
* E37 et E38 distinguaient mal les groupes (le Jaune compté dans « les forêts ») : corrigés, cohérents
  avec E36.
* E49 compte **9/15** rejoues sprint en ligne (et 8/15 hors ligne), et non 8/15.

## 2. Ce que la phase 0 a coûté en corrections

| Commit | Nature |
|---|---|
| `eb0351a` | compteur de cache C3 + pages RTS A3 |
| `6e78285` | EPSG:3301 (Kûti, Estonie) côté service de tuiles et côté front |
| `5b36161`, `e87a439` | captures Kûti et Ste Anne II + `LISEZMOI.md` |
| `632603f` | l'extracteur de points du banc assumait un format de `controls` que le moteur ne produit pas (E48) |

## 2 bis. Ce que le banc en ligne mesure (35/35 trajectoires valides, 0 erreur)

| Groupe | Captures | long. (m) | min paire | <30 m | <60 m | crois. | interdits | couv. (K4) | t (s) |
|---|---|---|---|---|---|---|---|---|---|
| forêt (3) | Forêt de Caen MD, Kûti MD, Ste Anne II MD | 8 202 – 8 392 | 62 – 119 m | 0 | 0 | 0 – 1 | 0 | 0,25 – 0,625 | 144 – 157 |
| forêt couleur (1) | Forêt de Caen Jaune | 2 287 | 40 – 79 m | 0 | 0 – 1 | 0 | 0 | 0,19 – 0,25 | 20 – 25 |
| sprint urbain (3) | Bayeux, Dôme, Porten-Bessin | 2 606 – 3 285 | **0,0 m** | 1 – 7 | 1 – 9 | 0 – **6** | 0 | 0,06 – 0,375 | 279 – 313 |

* **Zones interdites : 0 violation sur les 35 rejoues** — le moteur v1 les respecte, service de tuiles
  joignable pendant tout le run (`tile_service_reachable: true`).
* **Nombre de postes : exact** — 27 (forêt), 12 (couleur), 16 (sprint) demandés, 25 + 2, 10 + 2 et
  14 + 2 obtenus (`n_controls` compte les postes internes, hors départ et arrivée).
* **Déterminisme : 2/7** (Dôme et Porten-Bessin) ; les 4 forêts et Bayeux ne sont pas reproductibles
  à graine fixée.
* **Durée cumulée : 1,86 h** de rejeu, dont 21 rejoues sprint à ~290 s — l'enrichissement Overpass est
  refait à chaque rejeu.
* **Cache disque : il évolue pendant le run** (`hmc_npz` 5 → 7 sur les sprint) — élément de réponse
  pour V25.

## 2 ter. Ce que le banc hors ligne mesure (35/35 trajectoires valides, 0 erreur)

| Ce qui est comparé | En ligne | Hors ligne |
|---|---|---|
| Rejoues valides | 35/35 | **35/35** |
| Durée cumulée | 1,86 h | **1,49 h** |
| Postes livrés (forêt / couleur / sprint) | 25 / 10 / 14 | **25 / 10 / 14** — identique |
| Zones interdites violées | 0 | **0** |
| Couverture, médiane | 0,250 | 0,188 |
| Distance minimale, sprint | 0,0 m — 9/15 rejoues | 0,0 m — **8/15 rejoues** |
| Reproductibilité à graine fixée | 2/7 | **1/7** |

* **Le mode hors ligne est opérationnel** : couper MapAnt, Overpass et l'IGN ne casse pas la
  production de circuits. Le service de tuiles est local : les zones interdites restent
  disponibles, et aucune n'est violée.
* **Le gain de temps ne vient pas des cartes urbaines** : les forêts passent de ~150 s à ~60-90 s
  par rejeu, les sprints restent à ~285 s (CPU, pas réseau).
* **Le défaut de duplication survit à la coupure** : Bayeux passe de 0,0 m à 35,1 m (le doublon
  disparaît) mais le Dôme passe de 10,2 m à 0,0 m (le doublon apparaît). Ce n'est pas un artefact
  de l'enrichissement OSM — c'est une propriété du placement des postes sur un jeu de candidats
  réduit. **E49.**
* **Cas isolé** : Porten-Bessin graine 0 hors ligne produit 22 auto-intersections et 4 478 m,
  contre une médiane de 3 255 m et 2 auto-intersections. Un rejeu extrême, pas une tendance.

## 3. Faits établis que la phase 0 a produits

* **E44** — le service de tuiles ne pouvait pas rendre les cartes d'emprise entre ~2,7 et 4,5 km².
* **E45** — EPSG:3301 inconnu du service de tuiles et du registre front ; correctif minimal appliqué, forme complète à faire.
* **E47** — `technical_level` porte deux significations (niveau IOF / difficulté du terrain) ; une capture couleur Jaune passe par le chemin sprint.
* **E48** — l'instrument de mesure de la phase 0 ne savait pas lire la sortie du moteur pour les circuits de forêt, et la fixture de test validait le bug.
* **E49** — sur les cartes urbaines, le moteur v1 place **deux postes au même point** : **9 des 15** rejoues sprint en ligne (Bayeux graines 0/2/3/4, Dôme 0/3, Porten-Bessin 1/3/4) et **8 des 15** hors ligne ; `min_pair_dist_m` = 0,0 m. Aucune paire sous 30 m en forêt. Le contrôle interne ne porte que sur les postes consécutifs (E09) : seule une mesure exhaustive par paires le révèle. **C'est le résultat principal de la phase 0.**
* **E50** — le mode hors ligne est **opérationnel** : 35/35 rejoues valides, 0 zone interdite violée, nombre de postes et longueur conservés.
* **E46** — verdict de déterminisme à graine fixée, mesuré par le banc.
* **E36–E43** — valeurs de base du moteur v1.

## 4. Points restant à traiter hors P0

* **Correctif CRS complet (forme E45)** : module `crs.js` centralisé côté service de tuiles, sixième section de tests, registre front complet. *Prérequis infrastructurel.*
* **Captures du sprint Caen** et **forêts de la liste du plan** (airelles, cerisy, grochot, llose, montmirel) : l'inventaire réel ne les contient pas. À refaire si la phase 1 en a besoin.
* **V27** — le moteur v1 est-il une référence exploitable, ou faut-il le remplacer ? Tranché sur E36–E43 et E46.

## 5. Procédures de rejeu (vérifiées)

Voir `docs/plan/comptes-rendus/P0.md` § « Rejouer le banc ».
Deux préconditions vérifiées à l'usage : **service de tuiles actif** (sinon `forbidden_hits` est faussé)
et **un seul banc à la fois** (deux exécutions concurrentes écrivent dans le même journal et le même
dossier de sortie, et se corrompent mutuellement les caches disque — une exécution a dû être écartée).

## 6. Verdict

**La phase 0 est complète et validée pour fusion.** Les douze critères de la grille sont
satisfaits, à partir des deux seuls bancs réellement exécutés (70 rejoues, 0 erreur) :

* les **huit artefacts bruts** sont versionnés, données brutes comprises, en deux commits
  (`89dab05` en ligne, `672d948` hors ligne) ;
* **E36–E43, E46, E50** et **E45–E49** sont renseignés **à partir des seules mesures réelles** —
  aucune valeur n'est reprise d'une fixture de test ;
* **V24–V27** portent une réponse mesurée, pas une formulation de question ;
* les **écarts au gabarit §0.9** et **l'écart de nommage** (`P0_baseline.md` → huit artefacts
  `P0_baseline_*` / `P0_baseline_offline_*`) sont documentés dans `P0.md` et `P0_captures.md` ;
* le **moteur v1 n'a pas été modifié** : les quatre incidents traversés portaient tous sur
  l'instrument de mesure.

### Ce que la phase 0 ne tranche pas

* **V27** — le moteur v1 reste-t-il une référence exploitable pour la phase 1, ou faut-il le
  remplacer ? La question est désormais outillée, pas tranchée : elle appartient à la phase 1.
* **La forme complète de E45** (module `crs.js` centralisé, sixième section de tests, registre
  front complet) et les **captures manquantes** (sprint Caen, forêts de la liste du plan) restent
  à faire.
* **Le défaut E49** n'est **pas corrigé** — le plan l'interdit explicitement en phase 0. Il est
  documenté, mesuré dans les deux modes, et c'est le premier candidat à la phase 1.
