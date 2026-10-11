@echo off
setlocal
set "ROOT=C:\stock"
start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\setup_ls_openapi_credentials_once.py"
