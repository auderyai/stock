@echo off
setlocal
cd /d "%~dp0"
if not exist "..\.venv_krx_menu\Scripts\pythonw.exe" exit /b 1
start "" /b "..\.venv_krx_menu\Scripts\pythonw.exe" "scripts\run_job_progress_gui.py" supplement
exit /b 0
