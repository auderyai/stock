@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."
where git >nul 2>nul || (
  echo [FAIL] git.exe not found.
  exit /b 2
)
git rev-parse --is-inside-work-tree >nul 2>nul || (
  echo [FAIL] Not a Git work tree.
  exit /b 3
)
git rev-parse -q --verify "refs/tags/v42-db-menu-integration-complete" >nul 2>nul || (
  echo [FAIL] V42 baseline tag not found.
  exit /b 4
)
for /f "delims=" %%T in ('git rev-list -n 1 "v42-db-menu-integration-complete"') do set "TAGHEAD=%%T"
for /f "delims=" %%H in ('git rev-parse HEAD') do set "CURHEAD=%%H"
if /i not "%TAGHEAD%"=="%CURHEAD%" (
  echo [FAIL] V42 tag exists but does not point at current HEAD.
  echo Tag : %TAGHEAD%
  echo HEAD: %CURHEAD%
  exit /b 5
)
echo [PASS] V42 baseline tag exists at current HEAD.
git --no-pager log -1 --oneline
git tag --points-at HEAD
git status --short
exit /b 0
