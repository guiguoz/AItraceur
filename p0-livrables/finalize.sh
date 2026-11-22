#!/usr/bin/env bash
# Finalisation de la revue P0 — à lancer dans le clone Arena une fois que les
# huit artefacts sont versionnés sur origin/plan/p0-socle.
#
#   bash p0-livrables/finalize.sh
#
# Produit :
#   p0-livrables/P0_livrables.patch   — patch des trois fichiers texte
#   p0-livrables/P0_synthese.md       — synthèse des mesures
#   p0-livrables/P0_registre_rows.md  — lignes de registre issues des mesures
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/p0-livrables"
WT="/tmp/wt-p0-final"

echo "== 1. récupération de la branche distante =="
cd "$ROOT"
git fetch origin "+refs/heads/plan/p0-socle:refs/remotes/origin/plan/p0-socle"
TIP="$(git rev-parse --short origin/plan/p0-socle)"
echo "   tip = $TIP"

echo "== 2. worktree sur le tip distant =="
git worktree remove "$WT" --force 2>/dev/null || true
git worktree prune
git worktree add --detach "$WT" origin/plan/p0-socle >/dev/null

echo "== 3. contrôle des huit artefacts =="
MISSING=0
for f in P0_baseline_results.jsonl P0_baseline_summary.md P0_baseline_determinism.json \
         P0_baseline_run_metadata.json P0_baseline_offline_results.jsonl \
         P0_baseline_offline_summary.md P0_baseline_offline_determinism.json \
         P0_baseline_offline_run_metadata.json; do
  if [ ! -s "$WT/docs/plan/mesures/$f" ]; then
    echo "   MANQUANT ou vide : $f"
    MISSING=1
  else
    printf "   ok  %-44s %8s octets\n" "$f" "$(wc -c < "$WT/docs/plan/mesures/$f")"
  fi
done
if [ "$MISSING" = "1" ]; then
  echo "!! artefacts incomplets — arrêt"; exit 1
fi

echo "== 4. analyse des mesures =="
python3 "$ROOT/p0-outils/analyze_baseline.py" "$WT" > /tmp/p0_analyse.out
cp "$WT/docs/plan/mesures/P0_synthese.md" "$OUT/P0_synthese.md"
cp "$WT/docs/plan/mesures/P0_registre_rows.md" "$OUT/P0_registre_rows.md"

echo "== 5. injection du registre et du compte rendu =="
python3 "$OUT/apply_registre.py" "$WT"
python3 "$OUT/apply_p0_crc.py" "$WT"

echo "== 5 bis. ajout de l'inventaire des captures (fichier nouveau) =="
cp "$OUT/P0_captures.md" "$WT/docs/plan/mesures/P0_captures.md"
# `git add -N` : le fichier apparaît dans `git diff` comme ajout, sans être indexé
( cd "$WT" && git add -N docs/plan/mesures/P0_captures.md )

echo "== 6. patch =="
cd "$WT"
git diff --stat
git diff > "$OUT/P0_livrables.patch"
mkdir -p "$OUT/fichiers"
cp docs/plan/REGISTRE.md "$OUT/fichiers/REGISTRE.md"
cp docs/plan/comptes-rendus/P0.md "$OUT/fichiers/P0.md"
cp docs/plan/mesures/P0_captures.md "$OUT/fichiers/P0_captures.md"
echo "   patch : $OUT/P0_livrables.patch ($(wc -l < "$OUT/P0_livrables.patch") lignes)"

git worktree remove "$WT" --force
echo "== terminé =="
