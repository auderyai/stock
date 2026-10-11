@echo off
setlocal
set "ROOT=C:\stock"
start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\check_xing32_runtime_gui.py"
