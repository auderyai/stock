@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
title KRX Job Menu

set "ROOT=C:\stock"
set "PY=C:\stock\.venv_krx_menu\Scripts\python.exe"
set "PYW=C:\stock\.venv_krx_menu\Scripts\pythonw.exe"
set "SCRIPT=C:\stock\scripts\run_krx_menu.py"
set "PYTHONPATH=C:\stock\src;%PYTHONPATH%"
set "PYTHONUTF8=1"
set "RUNTIME_LOG=C:\stock\logs\runtime\run_krx_menu_runtime.log"

if not exist "%PY%" (
  echo [ERROR] Python not found: %PY%
  pause
  exit /b 1
)
if not exist "%PYW%" (
  echo [ERROR] Python window runtime not found: %PYW%
  pause
  exit /b 1
)
if not exist "%SCRIPT%" (
  echo [ERROR] Script not found: %SCRIPT%
  pause
  exit /b 1
)

if exist "C:\stock\tools\maintenance\cleanup_logs.py" "%PY%" "C:\stock\tools\maintenance\cleanup_logs.py" --strict --quiet
cd /d "%ROOT%"
echo ==================================================>"%RUNTIME_LOG%"
echo [%date% %time%] run_krx_menu DISPATCH>>"%RUNTIME_LOG%"
echo CWD=%CD%>>"%RUNTIME_LOG%"
echo PYW=%PYW%>>"%RUNTIME_LOG%"
echo SCRIPT=%SCRIPT%>>"%RUNTIME_LOG%"
start "" /D "%ROOT%" "%PYW%" "%SCRIPT%"
if errorlevel 1 (
  echo [%date% %time%] run_krx_menu DISPATCH_FAILED=!ERRORLEVEL!>>"%RUNTIME_LOG%"
  type "%RUNTIME_LOG%"
  pause
  exit /b 1
)
echo [%date% %time%] run_krx_menu DISPATCHED>>"%RUNTIME_LOG%"
endlocal
exit /b 0
