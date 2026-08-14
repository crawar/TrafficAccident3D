@echo off
echo ========================================================
echo Traffic Accident 3D Scene Reconstruction - Initialization
echo ========================================================
echo.

echo [1/4] Checking Conda installation...
where conda >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] conda command not found. Please install Anaconda or Miniconda.
    pause
    exit /b 1
)
echo [SUCCESS] Conda is available.
echo.

echo [2/4] Checking local project environment...
if exist "%~dp0env" (
    echo [INFO] Local environment already exists. Skipping creation.
) else (
    echo [INFO] Local environment not found. Creating a new Conda environment...
    echo [INFO] This may take a while, please be patient.
    call conda create -p "%~dp0env" python=3.10 -y
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create Conda environment.
        pause
        exit /b 1
    )
)
echo.

echo [3/4] Activating local environment...
call conda activate "%~dp0env"
echo [SUCCESS] Environment activated.
echo.

echo [4/4] Installing dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install dependencies. Check network or requirements.txt.
    pause
    exit /b 1
)
echo.

echo ========================================================
echo Environment initialization complete! 
echo You can now double-click start.bat to launch the program.
echo ========================================================
pause
