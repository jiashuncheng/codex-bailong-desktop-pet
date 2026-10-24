@echo off
for %%I in ("%~dp0*.exe") do start "" "%%~fI" --manage
