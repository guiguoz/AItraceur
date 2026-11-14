# AItraceur — Plan de refondation (novembre 2026)

Ce dossier remplace les plans de juillet 2026 (conservés dans `archive-2026-07/`, à ne plus exécuter).
Il est écrit pour être exécuté par Claude Code dans le dépôt `guiguoz/AItraceur`, phase par phase.

## Principe fondateur (à ne jamais perdre de vue)

> « C'est la qualité de l'interposte qui conditionne l'emplacement de la balise, et non l'inverse. »
> — Guillaume Lemiègre, traceur

Les *Principes de traçage* de la FFCO disent la même chose (§3.4.1) : « Les parcours entre postes sont
les parties les plus importantes d'un parcours d'orientation et déterminent sa qualité. »
Tout ce plan en découle : le moteur doit d'abord **lire la carte sans erreur**, puis **proposer des
interpostes**, et seulement ensuite en déduire les postes.

## Les quatre hypothèses (réponses du traceur, 14 novembre 2026)

| # | Hypothèse | Réponse | Conséquence |
|---|-----------|---------|-------------|
| H1 | Matériel du traceur. | **PC Windows avec carte graphique NVIDIA GeForce RTX 3060** (l'hypothèse « pas de carte graphique » était fausse). Mémoire vidéo exacte à relever : 12 Go pour la version de bureau la plus courante, 8 Go pour une variante, 6 Go en version portable. | Phase 8 : assistant local confortable (palier « carte graphique 12 Go »). Phase 9 : le CNN peut se réentraîner sur le PC, sans Kaggle. Phases 3 à 6 : sans effet (calculs sur le processeur). |
| H2 | Forêt et ville avancent ensemble ; la ville d'abord pour les deux bugs signalés (vert olive, bâtiments en propriété privée). | Confirmée. | Jeux d'essai de ville en premier. |
| H3 | Le traceur possède des circuits tracés à la main sur certaines de ses cartes. | Confirmée. | La phase 9 se fait en entier. |
| H4 | Produit final : une application qui tourne entièrement sur le PC, sans compte ni service en ligne. | Confirmée. | Phase 11 telle qu'écrite. |

Le traceur déclare aussi détenir le droit de diffuser les PDF du dossier `docs/` (registre, E33).
Apprendre des circuits publiés sur Livelox en parcourant le site automatiquement : exclu par les
conditions d'utilisation du site ; voies permises en phase 9 (§7) et registre E34-E35.

## Ordre de lecture

| Fichier | Contenu | Lecteur |
|---------|---------|---------|
| `01_ETAT_DES_LIEUX.md` | Ce que fait réellement le code aujourd'hui, preuves à l'appui ; verdict sur les plans de juillet. | Traceur + Claude Code |
| `02_VISION_ARCHITECTURE.md` | Cible à long terme, architecture, choix techniques (agent ? modèle ? autre ?), feuille de route. | Traceur + Claude Code |
| `03_REGLES_DE_TRAVAIL.md` | Règles d'exécution pour Claude Code, définition de « terminé », discipline de mesure. | Claude Code |
| `10_P0…` à `21_P11…` | Une phase par fichier, à exécuter dans l'ordre. | Claude Code |
| `A1_symboles_reference.md` | Table de référence des symboles (4 normes) et de leurs rôles. | Claude Code (phase 2) |
| `A2_referentiel_niveaux_ffco.md` | Les six couleurs FFCO, règles T1–T17, citations de page. | Claude Code (phase 4) |
| `A3_registre_etabli_refute.md` | Registre initial : ce qui est établi, réfuté, à vérifier. | Tous |
| `A4_sources.md` | Documents, licences, références. | Tous |
| `mesures_2026-11/` | Scripts qui reproduisent les mesures citées en preuve dans le registre (étanchéité de la grille, durées, tables de symboles, citations). | Claude Code |

## Feuille de route en une page

| Phase | Titre | Ce que le traceur voit à la fin | Dépend de |
|-------|-------|--------------------------------|-----------|
| P0 | Socle et mesure | Rien de visible ; un banc d'essai qui chiffre les défauts actuels. | — |
| P1 | Assainissement du moteur actuel | Fin de la « triangulation » récompensée, arrivée respectée, couleurs dans le bon ordre, erreurs sprint affichées. | P0 |
| P2 | Carte et symboles | L'application dit quelle norme elle a reconnue et ce qu'elle a compris de chaque symbole ; plus de poste dans l'olive, quelle que soit la norme. | P0 |
| P3 | Terrain et atteignabilité | Calque « franchissable / interdit / inaccessible » ; plus de poste sur un bâtiment enclavé en propriété privée. | P2 |
| P4 | Niveaux FFCO | Choix du niveau par couleur (vert → noir) et par format, conforme à la Méthode fédérale. | P2 |
| P5 | Temps et itinéraires | Pour deux points quelconques : itinéraires, temps, choix réel ou non, lignes suivies, point d'attaque, ligne d'arrêt. | P3, P4 |
| P6 | Moteur « jambes d'abord » | Propositions d'interpostes puis de circuits, par niveau ; comparaison à l'aveugle avec l'ancien moteur. | P5 |
| P7 | Contrôleur et explications | Rapport de contrôle où chaque règle cite sa source ; explication en français de chaque interposte. | P6 |
| P8 | IA locale | Assistant qui cite la page du règlement ; brief en langage naturel ; agent optionnel. | P7 |
| P9 | Apprentissage | Le moteur apprend des circuits réels et des préférences du traceur ; vitesses calées sur ses traces GPS. | P6 |
| P10 | Relief et OMAP | Dénivelé réel (MNT LiDAR HD), éléments de relief, lecture des fichiers OpenOrienteering Mapper. | P5 |
| P11 | Produit | Un installateur Windows, un seul programme, hors ligne ; ancien moteur retiré. | P6–P10 |

Les phases P0 à P3 corrigent les deux bugs signalés à l'origine. P4 à P6 construisent le nouveau
moteur. P7 à P11 sont le long terme ; leurs fichiers fixent les interfaces et les portes de décision,
pas le détail ligne à ligne (le code aura changé d'ici là — voir `03_REGLES_DE_TRAVAIL.md` §7).

## Comment lancer le plan (VS Code)

**Une fois :**

1. Installer l'extension « Claude Code » (éditeur : Anthropic) dans VS Code et s'y connecter avec son
   compte Claude.
2. Glisser le dossier `plan` (dézippé) dans le dossier `docs` du projet AItraceur.

**Puis, une phase après l'autre :** ouvrir une nouvelle conversation Claude Code et écrire
« Exécute docs/plan/10_P0_socle_et_mesure.md ». Claude Code lit seul les règles et les annexes,
s'occupe de git, demande ce dont il a besoin, montre son compte rendu à la fin et demande s'il peut
enregistrer le travail dans `main`. Ensuite, nouvelle conversation et fichier suivant : `11_P1…`,
`12_P2…`, jusqu'à `21_P11…`. Seuls les fichiers `10` à `21` se donnent ; les autres sont lus par
Claude Code.

## Glossaire minimal

| Terme | Sens dans ce plan |
|-------|-------------------|
| Interposte, jambe | Parcours entre deux postes consécutifs. |
| Site | Emplacement possible de poste : un élément de la carte sur lequel on peut poser une balise. |
| Ligne directrice (main courante) | Élément linéaire à peu près parallèle à la direction de course (Principes §3.7). |
| Ligne d'arrêt | Élément linéaire à peu près perpendiculaire, derrière le poste (Principes §3.7). |
| Point d'attaque | Élément remarquable situé avant le poste (Principes §3.7). |
| Norme | Spécification cartographique : ISOM 2017-2, ISSprOM 2019, ISOM 2000, ISSOM 2007. |
| Moteur v1 | L'algorithme génétique actuel (`backend/src/services/generation/genetic_algo.py`). |
| Moteur v2 | Le moteur « jambes d'abord » construit par les phases 2 à 6. |
| Paquet de carte | Fichier JSON neutre décrivant une carte (symboles + objets en mètres), contrat unique entre l'interface et le moteur. |
| Banc d'essai | Outil de mesure reproductible (phase 0). |
