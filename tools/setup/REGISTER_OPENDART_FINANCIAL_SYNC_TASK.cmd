@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0REGISTER_OPENDART_FINANCIAL_SYNC_TASK.ps1"
exit /b %ERRORLEVEL%
