@echo off
setlocal
set "ROOT=C:\stock"
start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\scan_xing_devcenter_schema_sources_gui.py"
