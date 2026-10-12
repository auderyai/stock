@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0REGISTER_PC_DRIVE_SYNC_TASK.ps1"
if errorlevel 1 (
  echo [ERROR] Scheduled task registration failed.
  pause
  exit /b 1
)
pause
