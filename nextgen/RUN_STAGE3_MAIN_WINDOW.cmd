@echo off
setlocal
chcp 65001 >nul 2>&1
title C:\stock NextGen Stage 3
set "VENV=C:\stock\.venv_finplot"
if not exist "%VENV%\Scripts\python.exe" (
  echo [ERROR] .venv_finplot missing.
  pause
  exit /b 1
)
cd /d C:\stock\nextgen
"%VENV%\Scripts\python.exe" -m krx_research_nextgen.application.stage3_app
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] Stage 3 main window failed. code=%RC%
  pause
  exit /b %RC%
)
endlocal
