@echo off
setlocal EnableExtensions
cd /d "C:\stock"
if not exist ".venv_finplot\Scripts\pythonw.exe" exit /b 2
set "PYTHONPATH=C:\stock\src;C:\stock\nextgen\src"
start "" ".venv_finplot\Scripts\pythonw.exe" -m krx_research_nextgen.application.stage4_app
exit /b 0
