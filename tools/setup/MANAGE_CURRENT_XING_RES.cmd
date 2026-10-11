@echo off
setlocal
set "ROOT=C:\stock"
set "NEW_STOCK_ROOT=%ROOT%"
if not exist "%ROOT%\resources\xing\current_res" mkdir "%ROOT%\resources\xing\current_res"
start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\manage_current_xing_res_gui.py"
