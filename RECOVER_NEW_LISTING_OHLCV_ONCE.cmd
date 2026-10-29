@echo off
setlocal
chcp 65001 >nul
cd /d C:\stock
if not exist ".venv_krx_menu\Scripts\python.exe" (
  echo [ERROR] .venv_krx_menu Python not found.
  pause
  exit /b 2
)
set "PYTHONPATH=src"
set "PYTHONUTF8=1"
".venv_krx_menu\Scripts\python.exe" "scripts\recover_new_listing_ohlcv.py" --apply %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo [FAIL] Recovery stopped with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
