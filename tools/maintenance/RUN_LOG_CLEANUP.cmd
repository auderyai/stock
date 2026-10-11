@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "PY=C:\stock\.venv_krx_menu\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\stock\.venv_finplot\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python runtime not found.
  pause
  exit /b 1
)
"%PY%" "C:\stock\tools\maintenance\cleanup_logs.py" --keep 1
exit /b %ERRORLEVEL%
