@echo off
setlocal
chcp 65001 >nul 2>&1
title C:\stock NextGen Stage 4 Verify
set "VENV=C:\stock\.venv_finplot"
cd /d C:\stock\nextgen
"%VENV%\Scripts\python.exe" -m krx_research_nextgen.application.verify_stage4
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [OK] STAGE 4 VERIFY PASSED
) else (
  echo [ERROR] STAGE 4 VERIFY FAILED
)
pause
exit /b %RC%
