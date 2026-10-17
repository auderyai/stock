@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=C:\stock"
set "PY=%ROOT%\.venv_krx_menu\Scripts\python.exe"
set "SCRIPT=%ROOT%\scripts\opendart_financial_backfill.py"
set "LOG_DIR=%ROOT%\logs\financial_backfill"
set "LOG=%LOG_DIR%\startup_sync.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo [%date% %time%] START>>"%LOG%"
if not exist "%PY%" (
  echo [ERROR] Python not found: %PY%>>"%LOG%"
  exit /b 2
)
set "PYTHONPATH=%ROOT%\src"
set "PYTHONUTF8=1"
"%PY%" "%SCRIPT%" --years 2025,2024,2023 sync-ready-local >>"%LOG%" 2>&1
set "RC=!ERRORLEVEL!"
echo [%date% %time%] END rc=!RC!>>"%LOG%"
exit /b !RC!
