@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run the desktop source dependency installer first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "tools\material_workbench\启动.py"
