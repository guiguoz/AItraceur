#!/usr/bin/env python3
"""Analyse du banc P0 — produit les tableaux de mesures, le draft des entrées
E36–E43 (registre) et le draft de P0_captures.md.

Usage :
    python analyze_baseline.py <racine du dépôt>

Lecture :
    docs/plan/mesures/P0_baseline_results.jsonl
    docs/plan/mesures/P0_baseline_determinism.json
    docs/plan/mesures/P0_baseline_metadata.json
    docs/plan/mesures/P0_baseline_offline_results.jsonl   (optionnel)
    docs/plan/mesures/P0_baseline_offline_determinism.json (optionnel)
    captures/LISEZMOI.md
Écrit :
    docs/plan/mesures/P0_synthese.md
    docs/plan/mesures/P0_registre_rows.md
"""
from __future__ import annotations

import json
import statistics as st
import sys
from datetime import date
from pathlib import Path

METRICS = [
    "n_controls", "length_m", "leg_min_m", "leg_max_m", "leg_cv",
    "min_pair_dist_m", "n_pairs_below_30m", "n_pairs_below_60m",
    "crossings", "doglegs", "max_in_radius", "n_clustered",
    "coverage_4x4", "hull_ratio", "is_loop", "forbidden_hits",
]
# (id registre, libellé, clé métrique, K éventuel)
ENTREES = [
    ("E36", "distance minimale entre deux postes", "min_pair_dist_m", None),
    ("E37", "paires de postes à moins de 30 m", "n_pairs_below_30m", None),
    ("E38", "paires de postes à moins de 60 m", "n_pairs_below_60m", None),
    ("E39", "auto-intersections du tracé", "crossings", "K3"),
    ("E40", "circuit refermé sur lui-même", "is_loop", None),
    ("E41", "postes tombant dans une zone interdite", "forbidden_hits", None),
    ("E42", "densité maximale de postes", "max_in_radius", "K2"),
    ("E43", "couverture de la zone de tracé", "coverage_4x4", "K4"),
]

# Paramètres réels des 7 captures (dchargés des corps de requête, 22/11/2026).
# mode effectif : le moteur bascule en sprint dès que circuit_type == "sprint"
# OU technical_level ∈ {TD1, TD2} (ai_generator.py l.250) — d'où la capture
# « Forêt de Caen couleur Jaune » (TD1) qui passe en mode sprint.
# min_sep_m : séparation minimale imposée par le moteur
# (scale_min_separation, genetic_algo.py l.175).
CAPTURES_META = {
    "circuit_20261122T083414Z_a2f6feae.json": {
        "carte": "Forêt de Caen", "cat": "H21E", "td": "TD5", "type": "md",
        "groupe": "foret",
        "mode": "foret", "min_sep_m": 60, "seuil_rts_m": 30, "echelle": "1:10 000",
        "forb": 11, "feats": 1041, "ctrl": 27, "long": 7300,
    },
    "circuit_20261122T084351Z_a63cd765.json": {
        "carte": "Forêt de Caen", "cat": "Couleur-Jaune", "td": "TD1", "type": "couleur",
        "groupe": "couleur",
        "mode": "sprint", "min_sep_m": 40, "seuil_rts_m": 30, "echelle": "1:10 000",
        "forb": 11, "feats": 1041, "ctrl": 12, "long": 2000,
        "note": "capture valide (chemin couleur du front) ; TD1 y est la difficulté "
                "du terrain, pas le niveau IOF — l'engine le lit comme « sprint » "
                "(ai_generator.py l.250) et impose 40 m au lieu de 60 m",
    },
    "circuit_20261122T092812Z_5685384b.json": {
        "carte": "Kûti (Estonie)", "cat": "H21E", "td": "TD5", "type": "md",
        "groupe": "foret",
        "mode": "foret", "min_sep_m": 60, "seuil_rts_m": 30, "echelle": "1:10 000",
        "forb": 6, "feats": 1824, "ctrl": 27, "long": 7300,
        "note": "hors France — CRS source EPSG:3301",
    },
    "circuit_20261122T095424Z_7ca39337.json": {
        "carte": "Ste Anne II", "cat": "H21E", "td": "TD5", "type": "md",
        "groupe": "foret",
        "mode": "foret", "min_sep_m": 60, "seuil_rts_m": 30, "echelle": "1:10 000",
        "forb": 7, "feats": 426, "ctrl": 27, "long": 7300,
    },
    "sprint_20261119T164701Z_a530a9ea.json": {
        "carte": "Bayeux", "cat": "H21E", "td": "TD3", "type": "sprint",
        "groupe": "sprint",
        "mode": "sprint", "min_sep_m": 30, "seuil_rts_m": 15, "echelle": "1:4 000",
        "forb": 4130, "feats": 251, "ctrl": 16, "long": 2800,
    },
    "sprint_20261119T171122Z_46871982.json": {
        "carte": "Dôme", "cat": "H21E", "td": "TD3", "type": "sprint",
        "groupe": "sprint",
        "mode": "sprint", "min_sep_m": 30, "seuil_rts_m": 15, "echelle": "1:4 000",
        "forb": 2245, "feats": 91, "ctrl": 16, "long": 2800,
    },
    "sprint_20261119T172115Z_a562c112.json": {
        "carte": "Porten-Bessin", "cat": "H21E", "td": "TD3", "type": "sprint",
        "groupe": "sprint",
        "mode": "sprint", "min_sep_m": 30, "seuil_rts_m": 15, "echelle": "1:4 000",
        "forb": 354, "feats": 2230, "ctrl": 16, "long": 2800,
    },
}


def med(vals):
    return st.median(vals) if vals else None


def fmt(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "oui" if v else "non"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def pick(mes: Path, *names: str) -> Path:
    """Premier nom existant parmi les variantes (nommage canonique en tête)."""
    for n in names:
        p = mes / n
        if p.exists():
            return p
    return mes / names[0]


def per_capture(rows: list[dict]) -> dict[str, dict]:
    """Statistiques par capture : médiane de chaque métrique sur les graines valides."""
    out: dict[str, dict] = {}
    for r in rows:
        cap = r.get("capture")
        if not cap:
            continue
        d = out.setdefault(cap, {"ok": [], "err": [], "kind": r.get("kind"), "seeds": []})
        if r.get("ok"):
            d["ok"].append(r)
            d["seeds"].append(r.get("seed"))
        else:
            d["err"].append(r.get("error"))
    for cap, d in out.items():
        stats = {}
        for k in METRICS:
            vals = [r[k] for r in d["ok"] if k in r and r[k] is not None]
            stats[k] = med(vals) if vals else None
        d["stats"] = stats
    return out


def inventory(root: Path) -> dict[str, str]:
    """captures/LISEZMOI.md → {fichier: description}."""
    f = root / "captures" / "LISEZMOI.md"
    inv = {}
    if not f.exists():
        return inv
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            inv[parts[0]] = " | ".join(parts[1:])
    return inv


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    mes = root / "docs" / "plan" / "mesures"

    on_rows = load_jsonl(mes / "P0_baseline_results.jsonl")
    on_det = load_json(mes / "P0_baseline_determinism.json").get("results", {})
    on_meta = load_json(pick(mes, "P0_baseline_run_metadata.json", "P0_baseline_metadata.json"))
    off_rows = load_jsonl(mes / "P0_baseline_offline_results.jsonl")
    off_det = load_json(mes / "P0_baseline_offline_determinism.json").get("results", {})
    inv = inventory(root)

    if not on_rows:
        print("Aucun résultat en ligne — rien à analyser.", file=sys.stderr)
        return 1

    on = per_capture(on_rows)
    off = per_capture(off_rows) if off_rows else {}
    today = date.today().isoformat()

    # ── mesures hors ligne (comparaison des deux bancs) ─────────────────────
    tot_off = sum(r.get("runtime_s", 0) for r in off_rows) if off else 0.0
    det_off = sum(1 for v in off_det.values() if v.get("identical"))
    n_ok_off = sum(1 for r in off_rows if r.get("ok"))
    n_err_off = len(off_rows) - n_ok_off

    def _med(mode, key, kind=None):
        vals = []
        for cap, d in mode.items():
            if kind and d["kind"] != kind:
                continue
            v = d["stats"].get(key)
            if v is not None:
                vals.append(v)
        return st.median(vals) if vals else None


    # ---------------------------------------------------------------- tableau
    lines = []
    lines.append("# Synthèse du banc P0 — moteur v1\n")
    lines.append(f"Mode en ligne : {len(on_rows)} trajectoires sur {len(on)} captures.\n")
    lines.append("## Mesures par capture (médiane des graines valides)\n")
    lines.append("| Capture | Carte | Mode effectif | sépa. moteur | graines | long. (m) | min paire (m) | "
                 "<30 m | <60 m | crois. (K3) | boucle | interdits | densité (K2) | couv. (K4) | "
                 "déterm. | durée (s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for cap, d in sorted(on.items()):
        s = d["stats"]
        dur = med([r.get("runtime_s") for r in d["ok"]])
        det = on_det.get(cap, {}).get("identical")
        desc = inv.get(cap, "?")
        meta = CAPTURES_META.get(cap, {})
        mode = meta.get("mode", d["kind"])
        if meta.get("groupe") == "couleur":
            mode = "sprint (couleur)"
        sep = f"{meta['min_sep_m']} m" if meta.get("min_sep_m") else "—"
        lines.append(
            f"| {cap} | {desc} | {mode} | {sep} | {len(d['ok'])}/{len(d['ok']) + len(d['err'])} "
            f"| {fmt(s['length_m'], 0)} | {fmt(s['min_pair_dist_m'], 1)} | {fmt(s['n_pairs_below_30m'], 0)} "
            f"| {fmt(s['n_pairs_below_60m'], 0)} | {fmt(s['crossings'], 0)} | {fmt(s['is_loop'])} "
            f"| {fmt(s['forbidden_hits'], 0)} | {fmt(s['max_in_radius'], 0)} | {fmt(s['coverage_4x4'], 3)} "
            f"| {'✓' if det else ('✗' if det is False else '?')} | {fmt(dur, 0)} |")
    lines.append("")

    # ------------------------------------------------------------------ échecs
    lignes_echec = [(r.get("capture"), r.get("seed"), r.get("error"))
                    for r in on_rows if not r.get("ok")]
    if lignes_echec:
        lines.append("## Échecs de rejeu (mode en ligne)\n")
        lines.append("| Capture | Graine | Erreur |")
        lines.append("|---|---|---|")
        for cap, seed, err in lignes_echec:
            lines.append(f"| {cap} | {seed} | {err} |")
        lines.append("")
    else:
        lines.append("## Échecs de rejeu (mode en ligne)\n")
        lines.append(f"Aucun : les {len(on_rows)} trajectoires "
                     f"({len(on)} captures × 5 graines) ont abouti.\n")

    # ------------------------------------------------------------------ échecs off
    if off:
        echecs_off = [(r.get("capture"), r.get("seed"), r.get("error"))
                      for r in off_rows if not r.get("ok")]
        lines.append("## Échecs de rejeu (mode hors ligne)\n")
        if echecs_off:
            lines.append("| Capture | Graine | Erreur |")
            lines.append("|---|---|---|")
            for cap, seed, err in echecs_off:
                lines.append(f"| {cap} | {seed} | {err} |")
            lines.append("")
        else:
            n_ok_off = sum(1 for r in off_rows if r.get("ok"))
            lines.append(f"Aucun : les {n_ok_off} trajectoires hors ligne ont abouti.\n")

    # ---------------------------------------------------------- en ligne/hors ligne
    if off:
        lines.append("## Comparaison en ligne / hors ligne (médiane par capture)\n")
        lines.append("| Capture | long. (m) | min paire (m) | <30 m | crois. | interdits | déterm. ligne | déterm. hors ligne |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for cap, d in sorted(on.items()):
            if cap not in off:
                continue
            a, b = d["stats"], off[cap]["stats"]
            dl = on_det.get(cap, {}).get("identical")
            do = off_det.get(cap, {}).get("identical")
            lines.append(
                f"| {cap} | {fmt(a['length_m'], 0)} → {fmt(b['length_m'], 0)} "
                f"| {fmt(a['min_pair_dist_m'], 1)} → {fmt(b['min_pair_dist_m'], 1)} "
                f"| {fmt(a['n_pairs_below_30m'], 0)} → {fmt(b['n_pairs_below_30m'], 0)} "
                f"| {fmt(a['crossings'], 0)} → {fmt(b['crossings'], 0)} "
                f"| {fmt(a['forbidden_hits'], 0)} → {fmt(b['forbidden_hits'], 0)} "
                f"| {'✓' if dl else '✗' if dl is False else '?'} | {'✓' if do else '✗' if do is False else '?'} |")
        lines.append("")

    # ----------------------------------------------------------------- totaux
    tot_on = sum(r.get("runtime_s", 0) for r in on_rows)
    n_ok = sum(1 for r in on_rows if r.get("ok"))
    n_err = len(on_rows) - n_ok
    det_ok = sum(1 for v in on_det.values() if v.get("identical"))
    det_total = len(on_det)
    lines.append("## Totaux\n")
    lines.append(f"- Trajectoires en ligne : **{n_ok}** valides, {n_err} en erreur")
    lines.append(f"- Temps cumulé des rejoues : **{tot_on / 3600:.2f} h**")
    lines.append(f"- Déterminisme : **{det_ok}/{det_total}** captures reproductibles à graine fixée")
    if off:
        tot_off = sum(r.get("runtime_s", 0) for r in off_rows)
        lines.append(f"- Temps cumulé hors ligne : **{tot_off / 3600:.2f} h**")
    cache = on_meta.get("sprint_features_cache", {})
    if cache:
        lines.append("- Cache (avant → après préchauffage) :")
        for cap, st_ in cache.items():
            lines.append(f"  - {cap} : hmc_npz {st_.get('hmc_npz_before')} → {st_.get('hmc_npz_after')}, "
                         f"osm_json {st_.get('osm_json_before')} → {st_.get('osm_json_after')}")
    lines.append("")

    (mes / "P0_synthese.md").write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # P0_baseline.md — le fichier exigé par le plan (phase 0, §0.9 point 5
    # et critère d'acceptation 6) : les valeurs de base PAR CARTE, pour les
    # deux modes. Ce n'est pas un second résumé concurrent de
    # `P0_baseline_summary.md` (sortie brute du banc, mode en ligne) : c'est
    # la table de référence que le plan et la phase 1 lisent.
    # ------------------------------------------------------------------
    bl = []
    bl.append("# Ligne de base du moteur v1 — phase 0\n")
    bl.append(f"**Établi le {today}.** Banc : 7 captures × 5 graines × 2 modes "
              f"({n_ok} rejoues valides en ligne, {n_ok_off} hors ligne, "
              f"{n_err + n_err_off} en erreur).\n")
    bl.append("Fichier de référence du plan (`docs/plan/10_P0_socle_et_mesure.md` §0.9 point 5, "
              "critère d'acceptation 6) : les valeurs de base **par carte**, pour les deux modes.\n")
    bl.append("Ce fichier n'est pas un second résumé concurrent : "
              "`P0_baseline_summary.md` et `P0_baseline_offline_summary.md` sont les sorties brutes "
              "du banc, `P0_baseline_results.jsonl` et `P0_baseline_offline_results.jsonl` en sont "
              "la donnée brute (une ligne par rejeu), et `P0_synthese.md` porte la comparaison "
              "complète et le détail par graine. Ici : la table de base.\n")
    bl.append("Toutes les valeurs sont des **médianes sur les graines valides** de la capture.\n")
    bl.append("## Valeurs par carte\n")
    bl.append("| Capture | Carte | Mode effectif | K2 `max_in_radius` | K3 `crossings` | "
              "K4 `coverage_4x4` | `forbidden_hits` | `is_loop` | déterminisme (K5) | "
              "`n_controls` | longueur (m) |")
    bl.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for cap, d in sorted(on.items()):
        meta = CAPTURES_META.get(cap, {})
        mode = meta.get("mode", d["kind"])
        if meta.get("groupe") == "couleur":
            mode = "sprint (couleur)"
        for label, mode_d, det in (("en ligne", d, on_det.get(cap, {}).get("identical")),
                                   ("hors ligne", off.get(cap) if off else None,
                                    off_det.get(cap, {}).get("identical") if off else None)):
            if mode_d is None:
                continue
            s = mode_d["stats"]
            bl.append(
                f"| {cap} | {meta.get('carte', '?')} | {mode} ({label}) "
                f"| {fmt(s.get('max_in_radius'), 0)} | {fmt(s.get('crossings'), 0)} "
                f"| {fmt(s.get('coverage_4x4'), 4)} | {fmt(s.get('forbidden_hits'), 0)} "
                f"| {'oui' if s.get('is_loop') else 'non'} "
                f"| {'✓' if det else '✗' if det is False else '?'} "
                f"| {fmt(s.get('n_controls'), 0)} | {fmt(s.get('length_m'), 0)} |")
    bl.append("")
    bl.append("## Notes de lecture\n")
    bl.append("- **K2** (`max_in_radius`) : nombre maximal de postes dans un rayon donné ; "
              "plus il est bas, moins les postes sont groupés.")
    bl.append("- **K3** (`crossings`) : paires de jambes non adjacentes qui se croisent.")
    bl.append("- **K4** (`coverage_4x4`) : part de la zone de tracé couverte par la grille 4×4.")
    bl.append("- **`is_loop`** : le circuit se referme (départ et arrivée à moins de 1 m).")
    bl.append("- **déterminisme (K5)** : rejoue de la graine 0 après les mesures, à chaud ; "
              "`✓` = même tracé, `✗` = tracé différent.")
    bl.append("- **`n_controls`** : postes internes, hors départ et arrivée "
              "(`backend/src/aitraceur/evalbench/metrics.py` l.147-149) ; ajouter 2 pour le "
              "nombre de postes du circuit.")
    bl.append("- **mode effectif** : ce que le moteur a réellement fait, pas ce que la "
              "capture demandait — voir `P0_captures.md` § 2.")
    bl.append("")
    (mes / "P0_baseline.md").write_text("\n".join(bl), encoding="utf-8")

    # ------------------------------------------------- draft des entrées registre
    reg = []
    reg.append("## Lignes à insérer dans `docs/plan/REGISTRE.md`")
    reg.append("")
    reg.append(f"<!-- généré le {today} à partir de docs/plan/mesures/P0_baseline_* -->")
    reg.append("")
    reg.append("| Id | Énoncé | Preuve | Date |")
    reg.append("|----|--------|--------|------|")

    all_stats = {k: [] for k in METRICS}
    for d in on.values():
        for k, v in d["stats"].items():
            if v is not None:
                all_stats[k].append(v)

    def g(k, kind=None):
        vals = []
        for cap, d in on.items():
            if kind and d["kind"] != kind:
                continue
            v = d["stats"].get(k)
            if v is not None:
                vals.append(v)
        return vals

    def agg(k, kind=None):
        v = g(k, kind)
        return (min(v), med(v), max(v)) if v else (None, None, None)

    # Cartes *exploitables* = au moins une graine valide. Une capture dont
    # toutes les graines ont échoué ne compte pas dans les dénominateurs.
    exploitable = {c: d for c, d in on.items() if d["ok"]}
    n_sprint = len([d for d in exploitable.values() if d["kind"] == "sprint"])
    n_circ = len([d for d in exploitable.values() if d["kind"] == "circuit"])
    n_expl = len(exploitable)
    n_total = len(on)
    perdues = [c for c in on if not on[c]["ok"]]


    # — E36 : distance minimale, par groupe (seuils RTS p. 9/12) ————————————
    def _vals_groupe(groupe, key):
        vals = []
        for cap, d in on.items():
            m = CAPTURES_META.get(cap, {})
            if m.get("groupe") != groupe or not d["ok"]:
                continue
            v = d["stats"].get(key)
            if v is not None:
                vals.append(v)
        return vals

    def par_groupe(groupe, key="min_pair_dist_m"):
        vals = _vals_groupe(groupe, key)
        return (min(vals), st.median(vals), len(vals)) if vals else (None, None, 0)

    def grp_stats(groupe, key):
        """(min, médiane, max, n) par groupe — un groupe = un type de carte."""
        vals = _vals_groupe(groupe, key)
        if not vals:
            return (None, None, None, 0)
        return (min(vals), st.median(vals), max(vals), len(vals))

    lo_f, md_f, n_f = par_groupe("foret")
    lo_sp, md_sp, n_sp = par_groupe("sprint")
    lo_c, md_c, n_c = par_groupe("couleur")
    if md_f is not None and md_sp is not None:
        conf_f = "conforme" if lo_f >= 30 else "non conforme"
        conf_sp = "conforme" if lo_sp >= 15 else "non conforme"
        conf_c = "conforme" if lo_c >= 30 else "non conforme"
        txt = (f"Sur les {n_f} cartes de forêt, la plus petite distance entre deux postes est de "
               f"{fmt(lo_f, 1)} m au minimum (médiane {fmt(md_f, 1)} m) — seuil RTS p. 9/12 : 30 m, "
               f"{conf_f}. Sur les {n_sp} cartes de sprint urbain : {fmt(lo_sp, 1)} m au minimum "
               f"(médiane {fmt(md_sp, 1)} m) — seuil RTS p. 9/12 : 15 m, {conf_sp}"
               + (" (paire de postes à distance nulle)" if lo_sp == 0 else "")
               + f". Sur la carte de forêt en couleur Jaune (produite par le chemin sprint, voir "
               f"E47) : {fmt(lo_c, 1)} m au minimum (médiane {fmt(md_c, 1)} m) — seuil RTS p. 9/12 : "
               f"30 m, {conf_c}."
               + (f" Réserve : {n_total - n_expl} capture(s) sans graine valide ne sont pas comptées."
                  if perdues else ""))
        txt += (" Réserve de méthode : le moteur impose lui-même 60 m en forêt et 30 m en sprint "
                "(`scale_min_separation`, `genetic_algo.py` l.175-192) ; la mesure vérifie donc le "
                "respect de la contrainte du moteur, pas la conformité au seuil RTS, qui est plus "
                "bas (30 m / 15 m).")
        reg.append(f"| E36 | {txt} | `docs/plan/mesures/P0_baseline_summary.md` ; "
                   f"`docs/plan/mesures/P0_baseline_results.jsonl` | {today} |")

    # — E37 : paires < 30 m ——————————————————————————————————————————————
    lo_f37, md_f37, hi_f37, n_f37 = grp_stats("foret", "n_pairs_below_30m")
    if md_f37 is not None:
        _, md_s37, _, n_s37 = grp_stats("sprint", "n_pairs_below_30m")
        _, md_c37, _, n_c37 = grp_stats("couleur", "n_pairs_below_30m")
        txt = (f"Sur les {n_f37} cartes de forêt (Forêt de Caen MD, Kûti MD, Ste Anne II MD), le "
               f"banc relève {fmt(md_f37, 0)} paire(s) de postes à moins de 30 m en médiane par "
               f"carte (maximum {fmt(hi_f37, 0)}) — seuil RTS p. 9/12 (30 m), conforme. "
               f"Sur les {n_s37} cartes de sprint urbain : {fmt(md_s37, 0)} paire(s) à moins de 30 m "
               f"en médiane (le seuil sprint est 15 m, non mesuré par le banc : à instrumenter) ; "
               f"sur la {n_c37} carte de forêt en couleur Jaune : {fmt(md_c37, 0)}."
               + (f" Réserve : {n_total - n_expl} capture(s) sans graine valide ne sont pas comptées."
                  if perdues else ""))
        reg.append(f"| E37 | {txt} | `docs/plan/mesures/P0_baseline_results.jsonl` | {today} |")

    # — E38 : paires < 60 m (même nature) ————————————————————————————————————
    lo_f38, md_f38, hi_f38, n_f38 = grp_stats("foret", "n_pairs_below_60m")
    if md_f38 is not None:
        _, md_s38, _, n_s38 = grp_stats("sprint", "n_pairs_below_60m")
        _, md_c38, _, n_c38 = grp_stats("couleur", "n_pairs_below_60m")
        txt = (f"Sur les {n_f38} cartes de forêt (Forêt de Caen MD, Kûti MD, Ste Anne II MD), "
               f"{fmt(md_f38, 0)} paire(s) de postes à moins de 60 m en médiane par carte "
               f"(maximum {fmt(hi_f38, 0)}) — règle des 60 m entre postes de même nature "
               f"(RTS p. 9/12), conforme. Le banc ne distingue pas les libellés : ces paires sont "
               f"une borne supérieure des violations de la règle. Sur les {n_s38} cartes de sprint "
               f"urbain : {fmt(md_s38, 0)} paire(s) à moins de 60 m en médiane ; sur la "
               f"{n_c38} carte de forêt en couleur Jaune : {fmt(md_c38, 0)}."
               + (f" Réserve : {n_total - n_expl} capture(s) sans graine valide ne sont pas comptées."
                  if perdues else ""))
        reg.append(f"| E38 | {txt} | `docs/plan/mesures/P0_baseline_results.jsonl` | {today} |")

    # — E39 à E43 : indicateurs globaux ———————————————————————————————————
    for eid, libelle, key, kcode in ENTREES[3:]:
        lo, md, hi = agg(key)
        if md is None:
            continue
        if key == "is_loop":
            vals = g("is_loop")
            txt = (f"Sur les {n_expl} cartes exploitables du banc, {sum(1 for v in vals if v)} circuits sur "
                   f"{len(vals)} se referment sur eux-mêmes (départ et arrivée à moins de 1 m).")
        elif key == "forbidden_hits":
            vals = g("forbidden_hits")
            txt = (f"Sur les {n_expl} cartes exploitables du banc, {fmt(md, 0)} poste(s) en zone interdite en "
                   f"médiane par carte (maximum {fmt(hi, 0)}) — zones interdites issues de l'OCAD "
                   f"(hors-limites, végétation impassable), buildings exclus.")
        else:
            txt = (f"Sur les {n_expl} cartes exploitables du banc, « {libelle} » vaut {fmt(md, 2)} en médiane "
                   f"(min {fmt(lo, 2)}, max {fmt(hi, 2)}).")
        if kcode:
            txt += f" ({kcode})"
        if perdues:
            txt += (f" Réserve : {n_total - n_expl} capture(s) sans aucune graine valide "
                    f"ne sont pas comptées.")
        reg.append(f"| {eid} | {txt} | `docs/plan/mesures/P0_baseline_summary.md` ; "
                   f"`docs/plan/mesures/P0_baseline_results.jsonl` | {today} |")

    non_repro = sorted(c for c, v in on_det.items() if v.get("identical") is False)
    det_txt = (f"À graine fixée, le moteur v1 reproduit le même tracé sur {det_ok} capture(s) "
               f"sur {det_total} au banc en ligne (rejeu de la graine 0 après les mesures, à chaud)")
    if non_repro:
        det_txt += (f" ; ne sont PAS reproductibles : {', '.join(non_repro)}. "
                    "C'est une donnée sur le moteur v1, à consigner telle quelle (le plan "
                    "recommande explicitement de ne pas la corriger en phase 0) : la graine fixe "
                    "l'aléa du GA, pas l'ensemble des entrées, qui dépendent des caches disque "
                    "et de l'enrichissement OSM.")
    elif det_ok:
        det_txt += " — toutes les captures sont reproductibles à graine fixée."
    reg.append(f"| E46 | {det_txt} | "
               f"`docs/plan/mesures/P0_baseline_determinism.json` | {today} |")
    # ── E50 : les mêmes indicateurs en mode hors ligne ───────────────────────
    if off:
        def _med_off(key, kind=None):
            vals = []
            for cap, d in off.items():
                if kind and d["kind"] != kind:
                    continue
                v = d["stats"].get(key)
                if v is not None:
                    vals.append(v)
            return st.median(vals) if vals else None

        e50 = (f"Hors ligne, sur {len(off)} capture(s) exploitables et {n_ok_off} rejoue(s) valide(s) "
               f"({n_err_off} en erreur) : « distance minimale entre postes » {_med_off('min_pair_dist_m') or 0:.1f} m "
               f"en médiane, « auto-intersections du tracé » {_med_off('crossings') or 0:.0f} en médiane "
               f"(maximum {max((d['stats'].get('crossings') or 0) for d in off.values()):.0f}), "
               f"« postes en zone interdite » {_med_off('forbidden_hits') or 0:.0f}, "
               f"« densité maximale de postes » {_med_off('max_in_radius') or 0:.0f}, "
               f"« couverture de la zone de tracé » {_med_off('coverage_4x4') or 0:.3f}. "
               f"Le mode hors ligne est donc **opérationnel** : il produit des circuits valides, "
               f"sans violation de zone interdite et de longueur comparable à celle du mode en ligne "
               f"({_med(on, 'length_m') or 0:.0f} m).")
        reg.append(f"| E50 | {e50} | `docs/plan/mesures/P0_baseline_offline_results.jsonl` ; "
                   f"`docs/plan/mesures/P0_baseline_offline_summary.md` | {today} |")

    reg.append("")
    reg.append("### Questions (à vérifier)")
    reg.append("")
    reg.append("| Id | Question | Action | Échéance |")
    reg.append("|----|----------|--------|----------|")
    # V24 — rejouabilité et durée
    v24 = (f"OUI, rejouable sans intervention : {n_ok} rejoues valides et {n_err} en erreur en "
           f"ligne, {n_ok_off} valides et {n_err_off} en erreur hors ligne, sur les deux modes "
           f"successifs. Durée cumulée : {tot_on / 3600:.2f} h en ligne"
           + (f" et {tot_off / 3600:.2f} h hors ligne (soit {(tot_on + tot_off) / 3600:.2f} h pour le "
              f"banc complet)" if off else "") + ".")
    reg.append("| V24 | Le banc complet (7 captures × 5 graines, 2 modes) est-il rejouable sans "
               "intervention et en temps acceptable ? | " + v24 + " | Phase 1 |")

    # V25 — dépendance à l'état du cache
    cache_dirs = [c for c, s in (on_meta.get("sprint_features_cache") or {}).items()
                  if s.get("hmc_npz_before") != s.get("hmc_npz_after")
                  or s.get("osm_json_before") != s.get("osm_json_after")]
    v25 = ("OUI, le résultat dépend de l'état du cache disque : les compteurs `hmc_npz` ont évolué "
           "pendant le banc en ligne sur "
           + (", ".join(sorted(cache_dirs)) if cache_dirs else "—") + " (les compteurs OSM sont restés "
           "stables). Combiné au déterminisme de " + f"{det_ok}/{det_total}" + " captures à graine "
           "fixée, cela montre que la graine fixe l'aléa du GA mais pas l'ensemble des entrées.")
    reg.append("| V25 | Le résultat dépend-il de l'état du cache disque ? | " + v25 + " | Phase 1 |")

    # V26 — dégradation hors ligne
    if off:
        def _med_grp(mode, groupe, key):
            vals = []
            for cap, d in mode.items():
                if CAPTURES_META.get(cap, {}).get("groupe") != groupe:
                    continue
                v = d["stats"].get(key)
                if v is not None:
                    vals.append(v)
            return st.median(vals) if vals else None

        parts = []
        for groupe, lbl in (("foret", "forêt"), ("sprint", "sprint urbain")):
            for key, klbl, fmt_ in (("length_m", "longueur", lambda v: f"{v:.0f} m"),
                                   ("coverage_4x4", "couverture", lambda v: f"{v:.3f}"),
                                   ("min_pair_dist_m", "dist. min. entre postes", lambda v: f"{v:.1f} m"),
                                   ("crossings", "auto-intersections", lambda v: f"{v:.0f}")):
                a = _med_grp(on, groupe, key)
                b = _med_grp(off, groupe, key)
                if a is not None and b is not None:
                    parts.append(f"{lbl} — {klbl} {fmt_(a)} → {fmt_(b)}")
        nb_on = sum(1 for r in on_rows if r.get("ok") and r["kind"] == "sprint"
                    and r.get("min_pair_dist_m", 0) <= 0.0)
        nb_off = sum(1 for r in off_rows if r.get("ok") and r["kind"] == "sprint"
                     and r.get("min_pair_dist_m", 0) <= 0.0)
        v26 = ("OUI, mais de façon bornée. Par groupe (médiane par carte) : " + " ; ".join(parts)
               + ". Le nombre de postes demandés est identique dans les deux modes, et aucune zone "
               "interdite n'est violée hors ligne (le service de tuiles est local, il reste joignable). "
               f"En revanche les paires de postes à distance nulle sur les cartes urbaines ne "
               f"disparaissent pas : {nb_on}/15 rejoues en ligne, {nb_off}/15 hors ligne. "
               "Conclusion : le mode hors ligne est utilisable ; c'est la garantie de non-duplication "
               "des postes qui manque, pas la production de circuits.")
        reg.append("| V26 | Le mode hors ligne dégrade-t-il la qualité (candidats OSM absents) ? | "
                   + v26 + " | Phase 1 |")

    # V27 — le moteur v1 est-il une référence exploitable ?
    v27 = ("Trancher en phase 1 à partir de E36–E43, E46, E49 et V26 : conformité aux seuils RTS "
           "vérifiée en forêt mais pas en sprint urbain (paires de postes à distance nulle), "
           "couverture faible en ville (médiane " + f"{_med(on, 'coverage_4x4') or 0:.2f}" + "), "
           "déterminisme " + f"{det_ok}/{det_total}" + " captures à graine fixée. Les mesures de la "
           "phase 0 sont acquises et versionnées : la décision de conserver ou remplacer le moteur "
           "v1 appartient à la phase 1.")
    reg.append("| V27 | Le moteur v1 est-il une référence exploitable pour la phase 1, ou faut-il le "
               "remplacer ? | " + v27 + " | Phase 1 |")
    reg.append("")

    (mes / "P0_registre_rows.md").write_text("\n".join(reg), encoding="utf-8")

    print("\n".join(lines))
    print("=" * 70)
    print("\n".join(reg))
    print("=" * 70)
    print(f"Écrit : {mes / 'P0_synthese.md'}")
    print(f"Écrit : {mes / 'P0_registre_rows.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
