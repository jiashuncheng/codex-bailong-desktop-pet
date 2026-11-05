@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run the desktop source dependency installer first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r tools/material_workbench/requirements-matting.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" tools/material_workbench/download_models.py
if errorlevel 1 goto failed
echo Workbench dependencies and model are ready.
pause
exit /b 0
:failed
echo Installation failed. Review the error above.
pause
exit /b 1
