@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run the source dependency installer first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "tools\material_workbench\install_shortcut.py"
if errorlevel 1 (
  pause
  exit /b 1
)
echo Desktop shortcut is ready.
