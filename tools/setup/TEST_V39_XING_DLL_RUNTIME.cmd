@echo off
setlocal EnableExtensions
set "ROOT=C:\stock"
set "PYTHONPATH=%ROOT%\src"
set "NEW_STOCK_ROOT=%ROOT%"

if not exist "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" (
  echo [ERROR] main .venv pythonw.exe not found.
  pause
  exit /b 1
)
if not exist "%ROOT%\.venv_xing32\Scripts\python.exe" (
  echo [ERROR] .venv_xing32 not found.
  pause
  exit /b 2
)

start "" "%ROOT%\.venv_krx_menu\Scripts\pythonw.exe" "%ROOT%\scripts\test_v39_xing_runtime_gui.py"
exit /b 0
