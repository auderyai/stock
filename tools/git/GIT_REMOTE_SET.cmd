@echo off
setlocal EnableExtensions
cd /d "C:\stock"
where git >nul 2>nul || (
  echo [ERROR] Git for Windows was not found.
  pause
  exit /b 2
)
set /p "REMOTE_URL=Git remote URL (origin): "
if "%REMOTE_URL%"=="" (
  echo [ERROR] Remote URL is required.
  pause
  exit /b 3
)
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  git remote add origin "%REMOTE_URL%"
) else (
  git remote set-url origin "%REMOTE_URL%"
)
if errorlevel 1 (
  echo [ERROR] Failed to configure origin.
  pause
  exit /b 1
)
echo.
git remote -v
echo.
echo [OK] origin configured.
pause
