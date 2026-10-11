@echo off
cd /d "%~dp0.."
".venv_krx_menu\Scripts\python.exe" "scripts\update_ls_two_days.py" %*
pause
