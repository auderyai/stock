@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY=%CD%\.venv_finplot\Scripts\python.exe"
set "PYTHONPATH=%CD%\src;%CD%\nextgen\src"
set "QT_QPA_PLATFORM=offscreen"
if not exist "%PY%" (
  echo [ERROR] .venv_finplot missing.
  exit /b 2
)
"%PY%" -m compileall -q -f nextgen\src || exit /b 1
for %%M in (verify_stage1 verify_stage3 verify_stage4 verify_stage4_gui_final verify_runtime) do (
  "%PY%" -m krx_research_nextgen.application.%%M || exit /b 1
)
echo [OK] PyQt6 / Finplot / PostgreSQL NextGen verification passed.
exit /b 0
