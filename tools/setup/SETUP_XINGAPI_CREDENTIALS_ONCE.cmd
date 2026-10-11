@echo off
setlocal
set "ROOT=C:\stock"
start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\setup_xing_credentials_gui.py"
