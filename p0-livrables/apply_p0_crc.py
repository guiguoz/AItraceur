#!/usr/bin/env python3
"""Met à jour docs/plan/comptes-rendus/P0.md avec les faits de l'étape 0.9.

Rend le compte rendu à jour : inventaire réel des captures, écart au gabarit
§0.9, mesures du banc, entrées de registre, incident de banc consigné.

Usage :
    python apply_p0_crc.py <racine du dépôt>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def section(md: str, header: str) -> tuple[int, int]:
    m = re.search(rf"^{re.escape(header)}\s*$", md, re.M)
    if not m:
        raise SystemExit(f"Section introuvable : {header}")
    start = m.start()
    nxt = re.search(r"^#{2,3} ", md[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(md)
    return start, end


def replace_section(md: str, header: str, new_text: str) -> str:
    """Remplace une section. Idempotent : si l'ancien titre a disparu mais que le
    nouveau est déjà en place, le document est renvoyé tel quel."""
    try:
        start, end = section(md, header)
    except SystemExit:
        nouveau = new_text.strip().splitlines()[0].strip() if new_text.strip() else ""
        if nouveau and re.search(rf"^{re.escape(nouveau)}\s*$", md, re.M):
            return md
        raise
    return md[:start] + new_text.rstrip("\n") + "\n\n" + md[end:]


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    p = root / "docs" / "plan" / "comptes-rendus" / "P0.md"
    md = p.read_text(encoding="utf-8")

    mesures = (root / "docs" / "plan" / "mesures" / "P0_synthese.md")
    synth = mesures.read_text(encoding="utf-8") if mesures.exists() else ""
    # tableau « Mesures par capture » de la synthèse : en-tête + séparateur +
    # toutes les lignes de données (la synthèse en produit une par capture).
    tableau = "_(mesures non disponibles)_"
    m = re.search(r"^##\s+Mesures par capture.*$", synth, re.M)
    if m:
        rows = []
        for line in synth[m.end():].splitlines():
            if line.startswith("|"):
                rows.append(line)
            elif rows:
                break
        if rows:
            tableau = "\n".join(rows)

    # ── 0.8 : l'instrument de mesure ────────────────────────────────────────
    md = replace_section(md, "### 0.8 — Rejouer : `replay_v1.py` et `run.py`", """### 0.8 — Rejouer : `replay_v1.py` et `run.py`
- `backend/src/aitraceur/evalbench/replay_v1.py` : `replay(capture_path, seed) → ReplayResult` ; adaptateurs `_extract_circuit_points` et `_extract_sprint_points`.
- `backend/src/aitraceur/evalbench/run.py` : CLI `python -m src.aitraceur.evalbench.run v1 --captures ... --seeds ... --out ...` ; produit `results.jsonl`, `summary.md`, `determinism.json`, `run_metadata.json`.
- Fixtures `circuit_sample.json` / `sprint_sample.json` + **8 tests** `test_extract_points.py` — tous passent.
- **Correctif du 22/11/2026 (`632603f`, voir E48)** : l'adaptateur de circuit lisait `controls` comme une liste de paires `[lng, lat]`, alors que `ai_generator.py` produit des dicts `{"x", "y", …}`. Les quatre captures de forêt échouaient donc au rejeu (`KeyError: 0`). La fixture `circuit_sample.json` était écrite dans le format supposé : les tests passaient en validant le bug. Adaptateur aligné sur le format réel, fixture réécrite, **8/8 tests**.""")

    # ── 0.9 : le fait ───────────────────────────────────────────────────────
    md = replace_section(md, "### 0.9 — Ligne de base sur cartes du traceur", """### 0.9 — Ligne de base sur cartes du traceur

**Fait.** Sept captures produites les 19 novembre 2026 (sprints) et le 22 novembre 2026
(forêts), puis rejouées par le banc en ligne et hors ligne.

Inventaire réel, et correspondance fichier ↔ carte ↔ profil : `docs/plan/mesures/P0_captures.md`.

| Type | Captures |
|---|---|
| sprint (3) | Bayeux, Dôme, Porten-Bessin |
| forêt MD H21E (3) | Forêt de Caen, Kûti (Estonie), Ste Anne II |
| forêt couleur Jaune (1) | Forêt de Caen |

Le banc a rejoué les sept captures, cinq graines chacune, dans les deux modes, et a produit
les huit artefacts de `docs/plan/mesures/` (`P0_baseline_*` et `P0_baseline_offline_*`).

#### Écart au gabarit §0.9 du plan

Le plan demande « au minimum deux cartes de sprint (**dont Caen**) et trois de forêt (parmi
airelles, cerisy, grochot, llose, montmirel, steanne) ».

| Attendu par le gabarit | Réel | Écart |
|---|---|---|
| un sprint **Caen** | Bayeux, Dôme, Porten-Bessin | **manquant** — aucun sprint Caen dans l'inventaire |
| au moins 2 sprints | 3 | dépassé |
| 3 forêts, dont une de la liste (airelles, cerisy, grochot, llose, montmirel, **steanne**) | 4 forêts : Forêt de Caen (×2), **Kûti** (Estonie), Ste Anne II | **Ste Anne II** est la seule de la liste ; Forêt de Caen (×2) et Kûti sont des substituts |
| — | Kûti est **hors France** | non prévu : a imposé l'enregistrement d'EPSG:3301 (E45) |
| `docs/plan/mesures/P0_baseline.md` | `P0_baseline_summary.md` + `P0_baseline_results.jsonl` + `P0_baseline_determinism.json` + `P0_baseline_run_metadata.json` | le plan ne demandait qu'un résumé ; la **donnée brute** est versionnée en plus, pour que E36–E43 soient contrôlables à la relecture |

Deux cartes de Forêt de Caen partagent la même emprise, les mêmes 1 041 entités et les mêmes
11 zones interdites : ce sont deux profils de la **même** carte (MD H21E et couleur Jaune), comme
le demande le gabarit.

#### Point de vigilance sur la capture « couleur Jaune »

La capture Jaune est un circuit **de forêt**, mais le moteur la produit par le **chemin sprint** :
dans la branche `couleur`, le champ `technical_level` porte la *difficulté du terrain*
(« TD = difficulté terrain », `ffco_categories.json`), et `ai_generator.py` l.250 le lit avec le
sens du niveau technique IOF. Conséquence directe de E08, consignée en E47.""")

    # ── Résultat final des tests ────────────────────────────────────────────
    md = replace_section(md, "## Résultat final des tests", """## Résultat final des tests

Revérifié le 22 novembre 2026 sur `plan/p0-socle` au tip `672d948` :

```
pytest tests -q   →  226 passés, 4 échoués (pré-existants aitraceur_proto), 7 warnings
node tile-service/test.js  →  22/22 tests passés
```

Les 4 échecs sont antérieurs à la phase 0 et tous situés dans `tests/aitraceur_proto/`
(prototype gelé, hors périmètre). **Aucune régression** par rapport à la ligne de base (§0.3).""")

    # ── Écarts au plan ──────────────────────────────────────────────────────
    md = replace_section(md, "## Écarts au plan", """## Écarts au plan

| Étape | Écart | Motif |
|-------|-------|-------|
| 0.1 | Frontend npm test non exécuté | Test manuel ; tests backend vérifiés |
| 0.8 | Le banc ne pouvait pas rejouer les circuits de forêt | `_extract_circuit_points` lisait `controls` comme des paires au lieu de dicts ; fixture masking le bug. Corrigé (`632603f`, E48) |
| 0.9 | **Aucun sprint Caen** | l'inventaire réel comporte Bayeux, Dôme, Porten-Bessin |
| 0.9 | **Kûti est hors de France** | carte de substitution ; a imposé l'enregistrement d'EPSG:3301 (E45) |
| 0.9 | **Forêt de Caen remplace 5 des 6 forêts suggérées** | seule Ste Anne II figure dans la liste du plan |
| 0.9 | **Huit sorties brutes versionnées en plus de `P0_baseline.md`** | la ligne de base réelle couvre **deux modes** (en ligne et hors ligne) et **sept captures**, ce qui demande quatre fichiers par mode. La donnée brute (`results.jsonl`) est nécessaire pour contrôler E36–E43, E49 et E50 à la relecture |
| 0.9 | Le plan demande un seul fichier `P0_baseline.md` pour une ligne de base qui couvre **deux modes** | `P0_baseline.md` existe bien (critère d'acceptation 6) et porte les valeurs par carte pour les deux modes ; les **huit** sorties brutes du banc sont versionnées à côté, sous `P0_baseline_*` et `P0_baseline_offline_*`. Un fichier, pas deux résumés concurrents : `P0_baseline_summary.md` est la sortie brute du banc, `P0_baseline.md` est la table de base consolidée |
| 0.9 | Trois fichiers de plus que le plan : `P0_captures.md`, `P0_synthese.md`, `P0_registre_rows.md` | l'inventaire des sept captures et l'écart au gabarit §0.9 (demandés par la tâche) ; la synthèse comparative des deux modes ; les lignes de registre issues des mesures, pour que le registre soit contrôlable à la relecture |
| 0.9 | Deux bancs lancés en parallèle ont écrit dans le même log et le même dossier de sortie | **exécution écartée** : ni les temps ni les lignes de journal de cette exécution ne sont retenus ; le banc a été relancé seul |""")

    # ── Mesures ─────────────────────────────────────────────────────────────
    md = replace_section(md, "## Mesures", f"""## Mesures

Banc P0 : 7 captures × 5 graines, en ligne (`AITRACEUR_ONLINE=1`) puis hors ligne
(`AITRACEUR_ONLINE=0`), sur la machine du traceur, service de tuiles actif.

Artefacts versionnés dans `docs/plan/mesures/` :

| Fichier | Contenu |
|---|---|
| `P0_baseline_results.jsonl` | données brutes : une ligne par rejeu (capture, graine, `ok`, temps, 15 indicateurs) |
| `P0_baseline_summary.md` | résumé par capture et par graine |
| `P0_baseline_determinism.json` | verdict de reproductibilité à graine fixée, par capture |
| `P0_baseline_run_metadata.json` | compteurs de cache avant/après préchauffage, métadonnées d'exécution |
| `P0_baseline_offline_*` | les quatre mêmes fichiers, mode hors ligne |
| `P0_baseline.md` | **le fichier du plan** : valeurs de base par carte (K2, K3, K4, `forbidden_hits`, `is_loop`, déterminisme) pour les deux modes |
| `P0_synthese.md` | synthèse comparative des deux modes, totaux, échecs de rejeu |
| `P0_registre_rows.md` | lignes de registre issues des mesures (E36–E43, E46, E50, V24–V27) |
| `P0_captures.md` | inventaire des sept captures et écart au gabarit §0.9 |

{tableau}

Détail complet et comparaison en ligne / hors ligne : `docs/plan/mesures/P0_synthese.md`.""")

    # ── Registre ────────────────────────────────────────────────────────────
    md = replace_section(md, "## Registre — Mises à jour", """## Registre — Mises à jour

Faits établis pendant la phase 0 (service de tuiles) :

- **E44** — Le service de tuiles ne peut pas rendre les cartes d'emprise entre ~2,7 et 4,5 km² :
  la résolution adaptative raffinait à 0,1 m/px quand RAW < 0,3, produisant ~431 Mpx pour
  La Forêt de Caen 2022 (2107 × 2045 m), au-dessus de la limite Sharp (268 Mpx).
  Correctif : `Math.max(0.1, RAW)` + garantie dure 200 Mpx dans `resolution.js`.

Faits établis par le banc de la phase 0 :

- **E36** à **E43** — valeurs de base du moteur v1 : distance minimale entre postes, paires à
  moins de 30 m et de 60 m, auto-intersections (K3), circuit refermé, postes en zone interdite,
  densité maximale (K2), couverture de la zone de tracé (K4). Voir `docs/plan/REGISTRE.md`.
- **E45** — EPSG:3301 (Kûti, Estonie) : correctif minimal appliqué dans la branche ; la forme
  complète (module `crs.js` centralisé, sixième section de tests) reste à faire et le service de
  tuiles reste un prérequis infrastructurel.
- **E46** — verdict de déterminisme à graine fixée, mesuré par le banc (rejeu de la graine 0 après
  les mesures, à chaud).
- **E47** — `technical_level` porte deux significations (niveau IOF / difficulté du terrain) ; une
  capture couleur Jaune passe par le chemin sprint.
- **E48** — l'instrument de mesure de la phase 0 ne savait pas lire la sortie du moteur pour les
  circuits de forêt ; la fixture de test validait le bug.

Questions ouvertes reportées en phase 1 : **V24** (rejouabilité et temps du banc), **V25**
(influence cache froid / chaud), **V26** (comparaison hors ligne / en ligne), **V27** (le moteur v1
est-il une référence, ou faut-il le remplacer ?).

**Bug corrigé dans le code de la phase :** `_segments_intersect` utilisait `(d1 > 0 < d2)` (comparaison chaînée Python) au lieu de `d1 * d2 < 0` — corrigé dans `metrics.py`.

**Bug corrigé dans `.gitignore` :**
- `AItraceur/` sur Windows (case-insensitive) bloquait `backend/src/aitraceur/` → ancré `/AItraceur/`.
- `tools/` bloquait `backend/tools/` → exception `!backend/tools/` ajoutée.""")

    # ── À tester à la main ──────────────────────────────────────────────────
    md = replace_section(md, "## À tester à la main (étape 0.9)", """## Rejouer le banc (procédure vérifiée)

Le banc doit tourner **sur la machine du traceur**, service de tuiles actif, et **un seul job à la
fois** (deux exécutions concurrentes écrivent dans le même log et le même dossier de sortie, et
se corrompent mutuellement les caches disque).

```bash
# service de tuiles
curl -s http://localhost:8089/health          # {"status":"ok"}

# banc en ligne
cd backend
python -m src.aitraceur.evalbench.run v1 \\
    --captures ../captures \\
    --seeds 0 1 2 3 4 \\
    --out ../runs/p0_baseline_online

# banc hors ligne
AITRACEUR_ONLINE=0 python -m src.aitraceur.evalbench.run v1 \\
    --captures ../captures \\
    --seeds 0 1 2 3 4 \\
    --out ../runs/p0_baseline_offline

# versement des huit artefacts
cp ../runs/p0_baseline_online/results.jsonl      ../docs/plan/mesures/P0_baseline_results.jsonl
cp ../runs/p0_baseline_online/summary.md          ../docs/plan/mesures/P0_baseline_summary.md
cp ../runs/p0_baseline_online/determinism.json    ../docs/plan/mesures/P0_baseline_determinism.json
cp ../runs/p0_baseline_online/run_metadata.json   ../docs/plan/mesures/P0_baseline_run_metadata.json
cp ../runs/p0_baseline_offline/results.jsonl     ../docs/plan/mesures/P0_baseline_offline_results.jsonl
cp ../runs/p0_baseline_offline/summary.md         ../docs/plan/mesures/P0_baseline_offline_summary.md
cp ../runs/p0_baseline_offline/determinism.json   ../docs/plan/mesures/P0_baseline_offline_determinism.json
cp ../runs/p0_baseline_offline/run_metadata.json  ../docs/plan/mesures/P0_baseline_offline_run_metadata.json
```""")

    # ── Remarques ───────────────────────────────────────────────────────────
    md = replace_section(md, "## Remarques", """## Remarques

- Le `run.py` importe `src.core.config` (settings) et `numpy`/`scipy` — disponibles dans `requirements.txt`.
- `replay_v1.py` : import `src.main` local (dans la fonction) — l'appel démarre la base SQLite et les routeurs FastAPI ; lancer depuis `backend/`.
- Le `AITRACEUR_ONLINE=False` ne désactive pas les appels réseau dans `replay_v1.py` directement : c'est le settings qui est lu par le moteur. Passer `AITRACEUR_ONLINE=0` comme variable d'environnement avant le lancement.
- **Le service de tuiles doit rester actif pendant les deux bancs** : sans lui, `/forbidden-zones` est indisponible et `forbidden_hits` est faussé. Le plan le signale dans ses pièges ; c'est aussi la raison pour laquelle le banc n'a pas été lancé sur la machine de revue.
- **Un seul banc à la fois.** Deux exécutions concurrentes ont écrit dans le même journal et le même dossier de sortie : le journal contenait des octets NUL, les lignes des deux exécutions étaient entremêlées et les temps de rejeu étaient gonflés par la concurrence. Cette exécution a été écartée et le banc relancé seul.
- Les compteurs de cache de `run_metadata.json` (`hmc_npz`, `osm_json`) sont cumulés sur le disque : ils mesurent l'activité du préchauffage, pas l'état du cache au moment du rejeu.""")

    # pas de ligne vide en fin de fichier (le patch serait signalé par git apply)
    md = md.rstrip("\n") + "\n"
    p.write_text(md, encoding="utf-8")
    print(f"Compte rendu P0 mis à jour : {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
