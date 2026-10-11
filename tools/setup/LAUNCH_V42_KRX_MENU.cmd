@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist ".venv_krx_menu\Scripts\pythonw.exe" (
  echo [ERROR] .venv pythonw.exe not found.
  pause
  exit /b 2
)
start "KRX Job Menu V42" ".venv_krx_menu\Scripts\pythonw.exe" "scripts\run_krx_menu.py"
exit /b 0
