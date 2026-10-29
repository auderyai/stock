@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%" || exit /b 2
if not exist "%ROOT%\.venv_krx_menu\Scripts\python.exe" (
  echo [ERROR] .venv_krx_menu Python not found.
  pause
  exit /b 2
)
set "PYTHONPATH=%ROOT%\src"
set "PYTHONUTF8=1"
"%ROOT%\.venv_krx_menu\Scripts\python.exe" "%ROOT%\scripts\recover_new_listing_ohlcv.py" --apply %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" echo [FAIL] Recovery stopped with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
