@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Il faut d'abord installer l'outil : double-clic sur INSTALLER.bat
  pause
  exit /b 1
)
.venv\Scripts\python -m poste
pause
