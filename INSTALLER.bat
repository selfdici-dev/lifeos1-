@echo off
cd /d "%~dp0"
echo === Installation du poste de trading (une seule fois) ===
where python >nul 2>nul
if errorlevel 1 (
  echo Python n'est pas installe. Installe-le depuis https://www.python.org/downloads/
  echo en cochant bien la case "Add python.exe to PATH", puis relance ce fichier.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
  echo L'installation a echoue. Copie le message ci-dessus et envoie-le a Claude.
  pause
  exit /b 1
)
if not exist .env copy .env.exemple .env >nul
echo.
echo Installation terminee. Pour utiliser l'outil : double-clic sur LANCER.bat
pause
