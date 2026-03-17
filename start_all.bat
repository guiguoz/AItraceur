@echo off
title AItraceur - Lanceur Global
echo ========================================================
echo        AItraceur - Demarrage des services...
echo ========================================================
echo.

echo [1/3] Backend FastAPI (port 8000)...
start "AItraceur - Backend" cmd /k "cd /d %~dp0backend && uvicorn src.main:app --reload"

echo [2/3] Tile Service (port 8089)...
start "AItraceur - Tiles" cmd /k "cd /d %~dp0backend\tile-service && node server.js"

echo [3/3] Frontend React (port 5173)...
start "AItraceur - Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo Attente du demarrage (5 secondes)...
timeout /t 5 /nobreak >nul

echo Ouverture du navigateur...
start http://localhost:5173

echo.
echo ========================================================
echo  AItraceur est lance !
echo  Ferme les 3 fenetres de commande pour tout arreter.
echo ========================================================
