@echo off
setlocal EnableExtensions
set "SOURCE=C:\stock\KRX_Menu_Launcher\RUN_OPENDART_FINANCIAL_SYNC_ON_LOGON.vbs"
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Stock OpenDART Financial Sync.vbs"
if not exist "%SOURCE%" (
  echo [ERROR] Startup launcher not found: %SOURCE%
  exit /b 2
)
copy /Y "%SOURCE%" "%TARGET%" >nul
if not errorlevel 1 echo [OK] Windows startup sync registered: %TARGET%
if errorlevel 1 exit /b %ERRORLEVEL%
call "%~dp0REGISTER_OPENDART_FINANCIAL_SYNC_TASK.cmd"
exit /b %ERRORLEVEL%
