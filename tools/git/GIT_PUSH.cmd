@echo off
setlocal EnableExtensions
cd /d "C:\stock"
where git >nul 2>nul || (
  echo [ERROR] Git for Windows was not found.
  pause
  exit /b 2
)
git remote get-url origin >nul 2>nul || (
  echo [ERROR] origin is not configured. Run GIT_REMOTE_SET.cmd first.
  pause
  exit /b 3
)
git push -u origin main
if errorlevel 1 (
  echo.
  echo [ERROR] Push failed. Check GitHub authentication/permissions.
  pause
  exit /b 1
)
echo.
echo [OK] main pushed to origin.
pause
