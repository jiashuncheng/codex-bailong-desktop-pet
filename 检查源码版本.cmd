@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows.ps1" -Action check
if errorlevel 1 pause
