@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%" || exit /b 2
set /p THROUGH=Delete synced Drive data through date (YYYY-MM-DD):
"%ROOT%\.venv_krx_menu\Scripts\python.exe" "%ROOT%\scripts\stock_drive_sync.py" cleanup-synced --through "%THROUGH%"
if errorlevel 1 goto end
set /p CONFIRM=Type DELETE_SYNCED_DRIVE_DELTAS to delete:
if not "%CONFIRM%"=="DELETE_SYNCED_DRIVE_DELTAS" goto end
"%ROOT%\.venv_krx_menu\Scripts\python.exe" "%ROOT%\scripts\stock_drive_sync.py" cleanup-synced --through "%THROUGH%" --confirm DELETE_SYNCED_DRIVE_DELTAS
:end
pause
