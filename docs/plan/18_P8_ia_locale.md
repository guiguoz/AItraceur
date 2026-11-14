# Phase 8 — IA locale : recherche citée, brief, agent

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

> Phase « lointaine » : objectif, interfaces, portes et critères. Avant de coder, écrire
> `docs/plan/P8_execution.md` (règles de travail §7) — et **revérifier l'état de l'art** : les
> modèles locaux changent tous les trois mois.

## But

Ajouter une couche de langage **autour** du moteur, entièrement locale et gratuite :

1. répondre aux questions de règlement **en citant le document et la page** ;
2. transformer un brief écrit en français en paramètres du moteur ;
3. (option) reformuler les explications de la phase 7 ;
4. (option) un agent qui enchaîne quelques outils du moteur, et un serveur MCP qui expose ces
   mêmes outils.

Rappel de la décision d'architecture (`02_VISION_ARCHITECTURE.md` §6) : le modèle de langage ne
place aucun poste, ne calcule aucun itinéraire, ne juge aucune jambe. Il lit, il traduit, il
reformule. **Tout fonctionne sans lui** : s'il est absent ou éteint, l'application garde ses
formulaires, ses explications par gabarits et une recherche documentaire par mots.

## Ce que le traceur verra

- Une question — « à quelle distance minimale deux postes de sprint ? » — et une réponse courte
  suivie de l'extrait exact, du nom du document et de la page, cliquable.
- Un champ « décris ton circuit » : « un jaune moyenne distance d'environ 3 km, départ au parking,
  en gardant mes postes 4 et 5 » → le formulaire se remplit ; il valide ou corrige.
- Un indicateur clair : « assistant local actif (modèle …) » ou « assistant non installé ».

## Prérequis

Phase 7 terminée. Matériel du traceur (H1, 14 novembre 2026) : carte graphique NVIDIA GeForce
RTX 3060. Relever d'abord sa mémoire vidéo exacte :
`nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv`.

## Contexte vérifié (10 novembre 2026 — à relire au lancement)

- `services/knowledge_base/local_rag.py` : recherche par `sentence-transformers` sur
  `backend/data/pdf_knowledge.jsonl` (2 395 extraits, **sans numéro de page**) et sur 54
  questions-réponses (`Lora/mondial_tracage_QR_v4.jsonl`), puis appel d'un modèle ajusté
  `ffco-iof-v7` par Ollama. `sentence-transformers` n'est pas dans `requirements.txt`.
- 141 des 2 395 extraits viennent d'un PDF hors sujet,
  `docs controleur/20241209_WL_FeuerungskontrolleurIn_Fz.pdf` (contrôle d'installations de
  chauffage, en allemand). La phase 1 les a retirés du fichier ; le manifeste ci-dessous empêche
  qu'ils reviennent.
- Le modèle ajusté et son jeu de questions enseignent l'échelle TD1–TD5 comme si elle était
  française (constat C6).
- `ai_assistant.py` essaie d'abord OpenAI (service payant en ligne), puis le modèle local, puis un
  mode de démonstration : contraire à « gratuit et local ».
- Ollama expose en local `/api/chat` (messages, `tools`, `format` = schéma JSON pour forcer la
  **forme** de la sortie) et `/api/embed`. Le schéma garantit la forme, pas la justesse des valeurs.
- Comparatifs consultés en novembre 2026 : les petits modèles locaux tiennent un ou deux appels
  d'outils, rarement plus de trois enchaînés ; familles alors citées : Qwen 3.x, Gemma 4,
  gpt-oss 20B, Mistral Small 24B. **Indicatif** : le choix se fait par nos propres jeux d'essai
  (ci-dessous), pas par réputation.
- Les tableaux de la Méthode fédérale sont sur deux colonnes (phase 4) : l'extraction doit se faire
  colonne par colonne, sinon les extraits mélangent compétences et règles de traçage.

## Conception

### Base documentaire — `aitraceur/assistant/corpus.py`

- **Manifeste** `docs/MANIFESTE.json` : pour chaque PDF retenu — fichier, titre, organisme, édition,
  langue, `colonnes` (1 ou 2), `autorite` (`ffco`, `iof`, `autre`). Seuls les documents du manifeste
  sont indexés ; le PDF hors sujet n'y figure pas.
- Extraction page par page ; un extrait ne franchit jamais une page ; taille visée 600 à 1 200
  caractères, coupure aux paragraphes. Chaque extrait porte `doc`, `page`, `titre_section` (dernier
  titre rencontré), `texte`.
- Sortie : `{DATA_DIR}/assistant/corpus.jsonl`, reconstruite par
  `python -m src.aitraceur.assistant.corpus build`.

### Recherche — `aitraceur/assistant/search.py`

```python
@dataclass(frozen=True)
class Passage:
    id: str; doc: str; page: int; section: str; text: str; score: float

def search(question: str, k: int = 5) -> list[Passage]: ...
```

- Socle : recherche par mots (BM25, implémentation locale d'une soixantaine de lignes), sur texte
  normalisé (minuscules, accents conservés, lemmatisation légère par suffixes). Aucun modèle requis.
- Option : plongements par Ollama (`/api/embed`), fusion des deux classements par rangs réciproques.
  Activée seulement si elle franchit la porte G1 mieux que le socle.
- Priorité aux documents `ffco` à score voisin : c'est le règlement qui s'applique au traceur.

### Réponse citée — `aitraceur/assistant/answer.py`

```python
@dataclass(frozen=True)
class Answer:
    text: str                           # 1 à 4 phrases
    quotes: tuple[Passage, ...]         # extraits EXACTS, affichés tels quels
    grounded: bool                      # False → « Je ne trouve pas cela dans les documents du dossier. »
```

1. `search` → cinq passages numérotés.
2. Le modèle reçoit la question et les passages, avec pour consigne de ne répondre que d'après eux,
   et renvoie un JSON `{ "reponse": str, "passages": [int] }` (schéma imposé, température 0).
3. Vérifications par le code : les numéros cités existent ; si la liste est vide, ou si la réponse
   contient un nombre absent des passages cités, `grounded = False`.
4. L'interface affiche la réponse **et les extraits exacts tirés du corpus** : le texte d'une
   citation ne sort jamais du modèle.

Sans modèle : l'interface affiche directement les cinq passages.

### Brief — `aitraceur/assistant/brief.py`

```python
def parse_brief(text: str, context: BriefContext) -> CourseBrief | Clarification: ...
```

Le modèle remplit un JSON au schéma de `CourseBrief` (couleur, format, longueur, nombre de postes,
postes à garder, zones à éviter). Le code valide : combinaison couleur × format existante (A2),
longueur dans une plage plausible, numéros de postes existants. Toute valeur invalide ou absente
devient une question au traceur (`Clarification`), jamais une supposition. Le brief validé
pré-remplit le formulaire ; **rien ne se lance sans le clic du traceur**.

### Reformulation (option) — `aitraceur/assistant/rephrase.py`

Entrée : les phrases de `explain_leg` (phase 7). Sortie : un paragraphe plus fluide. Garde-fou : tout
nombre et tout nom d'élément de la sortie doivent figurer dans l'entrée ; sinon on garde le texte
des gabarits.

### Outils, agent, MCP — `aitraceur/assistant/tools.py`, `agent.py`, `mcp_server.py`

Une seule liste d'outils, en lecture seule sauf mention, servie de deux façons :

| Outil | Effet |
|-------|-------|
| `list_maps`, `map_reading` | cartes connues ; norme et symboles à confirmer |
| `inspect_leg(map, a, b, color, format)` | `LegFacts` et explication (phases 5 et 7) |
| `best_legs_from(map, site, color, format)` | mode pas à pas (phase 6) |
| `generate_courses(map, brief)` | propositions (phase 6) — demande confirmation dans l'application |
| `alternatives_at(map, course, index)` | « un autre poste ici » |
| `check_course(map, course, color, format)` | rapport de contrôle (phase 7) |
| `search_rules(question)` | passages cités |

- **Agent** (`agent.py`) : boucle `/api/chat` avec `tools`, **trois appels d'outils au plus** par
  message du traceur ; chaque résultat d'outil s'affiche tel que le moteur l'a produit (carte,
  rapport) ; le modèle n'ajoute qu'une phrase de liaison. Désactivé par défaut ; activé seulement si
  la porte G4 est franchie avec le modèle installé.
- **Serveur MCP** (`mcp_server.py`, SDK Python `mcp`, transport stdio) : expose les mêmes outils.
  Premier usage : **Claude Code pendant le développement** (inspecter une jambe, lancer le banc,
  lire un rapport sans passer par l'interface) — déclarer le serveur dans `.mcp.json` à la racine
  du dépôt. Second usage : tout client MCP local. Il ne nécessite aucun modèle local.

### Client du modèle — `aitraceur/assistant/llm.py`

Client HTTP minimal d'Ollama sur `localhost` : `chat(messages, schema=None, tools=None)`,
`embed(texts)`, `health()`. Modèle : `AITRACEUR_LLM_MODEL` (vide = pas de modèle). Délai maximal,
erreurs explicites, aucune solution de repli en ligne.

### Paliers de matériel

Le palier du traceur est en gras (RTX 3060 de 12 Go ; si sa carte n'a que 8 Go, palier du dessus).

| Machine | Ce qui est activé | Taille de modèle visée |
|---------|-------------------|------------------------|
| 8 Go de mémoire, pas de carte graphique | recherche par mots, gabarits, formulaires | aucun modèle |
| 16 Go de mémoire, pas de carte graphique | + réponses citées et brief (réponses en 10 à 40 s) | 4 à 8 milliards de paramètres, quantifié 4 bits |
| carte graphique 8 Go | + reformulation | 7 à 12 milliards |
| **carte graphique 12 à 16 Go** | **+ agent** | **7 à 14 milliards, quantifiés 4 bits, entièrement en mémoire vidéo (réponses en quelques secondes) ; au-delà, une partie du modèle déborde en mémoire centrale et les réponses ralentissent nettement** |
| carte graphique 24 Go | confort | 20 à 30 milliards |

Ollama utilise la carte NVIDIA sans réglage particulier sous Windows (pilote à jour). Le modèle
retenu est **le plus petit qui franchit les portes** sur la machine du traceur, mesuré par
`backend/tools/eval_llm.py --model <nom>`, qui imprime le tableau des quatre portes et le débit.

## Étapes (à détailler dans `P8_execution.md`)

1. Manifeste (sans le PDF hors sujet), extraction par page et par colonne, corpus.
2. Jeux d'essai, écrits **avant** le code et relus par le traceur :
   `tests/assistant/questions.jsonl` (30 questions, avec document et page attendus),
   `briefs.jsonl` (30 briefs, avec le JSON attendu), `scenarios.jsonl` (10 dialogues d'agent, avec
   les appels d'outils attendus).
3. Recherche par mots ; porte G1.
4. Client Ollama ; réponse citée ; porte G2. Brief ; porte G3.
5. Serveur MCP et sa déclaration pour Claude Code.
6. Interface : `AiChatPanel.jsx` rebranché sur `/api/v2/assistant/*` ; champ de brief ; indicateur
   d'état.
7. Options : reformulation ; agent (porte G4).
8. Retraits : appel à OpenAI, dépendance à `ffco-iof-v7`, `sentence-transformers` s'il n'est plus
   utilisé ; `Lora/` déplacé dans `archive/` avec une note ; routes `/api/v1/knowledge/*` marquées
   obsolètes (supprimées en phase 11).

## Portes de décision

| Porte | Mesure | Seuil |
|-------|--------|-------|
| G1 recherche | le bon document et la bonne page figurent parmi les 5 premiers passages | ≥ 24 questions sur 30 |
| G2 réponse | réponse exacte **et** page citée exacte ; aucune règle inventée (relecture du traceur) | ≥ 24 sur 30, et zéro invention |
| G3 brief | JSON exactement attendu, ou demande de précision quand le brief est ambigu | ≥ 27 sur 30 |
| G4 agent | scénario mené au bout avec les bons outils, en trois appels au plus | ≥ 8 sur 10 |

Une porte non franchie désactive la fonction correspondante ; elle ne bloque pas les autres. G1 se
franchit sans aucun modèle : la recherche citée existe donc sur toutes les machines.

## Critères d'acceptation

1. Assistant éteint : toute l'application fonctionne ; la recherche documentaire renvoie des
   passages avec leur page.
2. Aucune requête ne sort de la machine (vérifié en coupant le réseau).
3. Chaque fonction activée a franchi sa porte sur la machine du traceur ; le tableau est au compte
   rendu, avec le modèle retenu et son débit.
4. Le serveur MCP répond à `inspect_leg` et `check_course` depuis Claude Code.

## Hors périmètre

- Ajuster (« fine-tuner ») un modèle : abandonné — fragile, opaque, à refaire à chaque nouveau
  modèle de base, et le jeu de données existant enseigne une échelle fausse.
- Faire juger la qualité d'un circuit par le modèle : c'est le rôle des règles (phase 7), du
  traceur (K7) et du modèle de classement (phase 9).
- Vision par ordinateur sur l'image de la carte : le moteur lit les objets, pas les pixels.

## Pièges

- Une réponse fluide et fausse est pire qu'une absence de réponse : d'où `grounded`, et l'affichage
  des extraits exacts.
- Le schéma JSON force la forme : un modèle peut renvoyer `"couleur": "vert"` pour un sprint. La
  validation par le code est obligatoire.
- Un agent qui enchaîne dix appels sur un petit modèle dérive : le plafond de trois appels n'est
  pas négociable sans une nouvelle mesure de G4.
- Ne pas indexer les questions-réponses de `Lora/` : elles contiennent l'échelle TD.
