@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist ".venv_krx_menu\Scripts\python.exe" (
  echo [ERROR] .venv_krx_menu Python not found.
  exit /b 1
)
".venv_krx_menu\Scripts\python.exe" "scripts\stock_drive_sync.py" sync-local
exit /b %ERRORLEVEL%
