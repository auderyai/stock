@echo off
setlocal EnableExtensions
set "PY=C:\stock\.venv_krx_menu\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\stock\.venv_finplot\Scripts\python.exe"
"%PY%" "C:\stock\tools\maintenance\cleanup_logs.py" --strict
exit /b %ERRORLEVEL%
