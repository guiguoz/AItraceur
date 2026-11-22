# Captures du banc P0 — inventaire et écarts au gabarit §0.9

**Date :** 2026-11-22
**Source :** `captures/LISEZMOI.md` (versionné) + corps des 7 requêtes capturées
**Banc :** `backend/src/aitraceur/evalbench/run.py` — 7 captures × 5 graines × 2 modes

---

## 1. Les sept captures

Les corps capturés sont hors dépôt (`.gitignore` : `captures/*`, avec `!captures/LISEZMOI.md`) :
ils pèsent plusieurs mégaoctets (`ocad_geojson_features`). Seule la table de correspondance
est versionnée, dans `captures/LISEZMOI.md`.

| Fichier | Carte | Type | Profil | `category` | `technical_level` | Longueur | Postes | Points candidats | Zones interdites | Emprise WGS84 |
|---|---|---|---|---|---|---|---|---|---|---|
| `sprint_20261119T164701Z_a530a9ea.json` | Bayeux | sprint | — | H21E | TD3 | 2 800 m | 16 | 251 | 4 130 | -0,74346 / 49,26830 → -0,68601 / 49,29897 |
| `sprint_20261119T171122Z_46871982.json` | Dôme | sprint | — | H21E | TD3 | 2 800 m | 16 | 91 | 2 245 | -0,36489 / 49,17349 → -0,33047 / 49,19238 |
| `sprint_20261119T172115Z_a562c112.json` | Porten-Bessin | sprint | — | H21E | TD3 | 2 800 m | 16 | 2 230 | 354 | -0,82494 / 49,31901 → -0,73414 / 49,36075 |
| `circuit_20261122T083414Z_a2f6feae.json` | Forêt de Caen | forêt | MD H21E | H21E | TD5 | 7 300 m | 27 | 1 041 | 11 | -0,44644 / 49,03106 → -0,41887 / 49,05025 |
| `circuit_20261122T084351Z_a63cd765.json` | Forêt de Caen | forêt | couleur Jaune | Couleur-Jaune | TD1 | 2 000 m | 12 | 1 041 | 11 | -0,44644 / 49,03106 → -0,41887 / 49,05025 |
| `circuit_20261122T092812Z_5685384b.json` | Kûti (Estonie) | forêt | MD H21E | H21E | TD5 | 7 300 m | 27 | 1 824 | 6 | 25,65611 / 58,05565 → 25,74364 / 58,10022 |
| `circuit_20261122T095424Z_7ca39337.json` | Ste Anne II | forêt | MD H21E | H21E | TD5 | 7 300 m | 27 | 426 | 7 | -0,45827 / 49,04278 → -0,43270 / 49,06827 |

Les paramètres `longueur`, `postes` et `technical_level` ne sont pas choisis à la main : le front
les calcule à partir de `backend/data/ffco_categories.json`
(`App.jsx`, `getCircuitParams()`). La vérification est exacte :

| Capture | Table FFCO | Front calcule | Capturé |
|---|---|---|---|
| forêts MD | `md.H21E` : min 6 000 / max 8 500 m, 18 postes, TD5 | `round((6000+8500)/2/100)×100` = 7 300 ; `ceil(18×1,5)` = 27 | 7 300 m, 27, TD5 ✓ |
| sprints | `sprint.H21E` : min 2 400 / max 3 200 m, 16 postes, TD3 | `round((2400+3200)/2/100)×100` = 2 800 ; 16 (×1,5 non appliqué au sprint) | 2 800 m, 16, TD3 ✓ |
| Jaune | `couleur.Jaune` : min 1 500 / max 2 500 m, 8 postes, TD1 | `round((1500+2500)/2/100)×100` = 2 000 ; `ceil(8×1,5)` = 12 | 2 000 m, 12, TD1 ✓ |

## 2. Ce que le moteur fait réellement de chaque capture

`ai_generator.py` l.250 :

```python
sprint_mode = request.circuit_type == "sprint" or request.technical_level in ("TD1", "TD2")
_base_dist = 30 if sprint_mode else 60
min_dist = scale_min_separation(_base_dist, request.map_scale, request.circuit_type or "md")
```

| Capture | Mode effectif | Séparation imposée | Seuil RTS p. 9/12 | Re-ranker d'itinéraire |
|---|---|---|---|---|
| Forêt de Caen MD | forêt | 60 m | 30 m | non |
| Kûti MD | forêt | 60 m | 30 m | non |
| Ste Anne II MD | forêt | 60 m | 30 m | non |
| **Forêt de Caen Jaune** | **sprint** | **40 m** | 30 m | **oui** |
| Bayeux, Dôme, Porten-Bessin | sprint | 30 m | 15 m | oui |

**La capture Jaune est un cas particulier.** Dans la branche `couleur`, le champ `technical_level`
ne porte pas le niveau technique IOF mais la **difficulté du terrain** — la note de
`ffco_categories.json` est explicite : « TD = difficulté terrain » ; jaune = TD1 (le plus facile),
noir = TD5. Le moteur lit ce champ avec le sens IOF (échelle britannique) et bascule donc la
capture en mode sprint : séparation 40 m au lieu de 60 m, re-ranker d'itinéraire activé.
C'est une conséquence directe de **E08**.

**Ce qui est établi, et ce qui ne l'est pas.** Ce n'est pas l'interface qui a été observée, c'est
le **corps de la requête capturé** : il porte `circuit_type: "couleur"` et
`category: "Couleur-Jaune"`. Ce sont ces deux champs qui font foi. Le mode effectif `sprint` en
découle mécaniquement (TD1) ; il ne dit rien du parcours de navigation. En particulier, le fait que
le moteur ait produit cette capture par le chemin sprint **ne prouve pas** qu'un mode « urbain »
ait été choisi à l'écran : un circuit de couleur peut être demandé depuis le parcours de forêt.
La formulation à retenir est donc « capture de catégorie `couleur` / Couleur-Jaune, traitée par le
chemin sprint à cause de TD1 », et non « capture urbaine ».

Effet de bord à retenir pour la lecture des mesures : `forbidden_hits` n'est pas comparable d'un
type à l'autre (4 130 zones interdites sur Bayeux, 2245 sur Dôme, 354 sur Porten-Bessin, 6 à 11
sur les forêts).

## 3. Écart au gabarit §0.9 du plan

Le plan (`docs/plan/10_P0_socle_et_mesure.md` §0.9) demande « au minimum deux cartes de sprint
(**dont Caen**) et trois de forêt (parmi airelles, cerisy, grochot, llose, montmirel, steanne) ».

| Attendu par §0.9 | Réel | Écart |
|---|---|---|
| un sprint **Caen** | aucun sprint Caen | **manquant** — l'inventaire réel comporte Bayeux, Dôme, Porten-Bessin |
| ≥ 2 sprints | 3 sprints | dépassé |
| 3 forêts, dont une de la liste (airelles, cerisy, grochot, llose, montmirel, **steanne**) | 4 forêts : Forêt de Caen (×2), **Kûti** (Estonie), Ste Anne II | **Ste Anne II** est la seule de la liste ; Forêt de Caen (×2) et Kûti sont des substituts |
| — | Kûti est **hors France** | non prévu ; a imposé l'enregistrement d'EPSG:3301 (E45) |
| `docs/plan/mesures/P0_baseline.md` | existe : valeurs de base **par carte** (K2, K3, K4, `forbidden_hits`, `is_loop`, déterminisme) pour les **deux** modes | le plan ne demandait qu'un résumé pour un seul mode ; la ligne de base réelle couvre deux modes et sept captures. À côté sont versionnées les **huit** sorties brutes du banc (`P0_baseline_*` et `P0_baseline_offline_*`), sans lesquelles E36–E43, E49 et E50 ne seraient pas contrôlables à la relecture. Un seul fichier de base, pas deux résumés concurrents |

Les deux cartes de Forêt de Caen partagent la même emprise, les mêmes 1 041 entités et les mêmes
11 zones interdites : ce sont deux profils de la **même** carte (MD H21E et couleur Jaune), comme
le demande §0.9 (« et, sur une carte de forêt, un circuit de couleur “Jaune” »).

## 4. Reproductibilité des captures

* Chaque fichier porte un horodatage UTC et une empreinte SHA-8 du corps de la requête
  (`backend/src/api/capture.py`) : `circuit_<AAAAMMJJTHHMMSSZ>_<sha8>.json`.
* Les 7 captures ont été produites les 19 novembre 2026 (sprints) et le 22 novembre 2026 (forêts).
* Le banc rejoue ces corps tels quels ; il ne dépend que d'eux et de la graine.

## 5. Ce que le banc mesure, et ce qu'il ne peut pas mesurer

* **Il mesure** : la rejouabilité (5 graines), le temps de rejeu, le déterminisme à graine fixée,
  et les indicateurs géométriques K2 (`max_in_radius`), K3 (`crossings`), K4 (`coverage_4x4`),
  `forbidden_hits`, `is_loop`, plus les distances entre postes.
* **Il ne mesure pas** : la conformité aux seuils RTS. Le moteur impose lui-même 60 m en forêt et
  30 m en sprint, alors que le RTS p. 9/12 demande 30 m et 15 m : la mesure vérifie le respect de
  la contrainte du moteur, pas celle du règlement. Seule une capture à seuil plus bas pourrait
  trancher.
* **Il ne mesure pas** la couleur FFCO du circuit « Jaune » : ce que le moteur traite, c'est un
  `technical_level` de difficulté de terrain.

## 6. Ce que le mode hors ligne ajoute

Le même banc a été rejoué avec `AITRACEUR_ONLINE=0` : MapAnt, Overpass et l'IGN sont coupés, le
service de tuiles local reste joignable. Les 35 rejoues hors ligne ont abouti, **0 erreur**.

| Ce qui est comparé | En ligne | Hors ligne |
|---|---|---|
| Rejoues valides | 35/35 | **35/35** |
| Durée cumulée | 1,86 h | **1,49 h** |
| Postes livrés | 25 / 10 / 14 | **25 / 10 / 14** (identique) |
| Zones interdites violées | 0 | **0** |
| Couverture (médiane) | 0,250 | 0,188 |
| Distance minimale, sprint | 0,0 m (9/15 rejoues) | 0,0 m (8/15 rejoues) |
| Reproductibilité à graine fixée | 2/7 | **1/7** |

Trois enseignements :

1. **Le mode hors ligne est opérationnel.** Longueur, nombre de postes et respect des zones
   interdites sont conservés : couper les données externes ne casse pas la production de circuits.
2. **Le gain de temps ne vient pas des cartes urbaines.** Les forêts passent de ~150 s à ~60-90 s
   par rejeu ; les sprints restent à ~285 s, dominés par le CPU et non par le réseau.
3. **Le défaut de duplication des postes survit à la coupure.** Bayeux passe de 0,0 m à 35,1 m
   (le doublon disparaît), mais le Dôme passe de 10,2 m à 0,0 m (le doublon apparaît). Ce n'est donc
   pas un artefact de l'enrichissement OSM, mais une propriété du placement des postes sur un
   jeu de candidats réduit (voir **E49**).

Cas isolé à signaler : Porten-Bessin graine 0 hors ligne produit 22 auto-intersections et un tracé
de 4 478 m, contre une médiane de 3 255 m et 2 auto-intersections. La médiane du mode reste à 2 ;
c'est un rejeu extrême, pas une tendance.
