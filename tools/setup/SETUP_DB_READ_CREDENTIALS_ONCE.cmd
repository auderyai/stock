@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv_krx_menu\Scripts\pythonw.exe" (
  echo [ERROR] .venv_krx_menu\Scripts\pythonw.exe was not found.
  echo Run SETUP_NEW_STOCK_ENV.cmd first.
  pause
  exit /b 1
)
start "" ".venv_krx_menu\Scripts\pythonw.exe" "scripts\setup_db_read_credentials_once.py"
exit /b 0
