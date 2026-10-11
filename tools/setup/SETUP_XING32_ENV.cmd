@echo off
setlocal
set "ROOT=C:\stock"
start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\setup_xing32_environment_gui.py"
