@echo off
setlocal EnableExtensions
set "ROOT=C:\stock"
set "PYTHON=%ROOT%\.venv_krx_menu\Scripts\pythonw.exe"
set "PATCH=%ROOT%\tools\setup\setup_openai_api_key_once.py"
if not exist "%PYTHON%" (
  echo [ERROR] Python runtime not found: %PYTHON%
  pause
  exit /b 1
)
if not exist "%PATCH%" (
  echo [ERROR] Setup patch not found: %PATCH%
  pause
  exit /b 1
)
start "" "%PYTHON%" "%PATCH%"
exit /b 0
