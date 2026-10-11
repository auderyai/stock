@echo off
set "ROOT=C:\stock"
set "PYTHONPATH=C:\stock\src;%PYTHONPATH%"
set "PYTHONUTF8=1"




set "ROOT=C:\stock"













setlocal



cd /d "%~dp0"



if not exist "..\.venv_krx_menu\Scripts\pythonw.exe" exit /b 1



start "" /b "..\.venv_krx_menu\Scripts\pythonw.exe" "scripts\run_job_progress_gui.py" daily



exit /b 0
