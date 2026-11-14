# Mesures du 10 au 12 novembre 2026 — scripts de preuve

Ces scripts sont les preuves des entrées E12 à E16, E24 à E26 du registre (`../A3_registre_etabli_refute.md`).
Ils ne font pas partie de l'application. À la phase 0, copier ce dossier dans `docs/plan/mesures_2026-11/`.

Dépendances : `numpy`, `scipy`, `scikit-image` (0.26 lors des mesures), `shapely` 2.

| Dossier | Script | Mesure | Entrée du registre |
|---------|--------|--------|--------------------|
| `rasterisation/` | `leak.py` | Étanchéité d'un trait selon la demi-largeur de tampon (400 traits aléatoires) | E12 |
| | `seal.py` | Bâtiments qui se touchent par un coin : fuites en rastérisation au centre, effet d'un rebouchage des diagonales | E13 |
| | `eroded.py` | Rastérisation prudente : fuites au coin et largeur de ruelle conservée, à 0,25, 0,5 et 1 m | E14 |
| | `alley.py` | Ruelles en rastérisation au centre, 8- et 4-connexité, de 0,5 à 2 m | E15 |
| | `bench_mcp.py`, `bench2.py` | Durées : composantes connexes, champs de temps `MCP_Geometric`, tracé | E16 |
| `symboles/` | `gen_a1.py` | Génère les tables de sémantique ISOM 2017-2 et ISSprOM 2019 (`semantics.json`) et vérifie la couverture contre les jeux de symboles de référence (`symtables.json`, extrait des fichiers `.omap`/`.xmap` d'OpenOrienteering Mapper et du gabarit de lidar-o) | E25 |
| | `gen_old.py` | Simule la génération des tables ISOM 2000 et ISSOM 2007 par les correspondances `.crt` d'OpenOrienteering ; liste les exceptions. `OOM_DIR` = clone de `github.com/OpenOrienteering/mapper` | E26 |
| `citations/` | `check_quotes.py` | Vérifie mot à mot des fragments de citation contre le texte des PDF de `docs/` (`PDFTXT_DIR` = dossier des textes extraits par `pdftotext`, un fichier `.txt` par PDF, même nom) | E24 |

Les mesures ont été faites sur une machine de test (un cœur). Les durées sont à refaire sur le PC du
traceur (V12). Les tirages aléatoires ont des graines fixes : les comptes de fuites se reproduisent
à l'identique.

`quotes_a2.txt` contient les fragments contrôlés avant correction de l'annexe A2 : quelques lignes
ressortent « DIFF » parce que la citation de l'annexe a été rectifiée depuis (fautes du PDF
reproduites). Le contrôle définitif est le test de la phase 4 (étape 4.1).
