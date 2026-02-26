#!/usr/bin/env bash
# ============================================================
# AItraceur — Script de vérification rapide
# Usage : ./check.sh
# Lance des vérifications sur les 3 services et les tests
# ============================================================

set -e  # Arrête le script si une commande échoue

# Couleurs pour la lisibilité
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PASS=0
FAIL=0

ok()   { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL+1)); }
info() { echo -e "  ${BLUE}ℹ${NC} $1"; }

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  AItraceur — Vérification rapide          ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# ---- 1. Vérification des prérequis ----
echo -e "${YELLOW}[1/5] Prérequis${NC}"

if command -v python3 &>/dev/null; then
    ok "Python3 installé : $(python3 --version 2>&1)"
elif command -v python &>/dev/null; then
    ok "Python installé : $(python --version 2>&1)"
else
    fail "Python non trouvé — installer Python 3.11+"
fi

if command -v node &>/dev/null; then
    ok "Node.js installé : $(node --version)"
else
    fail "Node.js non trouvé — installer Node.js 18+"
fi

if command -v npm &>/dev/null; then
    ok "npm installé : $(npm --version)"
else
    fail "npm non trouvé"
fi

if command -v git &>/dev/null; then
    ok "Git installé : $(git --version)"
    LAST_COMMIT=$(git log --oneline -1 2>/dev/null || echo "aucun commit")
    info "Dernier commit : $LAST_COMMIT"
else
    fail "Git non trouvé"
fi

if command -v ollama &>/dev/null; then
    ok "Ollama installé : $(ollama --version 2>/dev/null | head -1 || echo 'version inconnue')"
else
    info "Ollama absent (optionnel — pour l'IA locale)"
fi

echo ""

# ---- 2. Vérification des dépendances installées ----
echo -e "${YELLOW}[2/5] Dépendances${NC}"

if [ -f "backend/requirements.txt" ]; then
    ok "backend/requirements.txt trouvé"
else
    fail "backend/requirements.txt manquant"
fi

if [ -d "backend/tile-service/node_modules" ]; then
    ok "Tile service : node_modules présent"
else
    fail "Tile service : node_modules absent → cd backend/tile-service && npm install"
fi

if [ -d "frontend/node_modules" ]; then
    ok "Frontend : node_modules présent"
else
    fail "Frontend : node_modules absent → cd frontend && npm install"
fi

# Vérifier sharp dans package.json
if grep -q '"sharp"' backend/tile-service/package.json 2>/dev/null; then
    ok "sharp déclaré dans tile-service/package.json"
else
    fail "sharp ABSENT de tile-service/package.json → Bug #1 à corriger (Étape 1a)"
fi

echo ""

# ---- 3. Vérification des services (si démarrés) ----
echo -e "${YELLOW}[3/5] Services (vérification si démarrés)${NC}"

# Backend FastAPI
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null | grep -q "200"; then
    ok "Backend FastAPI : en ligne (port 8000)"
else
    info "Backend FastAPI : hors ligne — démarrer avec 'cd backend && uvicorn src.main:app --reload'"
fi

# Tile service
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8089/health 2>/dev/null | grep -q "200"; then
    ok "Tile service : en ligne (port 8089)"
else
    info "Tile service : hors ligne — démarrer avec 'cd backend/tile-service && node server.js'"
fi

# Frontend
if curl -s -o /dev/null -w "%{http_code}" http://localhost:5173 2>/dev/null | grep -q "200"; then
    ok "Frontend React : en ligne (port 5173)"
else
    info "Frontend React : hors ligne — démarrer avec 'cd frontend && npm run dev'"
fi

echo ""

# ---- 4. Tests automatiques (si disponibles) ----
echo -e "${YELLOW}[4/5] Tests automatiques${NC}"

if [ -f "backend/tests/test_endpoints.py" ]; then
    info "Tests backend disponibles — lancement..."
    if command -v pytest &>/dev/null; then
        cd backend
        if pytest tests/ -q --tb=short 2>&1; then
            ok "Tests backend : tous passent"
        else
            fail "Tests backend : certains échouent"
        fi
        cd ..
    else
        info "pytest non trouvé — pip install pytest httpx"
    fi
else
    info "Tests backend non encore créés (Étape 2a)"
fi

if [ -f "backend/tile-service/test.js" ]; then
    info "Tests tile service disponibles — lancement..."
    cd backend/tile-service
    if node test.js 2>&1; then
        ok "Tests tile service : tous passent"
    else
        fail "Tests tile service : certains échouent"
    fi
    cd ../..
else
    info "Tests tile service non encore créés (Étape 2b)"
fi

echo ""

# ---- 5. Fichiers critiques ----
echo -e "${YELLOW}[5/5] Fichiers critiques${NC}"

declare -A FICHIERS=(
    ["backend/src/main.py"]="API principale"
    ["backend/tile-service/server.js"]="Rendu tuiles"
    ["frontend/src/App.jsx"]="Interface principale"
    ["frontend/src/components/MapViewer.jsx"]="Carte Leaflet"
    ["backend/src/services/generation/genetic_algo.py"]="Algo génétique"
    ["backend/src/services/generation/scorer.py"]="Scorer IOF"
    ["backend/src/data/ocad_semantics.json"]="Ontologie ISOM 2017"
)

for FICHIER in "${!FICHIERS[@]}"; do
    if [ -f "$FICHIER" ]; then
        ok "$FICHIER (${FICHIERS[$FICHIER]})"
    else
        fail "$FICHIER MANQUANT (${FICHIERS[$FICHIER]})"
    fi
done

# Dataset RAG
if [ -f "Lora/mondial_tracage_QR_v4.jsonl" ]; then
    ok "Dataset RAG présent"
else
    info "Dataset RAG absent → Bug #6, IA en mode zéro-shot (Étape 5b)"
fi

echo ""

# ---- Résumé ----
echo -e "${BLUE}============================================${NC}"
TOTAL=$((PASS+FAIL))
if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}  ✓ Tout est OK ($PASS/$TOTAL vérifications passées)${NC}"
else
    echo -e "${YELLOW}  ⚠ $FAIL problème(s) sur $TOTAL vérifications${NC}"
    echo -e "  Voir la liste ${RED}✗${NC} ci-dessus pour les détails"
fi
echo -e "${BLUE}============================================${NC}"
echo ""

# Lire STATUS.md pour rappeler l'étape suivante
if [ -f "STATUS.md" ]; then
    NEXT=$(grep "Prochaine étape" STATUS.md | head -1 | sed 's/.*\*\* //' | sed 's/ |.*//')
    echo -e "  📋 ${YELLOW}Prochaine étape :${NC} $NEXT"
    echo ""
fi
