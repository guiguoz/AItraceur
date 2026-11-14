# Annexe A4 — Sources, licences, références

## 1. Documents officiels du dépôt

Abréviations utilisées dans tout le plan. Pages = pages du PDF (couverture = 1), sauf le RTS, cité
par sa numérotation imprimée « n/12 ».

| Abr. | Fichier (`docs/`) | Organisme | Usage dans le plan |
|------|-------------------|-----------|--------------------|
| MF | `Méthode Fédérale - Edition 2016.pdf` | FFCO | Règles T1–T17 par couleur, sprint p. 10-13 (A2, phases 4 et 6) |
| GC | `Guide de mise en place des circuits de couleur 2024.pdf` | FFCO | Six couleurs, distances par format (A2 §2 et §6) |
| RTS | `RTS_CO_(Ed.mai2025)_b6e41MU.pdf` — *Règles techniques et de sécurité en CO* | FFCO | Âges et temps, distances minimales, dénivelé (A2, phases 6 et 7) |
| TP | `TRACAGE PRINCIPES.pdf` | FFCO | Principes de traçage : qualité des interpostes, postes, lignes (phases 6 et 7) |
| TAP | `TRACAGE ASPECTS PRATIQUES.pdf` | FFCO | Types de lignes L1-L3, parcours vert, bleu, jaune (A1 §3, A2) |
| ISOM | `ISOM2017_2_FR_EN  (mars2022).pdf` | IOF (traduction FFCO) | Symboles, vitesses, dimensions minimales (A1, phases 3 et 5) |
| — | `ISOM2017_booklet-print_virallinen.pdf` | IOF | Référence de symboles (1re édition) |
| — | `IOF_Guidelines_for_Forest_Course_Planning_-_Jun_2020.pdf`, `IOF_Guidelines_for_Sprint_Course_Planning_-_Jun_2020.pdf`, `Course-planning-guidelines-Sprint-2020-upd-2022.pdf`, `Guidelines-for-Course-Planning_Sprint_IOF.pdf`, `2_Course_Planning.pdf`, `Appendix-A-Course-Planning-Principles.pdf` | IOF | Contexte international ; aucune règle de ce plan n'en dépend seule |
| — | `Guidelines-for-complex-urban-structures-last-update-2022-01-23.pdf` et sa traduction | IOF | Structures à plusieurs niveaux : référence pour leur modélisation future (hors plan) |
| — | `officials_handbook_orienteeringcourseplanning_practicalguidance.pdf` | — | Seule mention d'amas de postes (courses au score) : X03 |
| — | `PISTE_Swiss_Orienteering_Anleitung_2024_FINAL.pdf` | Swiss Orienteering | Non utilisé |

`docs controleur/` : `Mémento_du_Corps_Arbitral_(Ed.2023)`, `règles_techniques_et_de_sécurité_en_CO_(Ed.juin2023)` (édition
antérieure du RTS : le plan cite celle de mai 2025), `woc_manual_version_december-2019`,
`officials_handbook…` (doublon), et `20241209_WL_FeuerungskontrolleurIn_Fz.pdf`, **hors sujet**
(règlement suisse des contrôleurs de combustion) : à retirer du dépôt et du corpus (phase 1).

Non disponible : ISSprOM 2019 (valeur du passage minimal à vérifier, V03) ; « Guide du Traceur FFCO
2023 » cité par `ffco_categories.json` (V04). Droit de diffusion des PDF : V16.

## 2. Projets et données

| Source | Licence | Usage |
|--------|---------|-------|
| [OpenOrienteering Mapper](https://github.com/OpenOrienteering/mapper) — jeux de symboles `symbol sets/src/*.xmap`, tables `*.crt` | GPL-3.0 | Numéros, noms et types des symboles des quatre normes ; correspondances entre normes (A1). Seules des données factuelles en sont tirées. |
| [lidar-o](https://github.com/guiguoz/lidar-o) (même auteur) | celle du dépôt | Gabarit `assets/ISOM 2017-2_10000.omap`, noms de symboles FFCO réels (`scripts/mappings/*.yaml`), conversion `.omap` (`src/omap_writer.py`), convergence des méridiens (`src/init_terrain.py`), discipline de mesure (`src/qa.py`, `docs/bilan_v0.md`). |
| [ocad2geojson](https://github.com/perliedman/ocad2geojson) 2.1.20 | AGPL-3.0-or-later | Lecture des fichiers OCAD (navigateur et Node). |
| [StreetO](https://github.com/jcundill/streeto) | voir le dépôt | Exemple existant de génération de circuits urbains (consulté en juillet). |
| MNT LiDAR HD, IGN — [fiche data.gouv.fr](https://www.data.gouv.fr/datasets/mnt-lidar-hd) | Licence Ouverte 2.0 (mention de l'IGN obligatoire) | Relief, phase 10. |
| Livelox — [conditions d'utilisation](https://www.livelox.com/UserAgreement) (7 août 2026), [API publique](https://www.livelox.com/Documentation/Api), [robots.txt](https://www.livelox.com/robots.txt) | collecte automatique interdite hors API autorisée ; droits des cartes et circuits réservés aux organisateurs | Phase 1 (retrait du client), phase 9 §7 (voies permises) ; registre E34. |

## 3. Bibliothèques (licences à reconfirmer à l'ajout de chaque dépendance)

| Bibliothèque | Licence | Phase |
|--------------|---------|-------|
| numpy, scipy, scikit-image, shapely | BSD | 3, 5 |
| pyproj | MIT | 2 |
| PyMuPDF (déjà dans `requirements.txt`) | AGPL-3.0 | 4, 8 |
| xgboost (déjà présent) | Apache-2.0 | 9 |
| numba (si solveur anisotrope) | BSD-2 | 10 |
| OR-Tools (optionnel) | Apache-2.0 | après 6 |
| SDK Python `mcp` | MIT | 8 |
| FastAPI, React, Leaflet | MIT, MIT, BSD-2 | existant |
| MapLibre GL JS (si rendu navigateur) | BSD-3 | 11 |
| Tauri 2 | MIT ou Apache-2.0 | 11 |
| PyInstaller | GPL-2.0 avec exception pour les programmes produits | 11 |
| Ollama (installé par le traceur, non embarqué) ; modèles : licence propre à chaque modèle | MIT ; variable | 8 |

Toute bibliothèque ajoutée doit être compatible avec l'AGPL-3.0 du projet et figurer dans
`CREDITS.md`.

## 4. Références consultées (web, novembre 2026)

- Code de la propriété intellectuelle, art. L122-5-3 (fouille de textes et de données) : la copie à
  des fins de fouille est permise sur des œuvres licitement accessibles, sauf opposition de l'auteur,
  « notamment par des procédés lisibles par machine » pour les contenus publiés en ligne —
  traduction consultée : <https://french-business-law.com/french-legislation-art/article-l122-5-3-of-the-french-intellectual-property-code>

- Albert & Sárközy, « Route planning on orienteering maps with least-cost path analysis »,
  *Proceedings of the ICA*, 2021 — coûts par classe de végétation, grille de 1 m, calage sur des
  itinéraires d'experts : <https://ica-proc.copernicus.org/articles/4/4/2021/ica-proc-4-4-2021.pdf>
- COBRA (Chalmers) — itinéraires sur grille de 10 m, allure par symbole et pente :
  <https://mldv.m2.chalmers.se/cobra/about>
- Borrego Ramos, « Optimal route planning for orienteering: branch-and-cut with terrain cost
  surfaces and fatigue », 2026 (itinéraire du coureur, pas traçage) :
  <https://optimization-online.org/2026/08/optimal-route-planning-for-orienteering-branch-and-cut-with-terrain-cost-surfaces-and-fatigue/>
- Comparatifs de modèles locaux et d'appels d'outils (indicatifs, à refaire en phase 8) :
  <https://localaimaster.com/blog/best-ollama-models-tool-calling>,
  <https://insiderllm.com/guides/function-calling-local-llms/>
