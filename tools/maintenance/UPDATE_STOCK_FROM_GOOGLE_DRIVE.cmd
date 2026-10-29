@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%" || exit /b 2
"%ROOT%\.venv_krx_menu\Scripts\python.exe" "%ROOT%\scripts\stock_drive_sync.py" update-local
pause
