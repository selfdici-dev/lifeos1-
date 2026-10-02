@echo off
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
  echo Git n'est pas installe : retelecharge le ZIP depuis GitHub a la place.
  pause
  exit /b 1
)
git pull
if errorlevel 1 (
  echo La mise a jour a echoue. Copie le message ci-dessus et envoie-le a Claude.
  pause
  exit /b 1
)
.venv\Scripts\python -m pip install --quiet -r requirements.txt
echo Mise a jour terminee. Tes fichiers personnels (.env, journal, reglages) n'ont pas ete touches.
pause
