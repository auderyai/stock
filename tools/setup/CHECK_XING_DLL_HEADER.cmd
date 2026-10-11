@echo off
setlocal
set "ROOT=C:\stock"
set "NEW_STOCK_ROOT=%ROOT%"
start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\check_xing_dll_header_gui.py"
