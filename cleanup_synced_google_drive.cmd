@echo off
cd /d "%~dp0"
set /p THROUGH=Delete synced Drive data through date (YYYY-MM-DD): 
.venv_krx_menu\Scripts\python.exe scripts\stock_drive_sync.py cleanup-synced --through "%THROUGH%"
if errorlevel 1 goto end
set /p CONFIRM=Type DELETE_SYNCED_DRIVE_DELTAS to delete: 
if not "%CONFIRM%"=="DELETE_SYNCED_DRIVE_DELTAS" goto end
.venv_krx_menu\Scripts\python.exe scripts\stock_drive_sync.py cleanup-synced --through "%THROUGH%" --confirm DELETE_SYNCED_DRIVE_DELTAS
:end
pause
