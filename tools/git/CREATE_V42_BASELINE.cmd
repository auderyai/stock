@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."
set "PY=.venv_krx_menu\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Python not found: %PY%
  exit /b 2
)
"%PY%" scripts\verify_v42_baseline_ready.py --root "%CD%" || exit /b 2
"%PY%" scripts\verify_v42_gui_git_static.py || exit /b 2
where git >nul 2>nul || (
  echo [ERROR] git.exe not found in PATH.
  exit /b 3
)
if not exist ".git" (
  git init || exit /b 4
)
for /f "delims=" %%N in ('git config --get user.name 2^>nul') do set "GITNAME=%%N"
if not defined GITNAME (
  set /p "GITNAME=Git user.name: "
  if not defined GITNAME exit /b 5
  git config user.name "%GITNAME%"
)
for /f "delims=" %%E in ('git config --get user.email 2^>nul') do set "GITEMAIL=%%E"
if not defined GITEMAIL (
  set /p "GITEMAIL=Git user.email: "
  if not defined GITEMAIL exit /b 5
  git config user.email "%GITEMAIL%"
)

echo [1/4] Staging current source baseline...
git add src scripts tools KRX_Menu_Launcher config .gitattributes 2>nul
if errorlevel 1 (
  git add src scripts tools KRX_Menu_Launcher config || exit /b 6
)

echo [2/4] Checking V42-owned changes for whitespace errors...
git diff --cached --check -- ^
  src/krx_research/application/job_menu ^
  src/krx_research/infrastructure/job_menu ^
  src/krx_research/qt/job_menu ^
  scripts/run_krx_menu.py ^
  scripts/migrate_v42_legacy_jobs.py ^
  scripts/verify_v42_baseline_ready.py ^
  scripts/verify_v42_gui_git_static.py ^
  scripts/verify_v42_gui_unit.py ^
  KRX_Menu_Launcher/scripts/run_krx_menu.py ^
  KRX_Menu_Launcher/run_krx_menu.bat ^
  tools/git/CREATE_V42_BASELINE.cmd ^
  tools/git/VERIFY_V42_BASELINE.cmd ^
  tools/setup/LAUNCH_V42_KRX_MENU.cmd ^
  tools/setup/VERIFY_V42_GUI_INTEGRATION.cmd
if errorlevel 1 exit /b 7

echo [3/4] Creating commit...
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "V42: complete PySide6 GUI menu 2/5/7 PostgreSQL integration" || exit /b 8
) else (
  echo [INFO] No staged code changes. Existing HEAD will be tagged.
)

echo [4/4] Creating tag...
git rev-parse -q --verify "refs/tags/v42-db-menu-integration-complete" >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%H in ('git rev-list -n 1 "v42-db-menu-integration-complete"') do set "TAGHEAD=%%H"
  for /f "delims=" %%H in ('git rev-parse HEAD') do set "CURHEAD=%%H"
  if /i not "%TAGHEAD%"=="%CURHEAD%" (
    echo [ERROR] Existing tag points to a different commit. Refusing to move it automatically.
    exit /b 9
  )
  echo [INFO] Tag already exists at current HEAD.
) else (
  git tag -a "v42-db-menu-integration-complete" -m "V42 DB/Menu integration COMPLETE - 2026-10-05" || exit /b 9
)

echo.
echo [PASS] V42 local Git baseline created.
git --no-pager log -1 --oneline
git tag --points-at HEAD
echo.
echo Working tree status:
git status --short
exit /b 0
