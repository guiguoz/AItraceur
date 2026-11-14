# Phase 11 — Produit : une application de bureau, hors ligne

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

> Phase « lointaine » : objectif, interfaces, portes et critères. Avant de coder, écrire
> `docs/plan/P11_execution.md` (règles de travail §7).

## But

1. Livrer AItraceur comme **un seul programme Windows** : un installateur, une icône, aucun
   terminal, aucun compte, aucune connexion requise (hypothèse H4).
2. **Retirer** ce que le moteur v2 a remplacé : moteur v1, anciennes tables, services en ligne,
   code mort. Le dépôt doit redevenir lisible par quelqu'un qui le découvre.
3. Fermer la boucle avec les logiciels du traceur : exporter les circuits vers OCAD, Purple Pen ou
   OpenOrienteering Mapper, imprimer.
4. Protéger les données du traceur : elles sont sur son PC, elles s'exportent, elles survivent aux
   mises à jour.

## Ce que le traceur verra

- Un installateur `AItraceur-x.y.z-setup.exe` ; au lancement, une fenêtre, sans terminal.
- Dans « Réglages » : le dossier des données, l'état de l'assistant local (installé ou non), le
  dossier du MNT, « exporter toutes mes données », « importer une sauvegarde ».
- Un export « Envoyer vers OCAD / Purple Pen » (IOF XML 3.0) et une impression du circuit sur la
  carte.
- Plus de commutateur « ancien / nouveau moteur ».

## Prérequis

- Porte K7 franchie (phase 6). Phases 7 à 10 terminées **ou** explicitement reportées par le
  traceur (une phase non faite ne bloque pas le produit, elle en limite les fonctions).

## Contexte vérifié (14 novembre 2026 — à relire au lancement)

- Aujourd'hui il faut lancer trois programmes (`start_all.bat`) : le serveur Python (port 8000),
  l'interface Vite (5173) et le service de tuiles Node (8089) ; `CLAUDE.md` l'écrit lui-même.
- `src-tauri/` existe : Tauri 2 (`tauri = "2.10.0"`, `tauri-plugin-log`), identifiant
  `com.glemi.aITRACEUR`, `frontendDist: ../frontend/dist`, aucun programme d'accompagnement
  (« sidecar ») déclaré, aucun serveur Python lancé.
- `services/map-importer/` (Express, port 8788, appelle `ocad2geojson` en ligne de commande) n'est
  appelé par aucun fichier du dépôt depuis le premier commit (`8625df9`, 2026-03-04).
- `ocad2geojson` est sous licence AGPL-3.0-or-later, comme AItraceur ; il sait aussi produire une
  image vectorielle (`ocadToSvg`) et un style MapLibre (`ocadToMapboxGlStyle`) : un rendu de la
  carte dans le navigateur est possible sans le service de tuiles, **à mesurer** (fidélité,
  vitesse sur une grande carte).
- L'export IOF XML 3.0 existe (`services/export/iof_exporter.py`) ; il ne sait rien des circuits
  du moteur v2.
- Le dossier `docs/` contient 17 PDF FFCO et IOF ; le traceur déclare détenir le droit de les
  diffuser (registre, E33) : ils peuvent être embarqués dans l'installateur.

## Conception

### 1. Architecture du programme installé

```
AItraceur.exe (Tauri 2)
 ├─ fenêtre : interface React construite (frontend/dist), servie par Tauri
 ├─ programme d'accompagnement : aitraceur-engine.exe (PyInstaller, mode dossier)
 │    lancé au démarrage sur 127.0.0.1, port libre choisi au lancement,
 │    jeton aléatoire exigé sur chaque requête, arrêté à la fermeture
 └─ données : %APPDATA%\AItraceur\  (DATA_DIR)
       maps\ corpus\ prefs\ dtm\ assistant\ logs\ settings.json
```

- Tauri lance le moteur (`bundle.externalBin`, extension `shell` de Tauri 2), attend `GET /health`,
  puis passe l'adresse et le jeton à l'interface. Une seule instance à la fois.
- Mode **dossier** de PyInstaller (et non fichier unique) : démarrage plus rapide, moins de faux
  positifs des antivirus.
- `multiprocessing.freeze_support()` en tête du point d'entrée du moteur : sans lui, les calculs en
  parallèle des phases 5 et 6 relancent le programme en boucle une fois empaqueté.
- Aucune requête vers l'extérieur. Exceptions explicites et désactivées par défaut : aucune. (Le MNT
  et l'assistant sont des fichiers ou des programmes locaux installés par le traceur.)
- Ollama n'est **pas** embarqué : l'application le détecte s'il est installé (phase 8).

### 2. Rendu de la carte : garder ou retirer le service de tuiles

| Option | Pour | Contre |
|--------|------|--------|
| A. Rendu dans le navigateur (`ocad2geojson` → MapLibre ou SVG) | un seul lecteur de carte (déjà dans le navigateur, phase 2) ; plus de Node ; `.omap` rendu de la même façon après conversion | fidélité des symboles complexes à vérifier ; vitesse sur une carte de forêt de plusieurs dizaines de milliers d'objets |
| B. Service de tuiles empaqueté (Node en exécutable unique) | rendu actuel, connu du traceur | un troisième programme ; ne lit pas `.omap` |

Décision par la porte P1 ci-dessous. Si A échoue, B.

### 3. Exports et impression — `aitraceur/io/export_iof.py`, `frontend/src/components/v2/PrintView.jsx`

- **IOF XML 3.0** (`CourseData`) : postes avec position en coordonnées géographiques **et** en
  millimètres sur la carte (`MapPosition`), circuits, ordre des postes, longueur, dénivelé (si
  phase 10). Reprendre ce qui est sûr dans `iof_exporter.py`, sur les objets du moteur v2.
- Essai obligatoire dans les logiciels du traceur : le fichier s'importe dans sa version d'OCAD et
  dans Purple Pen, et les postes tombent au bon endroit (registre, V17).
- **Impression** : circuit en surimpression sur la carte, à l'échelle, au format A4 ou A3, depuis
  la fenêtre d'impression du système (fichier PDF possible) ; légende des postes et fiche des
  définitions en version simple (numéro, élément, libellé en français).
- Écriture `.omap` des circuits : seulement si le traceur en a l'usage (OpenOrienteering Mapper
  gère des circuits par une extension) ; sinon hors périmètre.

### 4. Données du traceur

| Donnée | Où | Sauvegarde |
|--------|----|------------|
| Paquets de carte, terrains, catalogues (caches) | `maps\` | non : se recalculent |
| Corrections de symboles, décisions de drapeaux, zones de course, observations de terrain | `maps\<map_id>\*.json` | **oui** |
| Réponses de calage des niveaux | `levels_overrides.json` | **oui** |
| Préférences et comparaisons à l'aveugle | `prefs\*.jsonl` | **oui** |
| Circuits réels importés, traces GPX | `corpus\` | **oui** |
| Modèles appris, profil de vitesses | `models\`, `speed_profile.json` | oui (se réentraînent) |

- « Exporter toutes mes données » : une archive `.zip` des seules lignes « oui », avec un
  `manifest.json` (version de l'application, version de chaque format, date).
- Chaque format de fichier porte un champ `schema_version` ; toute évolution de format s'accompagne
  d'une fonction de migration et d'un test qui charge un fichier de la version précédente.
- Les observations de terrain gardées dans le `localStorage` du navigateur (étape 14b) sont
  importées une fois au premier lancement, puis le serveur fait foi.

### 5. Retraits

À faire **après** la porte K7, dans cet ordre, une étiquette git avant chaque retrait
(`avant-retrait-<nom>`), tests verts après chacun :

| Retrait | Contenu | Condition |
|---------|---------|-----------|
| Moteur v1 | `services/generation/` (dont `genetic_algo.py`), `ai_generator.py`, `_circuit_impl`, `_sprint_impl`, `/api/v1/generation/*`, le pont v1 et ses tests | K7 franchie |
| Ancien contrôleur | `services/controleur/` | phase 7 faite |
| Anciennes règles et tables | `services/rules/`, `placement_rules.json`, `ffco_categories.json`, `isom_semantics.json`, `isom_navigation_roles.json`, `ocad_semantics.json`, `control_descriptions.json` | phase 4 faite ; le test d'architecture « aucun numéro de symbole hors du registre » passe sans exception |
| CNN | `ocad_patch_scorer.py`, `HeatmapCache`, `control_scorer_cnn.onnx`, scripts Kaggle, `torch` et `torchvision` dans `requirements.txt` | porte CNN de la phase 9 non franchie (ou phase 9 non faite) |
| Services en ligne | OSM / Overpass, MapAnt, opentopodata, API d'altimétrie IGN, embeddings OpenAI, collecte RouteGadget et Vikazimut (selon V22) ; la collecte Livelox est déjà retirée (phase 1, étape 1.11) | — |
| Assistant v1 | `/api/v1/knowledge/*`, `local_rag.py`, `ai_assistant.py`, `rag_builder.py` | phase 8 faite ou reportée |
| Service inutilisé | `services/map-importer/` | — |
| Service de tuiles | `backend/tile-service/` | porte P1, option A |
| Archives | scripts d'expériences de mai, `Lora/` → `archive/` avec une note d'une ligne chacun | — |

Après les retraits : `main.py` ne contient plus que l'assemblage de l'application FastAPI (routes
dans `api/v2/`) ; le préfixe `/api/v2` est conservé tel quel (pas de renommage : il ne coûte rien et
évite de casser l'interface).

### 6. Documentation

Réécrire, en partant du code et non des anciens textes :

- `README.md` : ce que fait l'application, installation, premiers pas (une page) ;
- `CLAUDE.md` : architecture réelle, commandes, règles (reprendre `03_REGLES_DE_TRAVAIL.md`) — l'actuel
  décrit des termes A→L qui n'ont jamais piloté la génération (constat C2) ;
- `ARCHITECTURE.md` : la chaîne de `02_VISION_ARCHITECTURE.md` §3, à jour ;
- `docs/guide/` : guide du traceur en français (importer une carte, confirmer les symboles, choisir
  un niveau, construire un circuit, vérifier, exporter), captures d'écran comprises ;
- `CREDITS.md` : OpenOrienteering Mapper (jeux de symboles, GPL-3.0), lidar-o, ocad2geojson
  (AGPL-3.0-or-later), IGN (MNT LiDAR HD, Licence Ouverte 2.0), et les bibliothèques (annexe A4).

## Étapes (à détailler dans `P11_execution.md`)

1. Porte P1 (rendu) : prototype de rendu dans le navigateur sur trois cartes (une de sprint, deux
   de forêt dont la plus grande du traceur) ; mesures ; décision.
2. Retraits, dans l'ordre du tableau, chacun avec sa propre fusion.
3. Point d'entrée du moteur empaquetable (`backend/src/engine_main.py` : choix du port, jeton,
   `freeze_support`, journal dans `DATA_DIR\logs`) ; construction PyInstaller ; essai sur un PC
   Windows sans Python installé.
4. Tauri : lancement du moteur, attente de santé, passage du port et du jeton, arrêt propre ;
   installateur (NSIS ou MSI, celui que Tauri 2 produit sans outil payant).
5. Données : `schema_version`, migrations, export et import de sauvegarde, reprise du
   `localStorage`.
6. Exports IOF XML 3.0 et impression ; essais dans OCAD et Purple Pen.
7. Test « hors ligne » automatisé (ci-dessous) et essai réel câble débranché.
8. Documentation et `CREDITS.md`.
9. Essai grandeur nature (critère 6).

## Portes de décision

| Porte | Condition | Sinon |
|-------|-----------|-------|
| P1 rendu navigateur | sur les trois cartes : le traceur juge le rendu fidèle (aucun symbole faux ou manquant qui gêne le traçage) ; affichage initial ≤ 5 s et déplacement fluide sur la plus grande carte, sur son PC | option B : service de tuiles empaqueté |
| P2 installateur | installation, lancement, génération et export réussis sur un PC Windows sans Python ni Node, compte utilisateur sans droits d'administrateur | corriger avant toute diffusion |
| P3 données | une sauvegarde exportée par la version N se réimporte dans la version N + 1 sans perte (test automatisé) | pas de version N + 1 |

## Critères d'acceptation

1. Un double-clic lance l'application ; aucune fenêtre de terminal ; fermeture propre (aucun
   processus du moteur ne reste actif).
2. **Hors ligne** : un test lance tout le parcours (import d'un paquet, terrain, catalogue,
   propositions, contrôle, export) avec un garde qui fait échouer toute connexion réseau autre que
   `127.0.0.1` ; il passe. Et l'essai à la main, réseau coupé, réussit.
3. Les retraits sont faits ; `grep` ne trouve plus `genetic_algo`, `72600`, `TD1`, `overpass`,
   `openai` dans `backend/src` ni `frontend/src`.
4. Un fichier IOF XML exporté s'importe dans OCAD et dans Purple Pen avec les postes au bon endroit
   (écart ≤ 1 m), vérifié par le traceur.
5. Le tableau final des indicateurs K1 à K9 est publié dans `docs/plan/mesures/P11_bilan.md`, avec la
   commande qui le reproduit.
6. **Essai grandeur nature** : le traceur prépare avec l'application au moins un circuit réellement
   couru (entraînement de club ou course), le fait courir, et consigne les retours des coureurs.
   C'est le vrai critère de réussite du projet ; ses enseignements ouvrent le plan suivant.

## Hors périmètre

- macOS et Linux (Tauri les permet ; non testés, non promis).
- Signature de code de l'installateur : payante. Conséquence acceptée : Windows affiche un
  avertissement au premier lancement ; le guide explique comment le passer.
- Mise à jour automatique : demande un service en ligne. Les mises à jour se font en réinstallant ;
  les données sont dans `%APPDATA%` et survivent.
- Version web hébergée, comptes, partage de cartes entre utilisateurs.
- Circuits multiples partageant des postes, relais, papillons, définitions de postes complètes :
  plan suivant.

## Pièges

- Chemins Windows : espaces et accents (« Méthode Fédérale - Edition 2016.pdf »), chemins longs,
  séparateurs. Tout passe par `pathlib` ; un test crée `DATA_DIR` dans un dossier
  `C:\Users\Prénom Accentué\…` simulé.
- Un antivirus peut bloquer un exécutable PyInstaller fraîchement construit : préférer le mode
  dossier, ne pas compresser avec UPX, documenter la marche à suivre.
- Ne jamais écrire dans le dossier d'installation (droits) : tout va dans `DATA_DIR`.
- Le port fixe 8000 peut être pris par un autre programme : toujours un port libre choisi au
  lancement.
- Les PDF de `docs/` sont embarqués (droit confirmé, E33) et servis en local pour les liens
  « ouvrir à la page » ; un réglage permet de pointer vers un autre dossier quand une nouvelle
  édition paraît (et les citations de la phase 4 sont alors revérifiées par leur test).
- Les retraits se font un par un : un gros commit « suppression du v1 » rendrait toute régression
  introuvable.
