#!/usr/bin/env python3
"""Injecte les lignes de registre P0 dans docs/plan/REGISTRE.md.

Entrées écrites à la main (E45, E47, E48) + lignes produites par
analyze_baseline.py (E36–E43, E46) + questions V24–V27.

Idempotent : une ligne déjà présente (même Id) n'est pas réinsérée.
Usage :
    python apply_registre.py <racine du dépôt>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ── Entrées rédigées à la main (constatés de la phase 0) ─────────────────────

MANUELS_ETABLIS = {
    "E45": (
        "Le service de tuiles et le registre front ne connaissaient pas EPSG:3301 : la carte "
        "Kûti (Estonie) ne pouvait pas être projetée. Correctif minimal appliqué dans la branche : "
        "définition EPSG:3301 côté Node (`backend/tile-service/server.js`) et côté front "
        "(`frontend/src/services/ocadCrs.js`). La forme complète attendue par le plan — module "
        "`crs.js` centralisé, sixième section de tests, fiche de registre dédiée — n'est pas dans la "
        "branche : elle reste à faire, et le service de tuiles reste un prérequis infrastructurel.",
        "`backend/tile-service/server.js` ; `frontend/src/services/ocadCrs.js` ; capture "
        "`circuit_20261122T092812Z_5685384b.json` ; `docs/plan/mesures/P0_captures.md` § 1",
    ),
    "E47": (
        "Le champ `technical_level` porte deux significations : le niveau technique IOF dans les "
        "branches sprint/md/ld, la difficulté du terrain dans la branche couleur (« TD = difficulté "
        "terrain », `backend/data/ffco_categories.json`). Le moteur le lit toujours avec le sens IOF "
        "(`ai_generator.py` l.250 : `technical_level in (\"TD1\", \"TD2\")` ⇒ sprint) : un circuit "
        "couleur Jaune (TD1) est donc produit par le chemin sprint — séparation minimale imposée de "
        "40 m au lieu de 60 m, re-ranker d'itinéraire activé. Conséquence directe de E08.",
        "`backend/src/services/generation/ai_generator.py` l.250-252 ; "
        "`backend/src/services/generation/genetic_algo.py` l.175-192 ; "
        "`backend/data/ffco_categories.json` (bloc `couleur`) ; "
        "`docs/plan/mesures/P0_captures.md` § 2",
    ),
    "E49": (
        "Sur les cartes urbaines, le moteur v1 place deux postes au même point : 9 des 15 rejoues "
        "sprint présentent une paire de postes à distance nulle en ligne (`min_pair_dist_m` = 0,0 m) "
        "— Bayeux graines 0/2/3/4, Dôme graines 0/3, Porten-Bessin graines 1/3/4 — et 8 des 15 hors "
        "ligne. Sur les 15 rejoues de forêt, aucune paire sous 30 m. Le contrôle interne de distance "
        "minimale ne porte que sur les postes consécutifs (E09) : le banc, qui mesure toutes les "
        "paires, le révèle. Bayeux graine 2 cumule 7 paires sous 30 m, 9 paires sous 60 m et 6 "
        "auto-intersections. Le défaut n'est pas propre au mode en ligne : il survit à la "
        "disparition des candidats OSM.",
        "`docs/plan/mesures/P0_baseline_results.jsonl` ; "
        "`docs/plan/mesures/P0_baseline_offline_results.jsonl` ; "
        "`backend/src/aitraceur/evalbench/metrics.py` l.163-175 (toutes paires, sauf départ–arrivée)",
    ),
    "E48": (
        "L'instrument de mesure de la phase 0 ne pouvait pas lire la sortie du moteur pour les "
        "circuits de forêt : `_extract_circuit_points` lisait `controls` comme une liste de paires "
        "`[lng, lat]`, alors que `ai_generator.py` produit des dicts `{\"x\", \"y\", …}` — les quatre "
        "captures de forêt échouaient au rejeu sur `KeyError: 0`. La fixture "
        "`circuit_sample.json` était écrite dans le format supposé : les tests unitaires passaient "
        "donc en validant le bug. Corrigé le 22/11/2026 : adaptateur aligné sur le format réel et "
        "fixture réécrite.",
        "commit `632603f` ; `backend/src/aitraceur/evalbench/replay_v1.py` l.98 ; "
        "`backend/tests/aitraceur/fixtures/v1_outputs/circuit_sample.json`",
    ),
}

MANUELS_VERIFIER = {
    "V24": (
        "Le banc complet (7 captures × 5 graines, 2 modes) est-il rejouable sans intervention et "
        "en temps acceptable ?",
        "Consigner la durée cumulée et le temps par capture dans "
        "`docs/plan/mesures/P0_baseline_run_metadata.json` et "
        "`P0_baseline_offline_run_metadata.json`",
        "Phase 1",
    ),
    "V25": (
        "Le résultat dépend-il de l'état du cache disque (chaud ou froid) ?",
        "Comparer les compteurs `hmc_npz` et `osm_json` avant/après préchauffage dans "
        "`docs/plan/mesures/P0_baseline_run_metadata.json` ; comparer les métriques du mode en ligne "
        "et du mode hors ligne",
        "Phase 1",
    ),
    "V26": (
        "Le mode hors ligne dégrade-t-il la qualité du tracé (candidats OSM absents) ?",
        "Comparer `docs/plan/mesures/P0_baseline_summary.md` et "
        "`P0_baseline_offline_summary.md`, capture par capture",
        "Phase 1",
    ),
    "V27": (
        "Le moteur v1 est-il une référence exploitable pour la phase 1, ou faut-il le remplacer ?",
        "Trancher à partir de E36–E43 et du verdict de déterminisme E46",
        "Phase 1",
    ),
}


def extract_block(md: str, header: str) -> tuple[int, int, str]:
    """Renvoie (début, fin, contenu) de la section demandée."""
    m = re.search(rf"^{re.escape(header)}\s*$", md, re.M)
    if not m:
        raise SystemExit(f"Section introuvable : {header}")
    start = m.start()
    nxt = re.search(r"^## ", md[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(md)
    return start, end, md[start:end]


def insert_rows(section: str, rows: list[str]) -> str:
    """Insère des lignes de tableau à la fin du dernier tableau de la section."""
    lines = section.rstrip("\n").split("\n")
    last_row = None
    for i, ln in enumerate(lines):
        if ln.startswith("|"):
            last_row = i
    if last_row is None:
        raise SystemExit("Aucun tableau trouvé")
    # insérer après la dernière ligne de tableau (avant une éventuelle ligne vide)
    new = lines[: last_row + 1] + rows + lines[last_row + 1 :]
    return "\n".join(new) + "\n"


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    reg_path = root / "docs" / "plan" / "REGISTRE.md"
    md = reg_path.read_text(encoding="utf-8")

    today = "2026-11-22"

    # ── lignes issues de l'analyseur (E36–E43, E46) ──────────────────────────
    rows_path = root / "docs" / "plan" / "mesures" / "P0_registre_rows.md"
    ana_etablis: list[str] = []
    ana_questions: list[str] = []
    if rows_path.exists():
        for ln in rows_path.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) != 4:
                continue
            ident = cells[0]
            if ident.startswith("E"):
                ana_etablis.append(s)
            elif ident.startswith("V"):
                ana_questions.append(s)

    # ── table « Établi » : E36–E43, E45, E46, E47, E48 ───────────────────────
    start, end, section = extract_block(md, "## Établi")
    existing = set(re.findall(r"^\|\s*(E\d+)\s*\|", section, re.M))
    rows: list[str] = []
    for ln in ana_etablis:
        ident = ln.strip("|").split("|")[0].strip()
        if ident not in existing:
            rows.append(ln)
            existing.add(ident)
    for ident, (txt, preuve) in MANUELS_ETABLIS.items():
        if ident in existing:
            continue
        rows.append(f"| {ident} | {txt} | {preuve} | {today} |")
        existing.add(ident)
    # ordre numérique
    rows.sort(key=lambda ln: int(ln.strip("|").split("|")[0].strip()[1:]))
    n_etablis = len(rows)
    section = insert_rows(section, rows)
    md = md[:start] + section + md[end:]

    # ── table « À vérifier » : V24–V27 ───────────────────────────────────────
    start, end, section = extract_block(md, "## À vérifier")
    existing_v = set(re.findall(r"^\|\s*(V\d+)\s*\|", section, re.M))
    rows = []
    for ln in ana_questions:
        ident = ln.strip("|").split("|")[0].strip()
        if ident not in existing_v:
            rows.append(ln)
            existing_v.add(ident)
    for ident, (q, comment, quand) in MANUELS_VERIFIER.items():
        if ident in existing_v:
            continue
        rows.append(f"| {ident} | {q} | {comment} | {quand} |")
        existing_v.add(ident)
    rows.sort(key=lambda ln: int(ln.strip("|").split("|")[0].strip()[1:]))
    n_verifier = len(rows)
    section = insert_rows(section, rows)
    md = md[:start] + section + md[end:]

    reg_path.write_text(md, encoding="utf-8")
    print(f"REGISTRE mis à jour : {n_etablis} ligne(s) « Établi », {n_verifier} ligne(s) « À vérifier »")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
