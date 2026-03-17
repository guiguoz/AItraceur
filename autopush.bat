@echo off
:: autopush.bat — Pousse automatiquement les modifications sur GitHub
:: Usage : double-clic ou autopush.bat [message optionnel]

cd /d %~dp0

:: Vérifier s'il y a des modifications
git diff --quiet && git diff --staged --quiet && git ls-files --others --exclude-standard | findstr . >nul 2>&1
if errorlevel 1 (
    echo Aucune modification a pousser.
    pause
    exit /b 0
)

:: Construire le message de commit
set "DATE_STR="
for /f "tokens=1-2 delims= " %%a in ('powershell -command "Get-Date -Format 'yyyy-MM-dd HH:mm'"') do set DATE_STR=%%a %%b

:: Lister les fichiers modifiés (5 max)
set "FILES="
for /f "tokens=*" %%f in ('git diff --name-only 2^>nul') do (
    if "!FILES!"=="" (set FILES=%%f) else (set FILES=!FILES!, %%f)
)
for /f "tokens=*" %%f in ('git ls-files --others --exclude-standard 2^>nul') do (
    if "!FILES!"=="" (set FILES=%%f) else (set FILES=!FILES!, %%f)
)

setlocal enabledelayedexpansion

:: Message personnalisé ou automatique
if "%~1"=="" (
    set "MSG=[%DATE_STR%] Màj : !FILES!"
) else (
    set "MSG=[%DATE_STR%] %~1"
)

echo.
echo === AItraceur autopush ===
echo Message : !MSG!
echo.
git status --short
echo.

git add -A
git commit -m "!MSG!"
git push

echo.
echo Pousse sur GitHub.
pause
