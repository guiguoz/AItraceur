# Phase 7 — Contrôleur et explications

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

> Phase « lointaine » : ce fichier fixe l'objectif, les interfaces, les portes et les critères.
> Avant de coder, écrire `docs/plan/P7_execution.md` (règles de travail §7).

## But

1. Un **contrôleur** qui juge n'importe quel circuit — produit par le moteur ou dessiné par le
   traceur, en ville comme en forêt — et dont **chaque règle cite sa source**.
2. Des **explications en français** de chaque interposte, fabriquées à partir des mesures, sans
   modèle de langage.

## Ce que le traceur verra

- Un rapport de contrôle par circuit : bloquants, avertissements, informations ; pour chaque ligne,
  la mesure, la limite, la règle citée, et un lien vers la page du document.
- Sous chaque jambe, deux ou trois phrases : ce qu'elle demande au coureur et pourquoi elle est là.
- Le contrôle fonctionne aussi en forêt (aujourd'hui : sprint seulement, constat C9).

## Prérequis

Phase 6 terminée (porte K7 franchie).

## Contexte vérifié (10 novembre 2026 — à relire au lancement)

- `ControleurSprint` (`backend/src/services/controleur/controleur.py`, 889 lignes) porte 19 contrôles
  C01 à C20 ; il n'est appelé que par la génération sprint (`main.py` l.4523). Les sources qu'il
  déclare sont vagues ou invérifiables : « IOF Sprint Guidelines §3.1 », « FFCO Règles Sécurité §12 »,
  « calibration Phase 0 », et, pour C16, un « §4.5 » qui n'existe pas (constat C5).
- `ControleurIssue` a déjà la bonne forme : `code`, `severity`, `control_index`, `rule_reference`.
- Les mesures de jambe (phase 5), la conformité (phase 6.1) et les règles de circuit (phase 6.5)
  existent : le contrôleur n'a rien à recalculer, seulement à présenter et à compléter.

## Conception

### Registre des règles — `aitraceur/rules/registry.py`

```python
@dataclass(frozen=True)
class Rule:
    id: str                      # "R03"
    title_fr: str
    applies: "RuleScope"         # formats, couleurs, objet jugé : "poste" | "jambe" | "circuit"
    severity: str                # "bloquant" | "avertissement" | "information"
    citation: Citation | None    # même type que les niveaux (phase 4)
    source: str                  # clé de citation, ou "plan"

@dataclass(frozen=True)
class Finding:
    rule_id: str; severity: str
    where: tuple[str, ...]       # identifiants de sites ou de jambes
    measured: object; limit: object
    message_fr: str

def check_course(course: Course, ctx: LegContext, spec: LevelSpec) -> list[Finding]: ...
```

**Règle d'or, vérifiée par un test** : une règle dont la `source` est `"plan"` ne peut pas être
`bloquant`. C'est le garde-fou contre une nouvelle règle inventée (l'ancien C16 valait 15 % de la
note sprint sans aucune source).

Les citations vivent dans le même fichier que celles des niveaux et passent le même test
d'exactitude contre les PDF.

### Règles de départ

| Id | Règle | Gravité | Source |
|----|-------|---------|--------|
| R01 | Deux postes à moins de 30 m à vol d'oiseau (forêt) | bloquant | RTS p. 8/12 |
| R02 | Deux postes sur éléments de même nature à moins de 60 m (forêt) | bloquant | RTS p. 8/12 |
| R03 | Sprint : deux postes à moins de 15 m à vol d'oiseau ou de 25 m de course | bloquant | RTS p. 8/12 |
| R04 | Poste en zone interdite, infranchissable ou inaccessible | bloquant | TP §3.4.2 p. 8 ; RTS §3.2.1 (interdictions des propriétaires) |
| R05 | Jambe non conforme au niveau (une ligne par paramètre violé, chacune avec sa propre source) | bloquant si la source du paramètre est une citation ; avertissement si « plan » | A2 |
| R06 | Retour sur ses pas au poste (entrée et sortie par le même cheminement) | avertissement | TP §3.5.5 p. 10 |
| R07 | Itinéraire tentant à travers une zone interdite : gain ≥ 20 % si l'interdit était franchissable | avertissement | TP §3.4.2 p. 8 — « éviter les parcours entre postes qui encourageraient les compétiteurs à franchir des zones interdites ou dangereuses » ; seuil : plan |
| R08 | Dénivelé positif > 4 % de la longueur, par l'itinéraire le plus logique | avertissement | TP §3.11.6 p. 17 ; RTS p. 7/12 — actif à partir de la phase 10 |
| R09 | Temps estimé au-delà du maximum préconisé pour la couleur | avertissement | RTS §3.2.1 |
| R10 | Longueur hors de la fourchette indicative du format | information | GC p. 4-5 |
| R11 | Circuit vert : plus de deux changements de ligne en cours de jambe | bloquant | MF T3 |
| R12 | Circuit violet : trop peu de postes sans ligne d'arrêt | avertissement | MF T13 ; proportion : plan |
| R13 | Même interposte couru dans les deux sens | avertissement | RTS §3.2.1 — « que des itinéraires partiels entre 2 postes ne soient pas proposés dans les 2 sens » |
| R14 | Croisements d'itinéraires entre jambes non consécutives | information | TP p. 17 — le croisement « doit se justifier » |
| R15 | Plus de deux postes dans un rayon de 60 m (sprint) ou 150 m (forêt) | avertissement | plan (indicateur K2) |
| R16 | Liaison dernier poste → arrivée : rappel du balisage obligatoire | information | TP §3.6 p. 10 |
| R17 | Jambe traversant une structure à plusieurs niveaux | avertissement | A1 §3.3 |
| R18 | Objets à symbole non confirmé à moins de 20 m d'un poste ou sur un itinéraire | avertissement | plan |
| R19 | Zone `saisonnier`, voie ferrée ou route à circulation traversée sans décision du traceur | avertissement | A1 §3.3 |

R15 montre la différence entre le **style** du générateur (qui évite les amas par construction) et
le **règlement** : le contrôleur ne peut pas refuser le circuit d'un traceur pour une règle qu'aucun
texte ne porte.

### Sort des anciens contrôles

| Ancien | Devenir |
|--------|---------|
| C02 (trop proches) | R01, R02, R03 |
| C08 (zone interdite) | R04 |
| C01 (retour sur ses pas) | R06 |
| C07 (dénivelé) | R08 |
| C06 (temps), C03, C04, C05 (longueurs, nombre de postes) | R09, R10 ; les bornes de longueur de jambe ne sont pas des règles FFCO → information |
| C10, C13, C17 (type d'élément) | R05 (`site_*`) |
| C14, C15 (point d'attaque, ligne d'arrêt) | R05 (`attack_max_m`, `catching`) |
| C11, C18, C19, C20 (choix d'itinéraire, main courante) | R05 (`route_choice`, `handrail_fastest_forbidden`) ; leurs seuils « calibration Phase 0 » disparaissent |
| C12 (jambes parallèles) | à instruire à la replanification : chercher une source dans les documents ; sans source, information |
| C16 (amas de désorientation) | supprimé en phase 1 ; ne revient pas |

### Explications — `aitraceur/rules/explain.py`

```python
def explain_leg(leg: LegFacts, a: Site, b: Site, spec: LevelSpec, interest: Interest) -> list[str]: ...
def explain_course(course: Course, findings: Sequence[Finding]) -> list[str]: ...
```

Phrases construites par gabarits à partir des mesures — jamais de texte libre :

> « 3 → 4 : 420 m à vol d'oiseau, environ 3 min 10. Deux itinéraires à 6 % d'écart : à gauche par le
> chemin (510 m), à droite à travers la clairière (455 m, 120 m hors ligne). Point d'attaque : la
> jonction de chemins, 80 m avant le poste. Ligne d'arrêt : le ruisseau, 40 m derrière. Conforme au
> niveau jaune. »

Règles d'écriture : une phrase par fait ; les nombres arrondis (10 m, 10 s, 1 %) ; le vocabulaire
du glossaire ; rien qui ne soit dans `LegFacts` ; pour un refus, la règle et sa source.

## Étapes (à détailler dans `P7_execution.md`)

1. Registre, règles R01 à R19, test de la règle d'or, test d'exactitude des citations.
2. `check_course` branché sur `POST /api/v2/maps/{map_id}/courses/check` (créé en phase 6) ; le
   rapport remplace la sortie brute de conformité.
3. `explain.py` et ses gabarits ; tests par cas (une jambe à itinéraire unique, à deux itinéraires,
   refusée, en sprint avec changements de direction).
4. Interface : `ControlReport.jsx` (rapport groupé par gravité, lien vers la page du PDF,
   surbrillance des postes ou jambes concernés) ; explications dans `LegCard`.
5. Contrôle des circuits du moteur v1 par le nouveau contrôleur (via le pont) : le rapport est le
   même pour les deux moteurs ; `ControleurSprint` n'est plus appelé que pour sa boucle de
   corrections automatiques, tant que le moteur v1 existe.
6. Passage en revue, avec le traceur, du rapport sur cinq de ses circuits réels déjà courus.

## Portes de décision

- **Faux positifs** : sur les circuits réels du traceur (courus, donc réputés valables), tout
  « bloquant » est examiné. Un bloquant injustifié est un défaut du contrôleur ou de la lecture de
  carte, à corriger avant de livrer. Cible : zéro bloquant injustifié sur cinq circuits.
- **Explications** : le traceur relit vingt explications ; chacune doit être exacte (aucun fait
  faux) — c'est le critère — et utile (il l'aurait dit lui-même). Moins de 18 exactes sur 20 :
  retour aux mesures de la phase 5, pas aux gabarits.

## Critères d'acceptation

1. Chaque règle a une source ; aucune règle « plan » n'est bloquante (test).
2. Rapport de contrôle disponible en ville et en forêt, pour les deux moteurs et pour un circuit
   dessiné à la main.
3. Portes ci-dessus franchies et consignées.
4. `rule_reference` ne contient plus de référence invérifiable dans le code du moteur v2.

## Hors périmètre

- Reformulation par un modèle de langage (phase 8) : les explications de cette phase sont la
  **matière** que le modèle aura le droit de reformuler, jamais d'inventer.
- Définitions de postes IOF (grille de symboles) : après le plan.
- Corrections automatiques d'un circuit dessiné par le traceur : on signale, on ne retouche pas.

## Pièges

- Un contrôleur trop sévère est aussi inutile qu'un contrôleur laxiste : un traceur qui voit dix
  avertissements douteux n'en lit plus aucun. D'où la porte « faux positifs ».
- « Recommandé » dans un texte officiel se traduit par avertissement, pas par bloquant (le dénivelé
  de 4 % est une recommandation dans le RTS).
- Ne pas recopier les anciens seuils de `controleur_rules.json` : leur origine est inconnue.
