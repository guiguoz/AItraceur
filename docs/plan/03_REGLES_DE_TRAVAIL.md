# 03 — Règles de travail pour Claude Code

Ces règles valent pour toutes les phases. En cas de conflit entre une phase et ce fichier, ce
fichier gagne ; en cas de doute, s'arrêter et demander au traceur.

## 1. Avant de commencer une phase

1. Lire ce fichier, puis le fichier de la phase en entier, puis les annexes qu'il cite.
2. Vérifier les prérequis de la phase (section « Prérequis »). S'il en manque un, s'arrêter.
3. Les numéros de ligne du plan datent du commit `60b624a`. **Chercher par nom** (fonction,
   constante) et non par numéro ; si le code a divergé du constat décrit, s'arrêter et le signaler
   avant de modifier quoi que ce soit. (Leçon reprise de lidar-o : vérifier qu'un constat hérité
   décrit encore l'état du code.)
4. Créer la branche `plan/pN-nom-court` à partir de `main` à jour.

## 2. Pendant la phase

- Suivre les étapes dans l'ordre. Une étape = un commit (ou quelques-uns), avec ses tests.
- Messages de commit en français, au format déjà utilisé dans le dépôt (`feat:`, `fix:`,
  `refactor:`, `docs:`, `test:`), avec le numéro d'étape : `fix(p1.3): transmettre l'arrivée au
  générateur`.
- Ne pas pousser, ne pas lancer `autopush.bat` / `autopush.sh`.
- En fin de phase, après le compte rendu (§5), demander au traceur : « Je fusionne la branche dans
  `main` ? ». Fusionner seulement sur un « oui » explicite (`git switch main`, `git merge` de la
  branche de phase, tests relancés sur `main`), puis supprimer la branche. Sans réponse, ne rien
  fusionner.
- Ne rien faire qui ne soit pas dans la phase. Une idée d'amélioration hors périmètre va dans le
  compte rendu, section « Remarques », pas dans le code.
- Si une étape se révèle impossible ou fausse : s'arrêter, expliquer, proposer une correction du
  plan. Ne pas contourner.

## 3. Tests

| Quoi | Commande (depuis la racine du dépôt) |
|------|--------------------------------------|
| Backend | `cd backend && python -m pytest tests -q` |
| Moteur v2 seul | `cd backend && python -m pytest tests/aitraceur -q` |
| Frontend | `cd frontend && npm test` |
| Lint frontend | `cd frontend && npm run lint` |

- Toute fonction nouvelle du moteur v2 a un test. Tout bug corrigé a un test qui échouait avant.
- Les tests du moteur v2 n'utilisent **que** des cartes synthétiques construites par
  `backend/tests/aitraceur/fixtures/` (définies en phases 2, 3 et 5). Aucun fichier `.ocd`, `.omap`,
  `.gpx` réel n'entre dans le dépôt (droits des cartographes, taille).
- Ne jamais désactiver, sauter ou assouplir un test pour faire passer une étape. Un test obsolète se
  supprime avec une ligne d'explication dans le commit.
- Aucun test ne fait d'appel réseau.

## 4. « Terminé » veut dire

Une phase est terminée quand **tout** ceci est vrai :

1. Tous les critères d'acceptation de la phase sont satisfaits, chacun avec sa preuve (sortie de
   commande, capture, chiffre).
2. Tous les tests passent ; leur nombre est noté et n'a pas baissé sans explication.
3. Le banc d'essai (phase 0) a été relancé si la phase le demande, et ses résultats sont consignés.
4. `docs/plan/REGISTRE.md` est à jour (voir §6).
5. `CLAUDE.md`, `README.md`, `ARCHITECTURE.md` ne contiennent aucune affirmation devenue fausse du
   fait de la phase.
6. Le compte rendu de phase est écrit (voir §5).

## 5. Compte rendu de fin de phase

Écrire `docs/plan/comptes-rendus/PN.md` avec exactement ces rubriques :

```
# Compte rendu — phase N
## Fait                 (étape par étape, avec l'identifiant du commit)
## Écarts au plan       (ce qui a été fait autrement, et pourquoi)
## Mesures              (tableau avant / après ; commande exacte pour reproduire)
## Registre             (entrées ajoutées ou modifiées dans REGISTRE.md)
## À tester à la main   (ce que le traceur doit vérifier dans l'application, pas à pas)
## Remarques            (idées hors périmètre, risques repérés)
```

## 6. Discipline de mesure

1. **Aucun poids, seuil ou paramètre ne change sans mesure au banc d'essai**, avant et après, sur
   les mêmes cartes et les mêmes graines.
2. Un chiffre sans la commande qui le reproduit n'existe pas.
3. Une mesure = au moins 5 graines par carte et par profil ; on rapporte la médiane et l'écart
   interquartile. Un effet est « établi » s'il dépasse l'écart interquartile sur au moins trois
   cartes ; sinon il est « non établi ».
4. Chaque exécution du banc écrit `run_metadata.json` : identifiant du commit, état du dépôt
   (propre ou non), instantané complet de la configuration, graines, versions des bibliothèques
   (modèle repris de `write_config_snapshot` et `_git_hash`, `lidar-o/src/qa.py`).
5. Le registre `docs/plan/REGISTRE.md` a trois rubriques — **Établi**, **Réfuté**, **À vérifier** —
   et chaque entrée porte une date, une preuve (commande ou fichier) et, si elle remplace une
   ancienne croyance, la mention de celle-ci. Les réfutations sont aussi précieuses que les
   confirmations : on ne les efface jamais.
6. Le score interne d'un moteur n'est jamais un indicateur. Les indicateurs sont calculés par
   `aitraceur/evalbench/metrics.py`, indépendant de tout moteur.

## 7. Phases lointaines : replanifier avant d'exécuter

Les phases 0 à 6 sont détaillées au niveau du fichier et de la fonction. Les phases 7 à 11 fixent
l'objectif, les interfaces, les portes de décision et les critères d'acceptation ; le code aura
changé quand on y arrivera. Au début de chacune :

1. Relire l'état réel du code concerné.
2. Écrire `docs/plan/PN_execution.md` : la liste des étapes au niveau fichier / fonction / test,
   dans le format des phases 0 à 6.
3. Le faire valider par le traceur avant d'écrire du code.

## 8. Interdits

- **Réseau** : le moteur v2 ne fait aucune requête réseau. Aucune nouvelle dépendance à un service
  en ligne. Les accès existants (Overpass, IGN, MapAnt) passent derrière le drapeau
  `AITRACEUR_ONLINE` (phase 1), éteint par défaut.
- **Payant** : aucune dépendance, aucun service, aucun modèle payant.
- **Symboles** : aucun numéro de symbole en dur hors de `backend/src/aitraceur/symbols/` et de ses
  tests. Un test d'architecture le vérifie (phase 2).
- **Règles de traçage** : aucune règle sans source. Chaque règle porte une citation
  (document, page ou paragraphe, extrait) tirée des PDF du dépôt, ou l'étiquette `implementation`
  si c'est un choix technique. Ne jamais inventer de référence ; si le texte ne dit rien, l'écrire.
- **Hasard** : dans le moteur v2, pas de `random.` ni de `numpy.random` globaux ; un générateur
  (`random.Random(seed)` ou `numpy.random.default_rng(seed)`) est passé explicitement. Pas de
  `hash()` de chaîne pour fabriquer une graine (utiliser `zlib.crc32`).
- **Dépendances du moteur** : `backend/src/aitraceur/**` n'importe ni `fastapi`, ni `sqlalchemy`,
  ni `src.services`, ni `src.api`. Un test d'architecture le vérifie.
- **Moteur v1** : seules les corrections listées en phase 1 et le « pont » de la phase 2 y touchent.
  Aucun réglage, aucune nouvelle fonctionnalité.
- **Erreurs silencieuses** : pas de `except Exception: pass` dans le code nouveau. Une erreur est
  soit traitée, soit remontée avec un message qui dit quoi faire.
- **Données du traceur** : ne jamais supprimer ni réécrire un fichier de données local (cartes,
  observations d'audit terrain, circuits enregistrés) sans demande explicite.

## 9. Conventions du moteur v2

- Python 3.11+, annotations de type partout, `dataclass(frozen=True)` pour les objets de données.
- Identifiants en anglais, commentaires et docstrings en français (comme le reste du dépôt).
- Unités dans les noms : `_m`, `_s`, `_deg`, `_s_per_m`. Jamais de nombre sans unité dans une
  signature.
- Coordonnées monde : `(x, y)` en mètres dans le système projeté de la carte, `y` vers le nord.
- Coordonnées grille : `(row, col)`, `row = 0` au nord ; le centre de la cellule `(r, c)` est
  `x = x0 + (c + 0.5)·res`, `y = y0 − (r + 0.5)·res`, `(x0, y0)` étant le coin nord-ouest.
- Sorties déterministes : listes triées, dictionnaires à clés triées à la sérialisation, flottants
  arrondis (0,01 m ; 0,1 s) dans les fichiers.
- Toute constante numérique du moteur vit dans un objet de configuration nommé et documenté, avec
  sa source (`source="ISOM 2017-2 §…"`, `source="Méthode fédérale p.6"` ou
  `source="implementation"`).

## 10. Mise en place dans le dépôt (faite en phase 0)

### 10.1 `CLAUDE.md`

Remplacer la section « Fitness GA — termes A→L » (fausse, voir constat C2) et ajouter en tête :

```markdown
## Plan en cours
Le projet suit le plan de `docs/plan/` (lire `00_LISEZ-MOI.md`).
Règles de travail : `docs/plan/03_REGLES_DE_TRAVAIL.md` — à lire avant toute modification.
État d'avancement : `docs/plan/comptes-rendus/`. Faits établis ou réfutés : `docs/plan/REGISTRE.md`.

## Deux moteurs
- Moteur v1 (en service) : `backend/src/services/generation/`. Gelé : corrections listées dans le
  plan uniquement. La sélection est faite par `_default_scoring` ; `evaluate_fitness` n'est qu'une
  télémétrie.
- Moteur v2 (en construction) : `backend/src/aitraceur/`. Ne dépend ni de FastAPI ni de `src.services`.
- `backend/src/aitraceur_proto/` : prototype de mars 2026, gelé, supprimé en phase 6.
```

### 10.2 Commande `/phase` (raccourci facultatif)

Claude Code charge les compétences de projet depuis `.claude/skills/<nom>/SKILL.md`. Créer
`.claude/skills/phase/SKILL.md` :

```markdown
---
name: phase
description: Exécute une phase du plan de docs/plan en respectant les règles de travail.
disable-model-invocation: true
---
Lis docs/plan/03_REGLES_DE_TRAVAIL.md en entier.
Puis exécute la phase $ARGUMENTS du plan (fichier docs/plan/ dont le nom contient « _P$ARGUMENTS_ »).
Respecte l'ordre des étapes. Arrête-toi à la fin de la phase, écris le compte rendu demandé au §5
des règles, et attends la relecture.
```

Usage : `/phase 2`.

### 10.3 Sous-agent « vérificateur »

Les sous-agents de projet sont des fichiers `.claude/agents/<nom>.md`. Créer
`.claude/agents/verificateur.md` :

```markdown
---
name: verificateur
description: Relit une phase terminée du plan AItraceur et vérifie chaque affirmation du compte rendu contre le code, les tests et le banc d'essai. À utiliser avant de déclarer une phase terminée.
tools: Read, Glob, Grep, Bash
---
Tu es relecteur. Tu n'écris pas de code.
Pour le compte rendu fourni : relance chaque commande citée, compare aux chiffres annoncés,
vérifie chaque critère d'acceptation de la phase, cherche les interdits du §8 des règles
(numéro de symbole en dur, règle sans source, hasard global, import interdit, except silencieux).
Rends une liste : conforme / non conforme / non vérifiable, avec la preuve.
```

Usage en fin de phase : « Utilise le sous-agent verificateur sur `docs/plan/comptes-rendus/P2.md`. »

## 11. Quand s'arrêter et demander

- Un prérequis manque, ou le code ne correspond pas au constat du plan.
- Un critère d'acceptation ne peut pas être atteint sans changer la conception.
- Une décision est irréversible ou touche des données du traceur.
- Une règle de traçage semble nécessaire mais aucun document du dépôt ne la porte.
- Une carte réelle contient un cas que le plan n'a pas prévu (norme non reconnue, structure à
  plusieurs niveaux, carte non géoréférencée).
