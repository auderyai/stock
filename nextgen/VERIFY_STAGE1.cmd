@echo off
setlocal
chcp 65001 >nul 2>&1
title C:\stock Finplot Stage 1 Verify

set "VENV=C:\stock\.venv_finplot"
if not exist "%VENV%\Scripts\python.exe" (
  echo [ERROR] C:\stock\.venv_finplot is missing.
  pause
  exit /b 1
)

cd /d C:\stock\nextgen
"%VENV%\Scripts\python.exe" -m krx_research_nextgen.application.verify_stage1
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo [OK] STAGE 1 VERIFY PASSED
) else (
  echo [ERROR] STAGE 1 VERIFY FAILED
)
pause
exit /b %RC%
