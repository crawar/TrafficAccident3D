@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if exist "%ProgramFiles%\GitHub CLI\gh.exe" set "PATH=%ProgramFiles%\GitHub CLI;%PATH%"
if exist "D:\Git\cmd\git.exe" set "PATH=D:\Git\cmd;%PATH%"

echo ========================================================
echo Publish TrafficAccident3D to GitHub (public)
echo This script will NOT upload config\ai_settings.json
echo ========================================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo [ERROR] git is not installed.
    pause
    exit /b 1
)

where gh >nul 2>nul
if errorlevel 1 (
    echo [ERROR] GitHub CLI (gh) is not installed.
    pause
    exit /b 1
)

echo [1/5] Checking GitHub login...
gh auth status >nul 2>nul
if errorlevel 1 (
    echo A browser window will open. Please log in to GitHub.
    gh auth login --web --git-protocol https --hostname github.com
    if errorlevel 1 (
        echo [ERROR] GitHub login failed.
        pause
        exit /b 1
    )
)
echo [OK] GitHub CLI is logged in.
echo.

echo [2/5] Reading GitHub username...
for /f "usebackq delims=" %%U in (`gh api user --jq .login`) do set "GH_USER=%%U"
if not defined GH_USER (
    echo [ERROR] Failed to read GitHub username.
    pause
    exit /b 1
)
echo [OK] GitHub user: %GH_USER%
echo.

echo [3/5] Safety check: API key file must stay local...
git check-ignore -q "config\ai_settings.json"
if errorlevel 1 (
    echo [ERROR] config\ai_settings.json is NOT ignored. Aborting to protect the API key.
    pause
    exit /b 1
)
git diff --cached --name-only | findstr /I /C:"config/ai_settings.json" >nul
if not errorlevel 1 (
    echo [ERROR] config\ai_settings.json is staged. Aborting.
    pause
    exit /b 1
)
echo [OK] API key file is ignored and not staged.
echo.

echo [4/5] Creating initial commit...
git add -A
git -c "user.name=%GH_USER%" -c "user.email=%GH_USER%@users.noreply.github.com" commit -m "Initial public release of TrafficAccident3D."
if errorlevel 1 (
    echo [INFO] Commit step reported an error. If the commit already exists, push will continue.
)
echo.

echo [5/5] Creating public repo %GH_USER%/TrafficAccident3D and pushing...
gh repo create TrafficAccident3D --public --source=. --remote=origin --push --description "Traffic accident 3D scene reconstruction"
if errorlevel 1 (
    echo [ERROR] Failed to create or push the GitHub repository.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo Done.
echo Repository:
gh repo view --web --json url --jq .url
echo.
echo Local secret kept out of GitHub:
echo   config\ai_settings.json
echo YOLO weights were not uploaded (GitHub 100MB limit).
echo ========================================================
pause
exit /b 0
