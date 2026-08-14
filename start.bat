@echo off
echo ========================================================
echo Traffic Accident 3D Scene Reconstruction - Launcher
echo ========================================================
echo.

echo [1/2] Checking environment...
if not exist "%~dp0env" (
    echo [ERROR] Conda environment not found. Please run create.bat first.
    pause
    exit /b 1
)
echo [SUCCESS] Environment is ready.
echo.

echo [2/2] Starting GUI, please wait...
echo --------------------------------------------------------
echo.

set "ENV_DIR=%~dp0env"
set "ENV_PYTHON=%~dp0env\python.exe"
"%ENV_PYTHON%" "%~dp0main.py"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Program exited with an error.
    pause
)
