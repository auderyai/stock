@echo off
setlocal EnableExtensions

rem AuderyAI Stock laptop bootstrap. This file never copies secrets or database files.
set "ROOT=C:\stock"
set "REMOTE=https://github.com/auderyai/stock.git"
set "PY_MAIN=%ROOT%\.venv_krx_menu\Scripts\python.exe"
set "PY_NEXT=%ROOT%\.venv_finplot\Scripts\python.exe"

if /I "%~1"=="verify" goto verify
if not "%~1"=="" goto usage

echo [1/6] Checking required programs...
where git.exe >nul 2>&1 || goto missing_git
py -3.11 -c "import struct,sys;raise SystemExit(0 if sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64 else 1)" >nul 2>&1 || goto missing_python

echo [2/6] Preparing C:\stock...
if exist "%ROOT%\.git\NUL" goto existing_repo
if exist "%ROOT%\NUL" goto occupied_root
git clone "%REMOTE%" "%ROOT%" || goto failed
goto repository_ready

:existing_repo
pushd "%ROOT%" || goto failed
set "DIRTY="
for /f "delims=" %%G in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
  echo [SAFE] Existing local changes found. Git pull was skipped.
) else (
  git pull --ff-only origin main || goto failed_popd
)
popd

:repository_ready
echo [3/6] Creating the main Python environment...
if not exist "%PY_MAIN%" py -3.11 -m venv "%ROOT%\.venv_krx_menu" || goto failed
"%PY_MAIN%" -m pip install --upgrade pip || goto failed
"%PY_MAIN%" -m pip install -r "%ROOT%\requirements.in" -e "%ROOT%" || goto failed
"%PY_MAIN%" -m pip install -r "%ROOT%\tools\setup\requirements-google-drive.txt" || goto failed

echo [4/6] Creating the chart application environment...
if not exist "%PY_NEXT%" py -3.11 -m venv "%ROOT%\.venv_finplot" || goto failed
"%PY_NEXT%" -m pip install --upgrade pip || goto failed
"%PY_NEXT%" -m pip install -e "%ROOT%\nextgen" || goto failed

echo [5/6] Preparing a secret-free local configuration template...
if not exist "%ROOT%\.env" copy /Y "%ROOT%\.env.example" "%ROOT%\.env" >nul || goto failed

echo [6/6] Verifying installed source code...
set "PYTHONPATH=%ROOT%\src;%ROOT%\nextgen\src"
"%PY_MAIN%" -m compileall -q "%ROOT%\src" "%ROOT%\scripts" || goto failed
"%PY_NEXT%" -m compileall -q "%ROOT%\nextgen\src" || goto failed

echo.
echo [OK] Laptop program files and Python environments are ready.
echo [NEXT] 1. Install PostgreSQL 16 and restore the verified desktop pg_dump.
echo [NEXT] 2. Enter this laptop's DB and API credentials in C:\stock\.env.
echo [NEXT] 3. Run C:\stock\tools\setup\SETUP_GOOGLE_DRIVE_OAUTH_ONCE.cmd.
echo [NEXT] 4. Run this file again with: INSTALL_STOCK_LAPTOP.cmd verify
echo [SAFE] Financial startup sync is not registered until multi-PC acknowledgements exist.
exit /b 0

:verify
echo [1/4] Verifying the prepared laptop...
if not exist "%ROOT%\.git\NUL" goto missing_repo
if not exist "%PY_MAIN%" goto missing_environment
if not exist "%ROOT%\.env" goto missing_configuration

echo [2/4] Verifying PostgreSQL without changing data...
set "PYTHONPATH=%ROOT%\src"
"%PY_MAIN%" "%ROOT%\scripts\setup_postgresql.py" || goto failed

echo [3/4] Verifying this Windows user's encrypted Google Drive credential...
"%PY_MAIN%" "%ROOT%\tools\setup\google_drive_oauth_once.py" --verify-stored || goto missing_oauth

echo [4/4] Registering only the idempotent daily Drive delta sync...
call "%ROOT%\tools\setup\REGISTER_PC_DRIVE_SYNC_TASK.cmd" || goto failed
call "%ROOT%\tools\setup\RUN_PC_DRIVE_SYNC.cmd" || goto failed
echo.
echo [OK] Laptop verification and daily delta sync setup completed.
echo [SAFE] OpenDART financial cleanup remains disabled on this laptop for now.
exit /b 0

:usage
echo Usage: %~nx0 [verify]
exit /b 2

:missing_git
echo [ERROR] Git for Windows is not installed or not available in PATH.
exit /b 2

:missing_python
echo [ERROR] 64-bit Python 3.11 is not installed or the py launcher cannot find it.
exit /b 2

:occupied_root
echo [ERROR] C:\stock exists but is not a Git repository. No file was overwritten.
echo Move or inspect that folder, then run this patch again.
exit /b 2

:missing_repo
echo [ERROR] C:\stock is not a Git repository. Run this patch without arguments first.
exit /b 2

:missing_environment
echo [ERROR] The laptop Python environment is missing. Run this patch without arguments first.
exit /b 2

:missing_configuration
echo [ERROR] C:\stock\.env is missing. Run this patch without arguments first.
exit /b 2

:missing_oauth
echo [ERROR] Google Drive OAuth is not configured for this laptop Windows user.
echo Run C:\stock\tools\setup\SETUP_GOOGLE_DRIVE_OAUTH_ONCE.cmd, then retry verify.
exit /b 2

:failed_popd
popd
:failed
echo [ERROR] Laptop setup stopped. Completed files were preserved for safe retry.
exit /b 1
