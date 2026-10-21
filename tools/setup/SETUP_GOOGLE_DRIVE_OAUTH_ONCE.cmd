@echo off
setlocal
set "ROOT=C:\stock"
set "PYTHON=%ROOT%\.venv_krx_menu\Scripts\python.exe"
set "SCRIPT=%ROOT%\tools\setup\google_drive_oauth_once.py"
set "REQUIREMENTS=%ROOT%\tools\setup\requirements-google-drive.txt"

if not exist "%PYTHON%" (
  echo [ERROR] Python environment not found: %PYTHON%
  pause
  exit /b 1
)

"%PYTHON%" -c "import google_auth_oauthlib" >nul 2>&1
if errorlevel 1 (
  echo Installing the isolated Google Drive OAuth dependency...
  "%PYTHON%" -m pip install -r "%REQUIREMENTS%"
  if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
  )
)

"%PYTHON%" "%SCRIPT%"
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
  echo Google Drive OAuth setup completed.
) else (
  echo Google Drive OAuth setup failed. Exit code: %RESULT%
)
pause
exit /b %RESULT%
