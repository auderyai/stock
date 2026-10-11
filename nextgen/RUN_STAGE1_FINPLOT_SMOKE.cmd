@echo off
setlocal
chcp 65001 >nul 2>&1
title C:\stock Finplot Stage 1 Smoke

set "VENV=C:\stock\.venv_finplot"
if not exist "%VENV%\Scripts\python.exe" (
  echo [ERROR] C:\stock\.venv_finplot is missing.
  echo Run INSTALL_AND_VERIFY_STAGE1.cmd first.
  pause
  exit /b 1
)

cd /d C:\stock\nextgen
"%VENV%\Scripts\python.exe" -m krx_research_nextgen.application.stage1_smoke
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [ERROR] Finplot smoke test failed. code=%RC%
  pause
  exit /b %RC%
)
endlocal
