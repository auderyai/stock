@echo off
setlocal
chcp 65001 >nul 2>&1
title C:\stock NextGen Stage 4

set "VENV=C:\stock\.venv_finplot"
if not exist "%VENV%\Scripts\python.exe" (
  echo [ERROR] .venv_finplot missing.
  pause
  exit /b 1
)

cd /d C:\stock\nextgen
set "PYTHONPATH=C:\stock\src;C:\stock\nextgen\src"
"%VENV%\Scripts\python.exe" -m krx_research_nextgen.application.stage4_app
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [ERROR] Stage 4 main window failed. code=%RC%
  pause
  exit /b %RC%
)
endlocal
