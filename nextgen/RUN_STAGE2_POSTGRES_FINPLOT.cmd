@echo off
setlocal
chcp 65001 >nul 2>&1
title C:\stock Finplot Stage 2 PostgreSQL

set "VENV=C:\stock\.venv_finplot"
if not exist "%VENV%\Scripts\python.exe" (
  echo [ERROR] .venv_finplot missing.
  pause
  exit /b 1
)

set "TICKER=%~1"
set "LIMIT=%~2"
if "%LIMIT%"=="" set "LIMIT=550"

cd /d C:\stock\nextgen

if "%TICKER%"=="" (
  "%VENV%\Scripts\python.exe" -m krx_research_nextgen.application.stage2_postgres_smoke
) else (
  "%VENV%\Scripts\python.exe" -m krx_research_nextgen.application.stage2_postgres_smoke "%TICKER%" "%LIMIT%"
)

set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] Stage 2 PostgreSQL Finplot smoke failed. code=%RC%
  pause
  exit /b %RC%
)
endlocal
