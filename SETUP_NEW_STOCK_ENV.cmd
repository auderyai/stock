@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "VENV=%CD%\.venv_finplot"
if not exist "%VENV%\Scripts\python.exe" py -3.11 -m venv "%VENV%" || exit /b 1
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
"%VENV%\Scripts\python.exe" -m pip install -e "%CD%\nextgen" || exit /b 1
call "%CD%\VERIFY_NEW_STOCK.cmd"
exit /b %ERRORLEVEL%
