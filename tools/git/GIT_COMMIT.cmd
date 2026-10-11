@echo off
setlocal EnableExtensions
cd /d "C:\stock"
set /p "MSG=Commit message: "
if "%MSG%"=="" (
  echo [ERROR] Commit message is required.
  pause
  exit /b 2
)
if exist ".venv_krx_menu\Scripts\python.exe" (
  ".venv_krx_menu\Scripts\python.exe" scripts\git_manager.py --root "%CD%" commit --message "%MSG%"
) else (
  py -3.11 scripts\git_manager.py --root "%CD%" commit --message "%MSG%"
)
echo.
pause
