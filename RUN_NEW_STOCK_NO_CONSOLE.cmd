@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv_finplot\Scripts\pythonw.exe" (
  echo [ERROR] .venv_finplot is missing.
  pause
  exit /b 2
)
set "PYTHONPATH=%CD%\src;%CD%\nextgen\src"
start "" ".venv_finplot\Scripts\pythonw.exe" -m krx_research_nextgen.application.stage4_app
exit /b 0
