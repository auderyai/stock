@echo off
setlocal EnableExtensions
cd /d "C:\stock"
if exist ".venv_krx_menu\Scripts\python.exe" (
  ".venv_krx_menu\Scripts\python.exe" scripts\git_manager.py --root "%CD%" log --count 20
) else (
  py -3.11 scripts\git_manager.py --root "%CD%" log --count 20
)
echo.
pause
