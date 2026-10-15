@echo off
cd /d "%~dp0"
.venv_krx_menu\Scripts\python.exe scripts\stock_drive_sync.py update-local
pause
