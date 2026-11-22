# Ligne de base du moteur v1 — phase 0

**Établi le 2026-11-22.** Banc : 7 captures × 5 graines × 2 modes (35 rejoues valides en ligne, 35 hors ligne, 0 en erreur).

Fichier de référence du plan (`docs/plan/10_P0_socle_et_mesure.md` §0.9 point 5, critère d'acceptation 6) : les valeurs de base **par carte**, pour les deux modes.

Ce fichier n'est pas un second résumé concurrent : `P0_baseline_summary.md` et `P0_baseline_offline_summary.md` sont les sorties brutes du banc, `P0_baseline_results.jsonl` et `P0_baseline_offline_results.jsonl` en sont la donnée brute (une ligne par rejeu), et `P0_synthese.md` porte la comparaison complète et le détail par graine. Ici : la table de base.

Toutes les valeurs sont des **médianes sur les graines valides** de la capture.

## Valeurs par carte

| Capture | Carte | Mode effectif | K2 `max_in_radius` | K3 `crossings` | K4 `coverage_4x4` | `forbidden_hits` | `is_loop` | déterminisme (K5) | `n_controls` | longueur (m) |
|---|---|---|---|---|---|---|---|---|---|---|
| circuit_20261122T083414Z_a2f6feae.json | Forêt de Caen | foret (en ligne) | 3 | 0 | 0.562 | 0 | oui | ✗ | 25 | 8345 |
| circuit_20261122T083414Z_a2f6feae.json | Forêt de Caen | foret (hors ligne) | 3 | 0 | 0.562 | 0 | oui | ✗ | 25 | 7722 |
| circuit_20261122T084351Z_a63cd765.json | Forêt de Caen | sprint (couleur) (en ligne) | 2 | 0 | 0.250 | 0 | oui | ✗ | 10 | 2287 |
| circuit_20261122T084351Z_a63cd765.json | Forêt de Caen | sprint (couleur) (hors ligne) | 2 | 0 | 0.188 | 0 | oui | ✗ | 10 | 2276 |
| circuit_20261122T092812Z_5685384b.json | Kûti (Estonie) | foret (en ligne) | 3 | 0 | 0.312 | 0 | oui | ✗ | 25 | 8202 |
| circuit_20261122T092812Z_5685384b.json | Kûti (Estonie) | foret (hors ligne) | 3 | 0 | 0.250 | 0 | oui | ✗ | 25 | 8331 |
| circuit_20261122T095424Z_7ca39337.json | Ste Anne II | foret (en ligne) | 3 | 0 | 0.562 | 0 | oui | ✗ | 25 | 8392 |
| circuit_20261122T095424Z_7ca39337.json | Ste Anne II | foret (hors ligne) | 3 | 0 | 0.625 | 0 | oui | ✗ | 25 | 7849 |
| sprint_20261119T164701Z_a530a9ea.json | Bayeux | sprint (en ligne) | 3 | 2 | 0.125 | 0 | oui | ✗ | 14 | 2606 |
| sprint_20261119T164701Z_a530a9ea.json | Bayeux | sprint (hors ligne) | 2 | 2 | 0.125 | 0 | oui | ✗ | 14 | 2695 |
| sprint_20261119T171122Z_46871982.json | Dôme | sprint (en ligne) | 2 | 1 | 0.250 | 0 | non | ✓ | 14 | 2614 |
| sprint_20261119T171122Z_46871982.json | Dôme | sprint (hors ligne) | 2 | 2 | 0.188 | 0 | non | ✗ | 14 | 3020 |
| sprint_20261119T172115Z_a562c112.json | Porten-Bessin | sprint (en ligne) | 2 | 2 | 0.125 | 0 | non | ✓ | 14 | 3285 |
| sprint_20261119T172115Z_a562c112.json | Porten-Bessin | sprint (hors ligne) | 3 | 2 | 0.125 | 0 | non | ✓ | 14 | 3255 |

## Notes de lecture

- **K2** (`max_in_radius`) : nombre maximal de postes dans un rayon donné ; plus il est bas, moins les postes sont groupés.
- **K3** (`crossings`) : paires de jambes non adjacentes qui se croisent.
- **K4** (`coverage_4x4`) : part de la zone de tracé couverte par la grille 4×4.
- **`is_loop`** : le circuit se referme (départ et arrivée à moins de 1 m).
- **déterminisme (K5)** : rejoue de la graine 0 après les mesures, à chaud ; `✓` = même tracé, `✗` = tracé différent.
- **`n_controls`** : postes internes, hors départ et arrivée (`backend/src/aitraceur/evalbench/metrics.py` l.147-149) ; ajouter 2 pour le nombre de postes du circuit.
- **mode effectif** : ce que le moteur a réellement fait, pas ce que la capture demandait — voir `P0_captures.md` § 2.
