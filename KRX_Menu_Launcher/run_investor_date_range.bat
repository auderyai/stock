@echo off
setlocal
cd /d "%~dp0"
if not exist "..\.venv_krx_menu\Scripts\pythonw.exe" exit /b 1
start "" /b "..\.venv_krx_menu\Scripts\pythonw.exe" "scripts\run_investor_date_range_gui.py"
exit /b 0
