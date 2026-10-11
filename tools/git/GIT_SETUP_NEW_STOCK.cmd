@echo off
setlocal EnableExtensions
set "ROOT=C:\stock"
set "PY_CMD="
where py >nul 2>nul && set "PY_CMD=py -3.11"
if not defined PY_CMD where python >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD (
  echo [ERROR] Python was not found.
  pause
  exit /b 2
)
if not exist "%ROOT%\scripts\git_manager.py" (
  echo [ERROR] %ROOT%\scripts\git_manager.py not found. Apply the patch first.
  pause
  exit /b 3
)
for /f "delims=" %%A in ('git config --global user.name 2^>nul') do set "GIT_NAME=%%A"
for /f "delims=" %%A in ('git config --global user.email 2^>nul') do set "GIT_EMAIL=%%A"
if not defined GIT_NAME set /p "GIT_NAME=Git user.name: "
if not defined GIT_EMAIL set /p "GIT_EMAIL=Git user.email: "
%PY_CMD% "%ROOT%\scripts\git_manager.py" --root "%ROOT%" init --name "%GIT_NAME%" --email "%GIT_EMAIL%"
if errorlevel 1 (
  pause
  exit /b 1
)
echo.
echo [OK] new_stock Git setup completed.
pause
