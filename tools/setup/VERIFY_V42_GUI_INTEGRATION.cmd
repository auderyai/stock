@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist ".venv_krx_menu\Scripts\python.exe" (
  echo [ERROR] .venv Python not found.
  exit /b 2
)
".venv_krx_menu\Scripts\python.exe" scripts\verify_v42_baseline_ready.py || exit /b 2
".venv_krx_menu\Scripts\python.exe" scripts\verify_v42_gui_git_static.py || exit /b 2
".venv_krx_menu\Scripts\python.exe" scripts\verify_v42_gui_unit.py || exit /b 2
echo [PASS] V42 GUI/service integration is ready.
exit /b 0
