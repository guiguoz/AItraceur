#!/bin/bash
# autopush.sh — Pousse automatiquement les modifications sur GitHub
# Usage : bash autopush.sh [message optionnel]

set -e

# Vérifier qu'on est dans un repo git
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "Erreur : pas de repo git ici."
    exit 1
fi

# Vérifier qu'il y a des modifications
if git diff --quiet && git diff --staged --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    echo "Aucune modification à pousser."
    exit 0
fi

# Lister les fichiers modifiés pour le message de commit
MODIFIED=$(git diff --name-only 2>/dev/null | head -5 | tr '\n' ', ' | sed 's/,$//')
ADDED=$(git ls-files --others --exclude-standard 2>/dev/null | head -3 | tr '\n' ', ' | sed 's/,$//')
DELETED=$(git diff --name-only --diff-filter=D 2>/dev/null | head -3 | tr '\n' ', ' | sed 's/,$//')

# Compter le total de fichiers changés
TOTAL=$(git diff --name-only | wc -l)
TOTAL=$((TOTAL + $(git ls-files --others --exclude-standard | wc -l)))

# Construire le message de commit
DATE=$(date '+%Y-%m-%d %H:%M')

if [ -n "$1" ]; then
    # Message personnalisé fourni en argument
    MSG="[$DATE] $1"
else
    # Message automatique
    SUMMARY=""
    [ -n "$MODIFIED" ] && SUMMARY="modif: $MODIFIED"
    [ -n "$ADDED" ]    && SUMMARY="$SUMMARY | ajout: $ADDED"
    [ -n "$DELETED" ]  && SUMMARY="$SUMMARY | suppr: $DELETED"
    SUMMARY=$(echo "$SUMMARY" | sed 's/^ | //')

    if [ "$TOTAL" -gt 8 ]; then
        MSG="[$DATE] Màj $TOTAL fichiers"
    else
        MSG="[$DATE] $SUMMARY"
    fi
fi

# Afficher le résumé
echo ""
echo "=== AItraceur autopush ==="
echo "Message : $MSG"
echo ""
git status --short
echo ""

# Ajouter, committer, pousser
git add -A
git commit -m "$MSG"
git push

echo ""
echo "Poussé sur GitHub."
