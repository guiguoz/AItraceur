# Synthèse du banc P0 — moteur v1

Mode en ligne : 35 trajectoires sur 7 captures.

## Mesures par capture (médiane des graines valides)

| Capture | Carte | Mode effectif | sépa. moteur | graines | long. (m) | min paire (m) | <30 m | <60 m | crois. (K3) | boucle | interdits | densité (K2) | couv. (K4) | déterm. | durée (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| circuit_20261122T083414Z_a2f6feae.json | FORET-DE-CAEN | foret MD H21E | foret | 60 m | 5/5 | 8345 | 68.5 | 0 | 0 | 0 | oui | 0 | 3 | 0.562 | ✗ | 150 |
| circuit_20261122T084351Z_a63cd765.json | FORET-DE-CAEN | couleur Jaune | sprint (couleur) | 40 m | 5/5 | 2287 | 42.5 | 0 | 0 | 0 | oui | 0 | 2 | 0.250 | ✗ | 22 |
| circuit_20261122T092812Z_5685384b.json | KUTI | foret MD H21E | foret | 60 m | 5/5 | 8202 | 88.7 | 0 | 0 | 0 | oui | 0 | 3 | 0.312 | ✗ | 144 |
| circuit_20261122T095424Z_7ca39337.json | STE-ANNE-II | foret MD H21E | foret | 60 m | 5/5 | 8392 | 80.0 | 0 | 0 | 0 | oui | 0 | 3 | 0.562 | ✗ | 157 |
| sprint_20261119T164701Z_a530a9ea.json | BAYEUX | sprint | sprint | 30 m | 5/5 | 2606 | 0.0 | 1 | 4 | 2 | oui | 0 | 3 | 0.125 | ✗ | 294 |
| sprint_20261119T171122Z_46871982.json | DOME | sprint | sprint | 30 m | 5/5 | 2614 | 10.2 | 1 | 3 | 1 | non | 0 | 2 | 0.250 | ✓ | 289 |
| sprint_20261119T172115Z_a562c112.json | PORTEN-BESSIN | sprint | sprint | 30 m | 5/5 | 3285 | 0.0 | 1 | 2 | 2 | non | 0 | 2 | 0.125 | ✓ | 290 |

## Échecs de rejeu (mode en ligne)

Aucun : les 35 trajectoires (7 captures × 5 graines) ont abouti.

## Échecs de rejeu (mode hors ligne)

Aucun : les 35 trajectoires hors ligne ont abouti.

## Comparaison en ligne / hors ligne (médiane par capture)

| Capture | long. (m) | min paire (m) | <30 m | crois. | interdits | déterm. ligne | déterm. hors ligne |
|---|---|---|---|---|---|---|---|
| circuit_20261122T083414Z_a2f6feae.json | 8345 → 7722 | 68.5 → 69.6 | 0 → 0 | 0 → 0 | 0 → 0 | ✗ | ✗ |
| circuit_20261122T084351Z_a63cd765.json | 2287 → 2276 | 42.5 → 65.8 | 0 → 0 | 0 → 0 | 0 → 0 | ✗ | ✗ |
| circuit_20261122T092812Z_5685384b.json | 8202 → 8331 | 88.7 → 93.0 | 0 → 0 | 0 → 0 | 0 → 0 | ✗ | ✗ |
| circuit_20261122T095424Z_7ca39337.json | 8392 → 7849 | 80.0 → 86.8 | 0 → 0 | 0 → 0 | 0 → 0 | ✗ | ✗ |
| sprint_20261119T164701Z_a530a9ea.json | 2606 → 2695 | 0.0 → 35.1 | 1 → 0 | 2 → 2 | 0 → 0 | ✗ | ✗ |
| sprint_20261119T171122Z_46871982.json | 2614 → 3020 | 10.2 → 0.0 | 1 → 1 | 1 → 2 | 0 → 0 | ✓ | ✗ |
| sprint_20261119T172115Z_a562c112.json | 3285 → 3255 | 0.0 → 0.0 | 1 → 1 | 2 → 2 | 0 → 0 | ✓ | ✓ |

## Totaux

- Trajectoires en ligne : **35** valides, 0 en erreur
- Temps cumulé des rejoues : **1.86 h**
- Déterminisme : **2/7** captures reproductibles à graine fixée
- Temps cumulé hors ligne : **1.49 h**
- Cache (avant → après préchauffage) :
  - circuit_20261122T083414Z_a2f6feae.json : hmc_npz 5 → 5, osm_json 6 → 6
  - circuit_20261122T084351Z_a63cd765.json : hmc_npz 5 → 5, osm_json 6 → 6
  - circuit_20261122T092812Z_5685384b.json : hmc_npz 5 → 5, osm_json 6 → 6
  - circuit_20261122T095424Z_7ca39337.json : hmc_npz 5 → 5, osm_json 6 → 6
  - sprint_20261119T164701Z_a530a9ea.json : hmc_npz 5 → 5, osm_json 6 → 6
  - sprint_20261119T171122Z_46871982.json : hmc_npz 5 → 6, osm_json 6 → 6
  - sprint_20261119T172115Z_a562c112.json : hmc_npz 6 → 7, osm_json 6 → 6
