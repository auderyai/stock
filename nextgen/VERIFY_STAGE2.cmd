@echo off
setlocal
chcp 65001 >nul 2>&1
title C:\stock Finplot Stage 2 Verify

set "VENV=C:\stock\.venv_finplot"
if not exist "%VENV%\Scripts\python.exe" (
  echo [ERROR] .venv_finplot missing.
  pause
  exit /b 1
)

cd /d C:\stock\nextgen
"%VENV%\Scripts\python.exe" -m krx_research_nextgen.application.verify_stage2
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo [OK] STAGE 2 VERIFY PASSED
) else (
  echo [ERROR] STAGE 2 VERIFY FAILED
)
pause
exit /b %RC%
