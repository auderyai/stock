@echo off
setlocal
set "ROOT=C:\stock"
set "NEW_STOCK_ROOT=%ROOT%"
if not exist "%ROOT%\resources\xing\schemas" mkdir "%ROOT%\resources\xing\schemas"
start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\audit_xing_dll_packet_schemas_gui.py"
