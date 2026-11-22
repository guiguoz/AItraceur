# Phase 4 — Niveaux FFCO

> **Pour Claude Code** : le traceur lance cette phase par une seule phrase (« Exécute ce
> fichier »). Avant toute chose, lis `docs/plan/03_REGLES_DE_TRAVAIL.md` en entier — il prime
> sur ce fichier —, puis les fichiers et annexes que cette phase cite. Termine par le compte
> rendu et la question de fusion (règles §2 et §5).

## But

Donner au moteur la **définition officielle** de ce qu'on a le droit de proposer à un coureur de
chaque niveau : six couleurs en forêt, trois en sprint, chacune décrite par des paramètres
mesurables, chacun rattaché à sa source (document, page, citation) ou marqué « choix du plan ».

C'est la réponse à la question « un bon interposte H10 n'est pas un bon interposte H21 » : après
cette phase, « bon pour un niveau vert » a une définition écrite que le moteur peut appliquer
(phases 5 et 6) et que le traceur peut lire et corriger.

## Ce que le traceur verra

- Un sélecteur **couleur × format** (vert → noir ; longue distance, moyenne distance, sprint), à
  la place de « TD1 à TD5 ».
- Une **fiche de niveau** : les règles de la couleur choisie, chacune avec sa citation et sa page.
- Sur la carte, les sites utilisables pour la couleur choisie (un circuit vert n'a droit qu'aux
  jonctions de chemins et aux bâtiments).
- Une courte **revue de calage** : dix questions sur les valeurs que la FFCO ne chiffre pas.

## Prérequis

- Phase 3 terminée (sites, avec `obviousness` et `line_classes`).
- Lire `A2_referentiel_niveaux_ffco.md` en entier : c'est la matière de cette phase.

## Contexte vérifié

- Le niveau voyage aujourd'hui sous la forme `technical_level: "TD3"` (`main.py` l.2115 et l.4038 ;
  `App.jsx` l.20-30). L'échelle TD1–TD5 est britannique ; la phase 1 a seulement remis les couleurs
  dans le bon ordre et posé une correspondance provisoire couleur → TD pour le moteur v1.
- `placement_rules.json` décrit ses blocs en couleurs britanniques (« Blanc/Jaune », « Vert/Violet ») ;
  `Lora/mondial_tracage_QR_v4.jsonl` (54 questions-réponses) enseigne la même échelle au modèle
  `ffco-iof-v7`.
- La FFCO définit six niveaux par couleur (RTS §3.2.1, p. 8/12), décrits par la Méthode fédérale
  (p. 4 à 9 pour la forêt, p. 10 à 13 pour le sprint) ; le Guide des circuits de couleur donne les
  distances par format (p. 4-5). Les couleurs des tableaux de la Méthode ont été vérifiées sur le
  rendu des pages. Les citations de l'annexe A2 ont été contrôlées mot à mot contre le texte des
  PDF le 12 novembre 2026.
- Les tableaux de la Méthode sont sur **deux colonnes** : une extraction de texte naïve entrelace
  la colonne « compétences » et la colonne « règles de traçage ». Toute vérification automatique de
  citation doit porter sur des fragments tenant sur une seule ligne du PDF.

## Étapes

### 4.1 — Le fichier des niveaux

**Fichier** : `backend/src/aitraceur/levels/ffco_levels.json`, saisi à la main depuis l'annexe A2.

```jsonc
{
  "version": 1,
  "citations": {
    "MF_T1": { "doc": "Méthode Fédérale - Edition 2016.pdf", "page": 4,
               "quote": "T1 : Le parcours doit être tracé sur un terrain comportant des éléments de planimétrie évidents et reliés entre eux. Les postes sont toujours sur des lignes identiques et aux changements de direction. Un seul itinéraire possible. Le point d'attaque est confondu avec le poste. Choisir des postes faciles : bâtiment, jonction ou croisement de chemins",
               "check": ["Un seul itinéraire possible", "Choisir des postes faciles"] },
    "RTS_3_2_1": { "doc": "RTS_CO_(Ed.mai2025)_b6e41MU.pdf", "page": 9, "printed_page": "8/12",
                   "quote": "…", "check": ["temps de course maximum préconisé"] }
  },
  "forest": {
    "vert": {
      "difficulty_fr": "très facile", "t_codes": ["T1", "T2", "T3"],
      "params": {
        "site_max_obviousness":  { "value": 2,      "source": "MF_T1" },
        "site_on_line":          { "value": "L1",   "source": "MF_T1" },
        "handrail_classes":      { "value": ["L1"], "open_counts": true, "source": "TAP_lignes_1" },
        "max_offline_m":         { "value": 0,      "source": "MF_T1" },
        "max_unmarked_turns_leg":{ "value": 1,      "source": "plan" }
      }
    }
  },
  "sprint":  { "bleu": { "s_code": "S1", "params": { "max_turns_leg": { "value": 3, "source": "MF_S1" } } } },
  "formats": {
    "ld":     { "emphasis": "choix",               "distance_kind": "effort", "distance_km": { "vert": [2, 3], "bleu": [3, 4], "jaune": [4, 5], "orange": [5, 8], "violet": [8, 12], "noir": [8, 12] }, "source": "GC_4_1" },
    "md":     { "emphasis": "recherche_de_postes", "distance_kind": "effort", "distance_km": { "vert": [2, 2.5], "bleu": [2, 3], "jaune": [2, 4], "orange": [3, 4], "violet": [4, 6], "noir": [4, 6] }, "source": "GC_4_2" },
    "sprint": { "emphasis": "choix_sous_pression", "distance_kind": "course", "distance_km": { "bleu": [1, 1.8], "jaune": [1.8, 2.8], "orange": [2.3, 3.8] }, "source": "GC_4_3" }
  }
}
```

Règles de saisie :

- **tous** les paramètres des tableaux A2 §4 et §5, pour chaque couleur, y compris les « sans
  objet » (`"value": null`) ;
- `source` vaut une clé de `citations`, ou `"plan"`, ou plus tard `"traceur, AAAA-MM-JJ"` ;
- une citation = le texte exact du PDF (fautes comprises), la page du PDF, et un ou plusieurs
  fragments `check` courts tenant sur une ligne.

Ajouter au même endroit les **longueurs d'interposte** à vol d'oiseau, que la FFCO ne chiffre pas
(« parcours partiels courts » pour les débutants, TP §2.3.3.1) — `source: "plan"` :

| | sprint | moyenne distance | longue distance |
|---|--------|------------------|-----------------|
| vert | — | 60 – 300 m | 60 – 300 m |
| bleu | 30 – 250 m | 80 – 450 m | 80 – 450 m |
| jaune | 30 – 350 m | 80 – 700 m | 100 – 1 200 m |
| orange | 30 – 450 m | 80 – 900 m | 100 – 2 000 m |
| violet, noir | — | 60 – 900 m | 100 – 2 500 m |

**Tests** (`backend/tests/aitraceur/test_levels_data.py`) :

- le fichier se charge ; six couleurs en forêt, trois en sprint, trois formats ;
- chaque paramètre a une `source`, et toute source autre que `plan` ou `traceur, …` existe dans
  `citations` ;
- **citations exactes** : pour chaque citation, le texte de la page indiquée du PDF de `docs/`
  (extrait avec PyMuPDF, déjà dans `requirements.txt`) contient chaque fragment `check`, après normalisation
  (minuscules, apostrophes et guillemets unifiés, ponctuation et espaces réduits). Un PDF manquant
  fait échouer le test ;
- valeurs témoins : `forest.vert.max_offline_m == 0` ; `forest.bleu.max_offline_m == 100` ;
  `forest.orange.attack_max_m == 200` ; `sprint.bleu.max_turns_leg == 3` ;
  `sprint.jaune.max_turns_leg == 5` ; `formats.ld.distance_km.orange == [5, 8]` ;
  `formats.sprint.distance_km.bleu == [1, 1.8]`.

### 4.2 — Le modèle

**Fichiers** : `aitraceur/levels/ffco.py`, `aitraceur/levels/formats.py`.

```python
class Color(str, Enum):
    VERT = "vert"; BLEU = "bleu"; JAUNE = "jaune"; ORANGE = "orange"; VIOLET = "violet"; NOIR = "noir"

class Format(str, Enum):
    SPRINT = "sprint"; MD = "md"; LD = "ld"

@dataclass(frozen=True)
class Citation:
    key: str; doc: str; page: int; quote: str; printed_page: str | None = None

@dataclass(frozen=True)
class Param:
    name: str; value: object; source: str          # clé de citation, "plan" ou "traceur, <date>"
    citation: Citation | None

@dataclass(frozen=True)
class LevelSpec:
    color: Color; fmt: Format
    difficulty_fr: str
    codes: tuple[str, ...]                          # ("T1","T2","T3") ou ("S1",)
    params: Mapping[str, Param]
    distance_km: tuple[float, float]; distance_kind: str    # "effort" | "course"
    leg_length_m: tuple[float, float]
    emphasis: str                                   # "choix" | "recherche_de_postes" | "choix_sous_pression"
    def get(self, name: str): ...                   # valeur ; KeyError explicite si le paramètre n'existe pas

def load_levels(path: Path | None = None) -> "Levels": ...
def level_spec(color: Color, fmt: Format) -> LevelSpec: ...
def max_color_for_age(age: int) -> Color: ...       # RTS §3.2.1 : ≤10 vert, 11-12 bleu, 13-14 jaune, 15-16 orange, sinon noir
ORDER = (Color.VERT, Color.BLEU, Color.JAUNE, Color.ORANGE, Color.VIOLET, Color.NOIR)
```

`level_spec` lève `ValueError` avec un message citant la source pour les combinaisons qui
n'existent pas : vert, violet ou noir en sprint (« le sprint n'a que trois niveaux : bleu, jaune,
orange — Guide des circuits de couleur, p. 5 »).

**Tests** (`test_levels.py`) : `level_spec(VERT, LD).get("max_offline_m") == 0` ;
`level_spec(BLEU, SPRINT).codes == ("S1",)` ; `level_spec(VERT, SPRINT)` lève `ValueError` ;
`max_color_for_age(10) == VERT`, `(12) == BLEU`, `(14) == JAUNE`, `(16) == ORANGE`, `(17) == NOIR` ;
`ORDER` est croissant en difficulté ; `level_spec(ORANGE, MD).distance_km == (3, 4)`.

### 4.3 — Index des lignes

**Fichier** : `aitraceur/sites/lines.py`. Petit outil partagé avec la phase 5.

```python
@dataclass(frozen=True)
class LineRef:
    geom: "shapely.LineString"; line_class: str; family: str; sym_num: int; from_area_edge: bool

class LineIndex:
    """Toutes les lignes porteuses d'une classe (L1, L2, L3) : objets linéaires, et bords des
    surfaces dont la sémantique a une classe de ligne. Recherche par shapely.STRtree."""
    def __init__(self, pkg: MapPackage, reading: MapReading): ...
    def nearest(self, xy, classes: Collection[str], max_dist_m: float) -> tuple[LineRef, float] | None: ...
    def within(self, geom, classes: Collection[str]) -> list[LineRef]: ...
```

Les bords de surface sont découpés aux sommets et **privés des tronçons situés sur le bord de la
zone cartographiée** (le bord de la carte n'est pas une lisière).

**Tests** : sur `bois()`, `nearest((310, 250), {"L1"}, 50)` renvoie CHEMIN_NS à 10 m ;
`nearest((150, 300), {"L1"}, 50)` renvoie `None` ; `nearest((400, 300), {"L2"}, 5)` renvoie le bord
ouest de CLAIRIERE ; aucune ligne le long du bord de la carte.

### 4.4 — Sites admissibles par niveau

**Fichier** : `aitraceur/levels/sites_filter.py`.

```python
@dataclass(frozen=True)
class SiteVerdict:
    allowed: bool
    rule: str | None          # nom du paramètre qui refuse
    detail_fr: str            # "évidence 4 > 2 autorisé en vert (Méthode fédérale p. 4)"

def site_verdict(site: Site, spec: LevelSpec, lines: LineIndex) -> SiteVerdict: ...
```

Règles, dans l'ordre : `site_max_obviousness` ; `site_on_line` (le site doit porter la classe exigée
dans `line_classes`, ou être un coin de bâtiment — « bâtiment, jonction ou croisement de chemins ») ;
`site_max_dist_to_line_m` (distance du site à la ligne autorisée la plus proche) ; en sprint,
`site_max_similar_nearby` (comparé à `Site.n_similar`) et `multi_level`. Le refus cite toujours la source du paramètre.

**Tests** sur `bois()` :

| Site | vert | bleu | jaune |
|------|------|------|-------|
| croisement (300, 200) | admis | admis | admis |
| coin de CLAIRIERE (400, 250) | refusé `site_on_line` | admis (évidence 2 ; le site est sur une ligne L2) | admis |
| ROCHER_2 (350, 260) | refusé `site_max_obviousness` | refusé `site_max_obviousness` | admis |
| ROCHER_1 (150, 300) | refusé | refusé | admis |

Sur `village()` : coin sud de B2 et FONTAINE_O admis en bleu, jaune et orange (en sprint,
l'évidence ne refuse rien). Carte construite dans le test : cinq arbres (417) alignés tous les 10 m
dans PARC_E → chacun a `n_similar >= 2`, refusé en bleu et jaune par `site_max_similar_nearby`,
admis en orange.

### 4.5 — API et interface

**Fichiers** : `backend/src/api/v2/levels.py`, `frontend/src/components/v2/LevelPicker.jsx`,
`frontend/src/components/v2/LevelSheet.jsx`.

| Route | Rôle |
|-------|------|
| `GET /api/v2/levels` | Tous les niveaux, citations résolues ; pour chaque couleur de forêt, `v1_technical_level` (table provisoire de la phase 1, désormais servie par cette seule route). |
| `GET /api/v2/levels/{format}/{color}` | Une `LevelSpec`. 404 explicite si la combinaison n'existe pas. |
| `GET /api/v2/maps/{map_id}/sites?color=…&format=…` | Les sites de la phase 3, enrichis de `allowed` et `detail_fr`. |
| `PUT /api/v2/levels/params` | Corps `{ "format", "color", "name", "value" }` : réponse du traceur à la revue de calage ; écrit `{DATA_DIR}/levels_overrides.json` avec `source: "traceur, <date>"`. Refusé (409) pour un paramètre dont la source est une citation. |

Interface :

- `LevelPicker` : format d'abord (sprint, MD, LD), puis les couleurs existantes pour ce format ;
  l'état de l'application porte désormais `color` et `format`. Pour le moteur v1, `technical_level`
  est déduit par `v1_technical_level` ; **aucun** autre endroit du frontend ne connaît « TD ».
- `LevelSheet` : la fiche du niveau, une ligne par paramètre — libellé en français, valeur, source ;
  un clic sur une source FFCO ouvre le PDF à la page (`/docs/<fichier>#page=<n>`, les PDF étant
  servis en fichiers statiques par FastAPI).
- Calque des sites : pastille pleine pour un site admis à ce niveau, creuse sinon, motif au survol.
- Si une catégorie d'âge est choisie (H10, D12…) et que la couleur dépasse `max_color_for_age` :
  bandeau d'avertissement citant le RTS.

**Tests** : client HTTP — `GET /levels/sprint/vert` → 404 ; `GET /levels/ld/orange` contient
`attack_max_m` avec sa citation ; `PUT` sur `max_turns_leg` de S1 → 409 ; `PUT` sur
`site_max_dist_to_line_m` → 200 et la valeur survit à un rechargement. Vitest : `LevelPicker` ne
propose que trois couleurs en sprint.

### 4.6 — Revue de calage avec le traceur

`backend/tools/calage.py` imprime les dix questions de l'annexe A2 §7 avec la valeur de départ ; le
traceur répond (ou garde la valeur) ; chaque réponse passe par `PUT /api/v2/levels/params`. Pour les
questions qui se jugent sur carte (1, 2, 3, 9), ouvrir d'abord le calque des sites de deux cartes
réelles à la couleur concernée, pour que le traceur voie l'effet de la valeur.

Consigner les réponses dans `docs/plan/mesures/P4_calage.md` et, pour chacune, une entrée au
registre (« établi par le traceur le … »).

### 4.7 — Mise à l'écart de l'échelle TD

- En tête de `placement_rules.json`, de `ffco_categories.json` et de `ffco_rules_engine.py` :
  « Échelle TD1–TD5 : vocabulaire interne du moteur v1 (échelle britannique). Le référentiel FFCO est
  dans `aitraceur/levels/`. Ne pas réutiliser. »
- Test d'architecture (ajout à `test_architecture.py`) : aucune chaîne `TD1` … `TD5` ni
  `technical_level` dans `backend/src/aitraceur/` ni dans `backend/src/api/v2/` hors
  `v1_bridge.py` et `levels.py` (champ `v1_technical_level`).
- `frontend/src/__tests__/noTdScale.test.js` : `TD[1-5]` n'apparaît plus dans `frontend/src` hors
  tests.

## Critères d'acceptation

1. Tous les tests de 4.1 à 4.7 passent, dont le contrôle des citations contre les PDF.
2. Aucun paramètre sans source ; les dix paramètres « choix du plan » de l'annexe A2 §7 ont reçu la
   réponse du traceur (valeur confirmée ou corrigée).
3. Dans l'application, le traceur choisit « bleu, moyenne distance », lit la fiche, ouvre la page 5
   de la Méthode fédérale depuis la fiche, et voit sur une carte de forêt réelle les sites admis.
4. Sur une carte de forêt réelle, le nombre de sites admis par couleur est consigné
   (`docs/plan/mesures/P4_sites_par_niveau.md`) ; s'il y a moins de 15 sites admis en vert, le
   signaler au traceur : la carte se prête peut-être mal à un circuit vert, ou une classe de ligne
   est à revoir (question 9).

## Hors périmètre

- Conformité d'une **jambe** à un niveau (phase 6, à partir des mesures de la phase 5).
- Allures et temps (phase 5 ; calage en phase 9).
- Correspondance catégorie ↔ circuit au-delà des plafonds d'âge du RTS.

## Pièges

- Ne pas « arrondir » une citation pour qu'elle passe le test : relire la page, raccourcir le
  fragment `check`, garder la citation exacte.
- Les règles T de la forêt et celles du sprint portent les mêmes noms (T1, T2, T3) dans la Méthode
  et n'ont rien à voir : le code dit `S1`, `S2`, `S3` pour le sprint.
- Un paramètre absent pour une couleur n'est pas « zéro » : `null` veut dire « sans objet », et le
  code qui le lit doit le traiter explicitement.
- La couleur d'un circuit est un **plafond** de difficulté, pas une moyenne : une seule jambe
  orange dans un circuit bleu le rend non conforme.
