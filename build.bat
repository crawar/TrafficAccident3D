@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "APP_NAME=TrafficAccident3D"
set "PROJECT_DIR=%~dp0"
set "ENV_DIR=%PROJECT_DIR%env"
set "BUILD_DIR=%PROJECT_DIR%build"
set "DIST_DIR=%PROJECT_DIR%dist"
set "RELEASE_DIR=%PROJECT_DIR%release"
set "APP_OUT=%RELEASE_DIR%\%APP_NAME%"
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn"
set "PYTHONUTF8=1"
set "MPLBACKEND=Agg"

echo ========================================================
echo Traffic Accident 3D Scene Reconstruction - Build
echo ========================================================
echo.

cd /d "%PROJECT_DIR%"

echo [1/9] Checking Conda...
where conda >nul 2>nul
if errorlevel 1 (
    echo [ERROR] conda command not found. Please install Anaconda or Miniconda first.
    goto :fail
)
echo [OK] Conda is available.
echo.

echo [2/9] Checking local project environment...
if not exist "%ENV_DIR%" (
    echo [INFO] Local environment not found. Creating it inside this project...
    call conda create -p "%ENV_DIR%" python=3.10 -y --override-channels -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
    if errorlevel 1 (
        echo [ERROR] Failed to create local Conda environment.
        goto :fail
    )
) else (
    echo [OK] Local environment already exists.
)
echo.

echo [3/9] Activating local environment...
call conda activate "%ENV_DIR%"
if errorlevel 1 (
    echo [ERROR] Failed to activate local Conda environment.
    goto :fail
)
echo [OK] Environment activated.
echo.

echo [4/9] Installing build and runtime dependencies...
python -m pip install --upgrade pip -i "%PIP_INDEX%" --trusted-host "%PIP_TRUSTED_HOST%"
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    goto :fail
)

python -m pip install -r "%PROJECT_DIR%requirements.txt" -i "%PIP_INDEX%" --trusted-host "%PIP_TRUSTED_HOST%"
if errorlevel 1 (
    echo [ERROR] Failed to install runtime dependencies.
    goto :fail
)

python -m pip install pyinstaller -i "%PIP_INDEX%" --trusted-host "%PIP_TRUSTED_HOST%"
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    goto :fail
)
echo [OK] Dependencies are ready.
echo.

echo [5/9] Checking required project files...
if not exist "%PROJECT_DIR%main.py" (
    echo [ERROR] main.py not found.
    goto :fail
)
if not exist "%PROJECT_DIR%templates\accident_scene.html" (
    echo [ERROR] templates\accident_scene.html not found.
    goto :fail
)
if not exist "%PROJECT_DIR%templates\vehicle_model_preview.html" (
    echo [ERROR] templates\vehicle_model_preview.html not found.
    goto :fail
)
if not exist "%PROJECT_DIR%downloads" (
    echo [ERROR] downloads folder not found.
    goto :fail
)
set "MODEL_COUNT=0"
for %%F in ("%PROJECT_DIR%downloads\*.pt") do (
    if exist "%%~fF" set /a MODEL_COUNT+=1
)
if !MODEL_COUNT! LSS 2 (
    echo [ERROR] Expected at least 2 YOLO model files in downloads, but found !MODEL_COUNT!.
    goto :fail
)
if not exist "%PROJECT_DIR%glbmodels" (
    echo [ERROR] glbmodels folder not found.
    goto :fail
)
set "GLB_COUNT=0"
for %%F in ("%PROJECT_DIR%glbmodels\*.glb") do (
    if exist "%%~fF" set /a GLB_COUNT+=1
)
if !GLB_COUNT! LSS 8 (
    echo [ERROR] Expected at least 8 GLB vehicle models in glbmodels, but found !GLB_COUNT!.
    goto :fail
)
if not exist "%PROJECT_DIR%static\three\three.min.js" (
    echo [ERROR] static\three\three.min.js not found.
    goto :fail
)
if not exist "%PROJECT_DIR%static\three\OrbitControls.js" (
    echo [ERROR] static\three\OrbitControls.js not found.
    goto :fail
)
if not exist "%PROJECT_DIR%static\three\GLTFLoader.js" (
    echo [ERROR] static\three\GLTFLoader.js not found.
    goto :fail
)
if not exist "%PROJECT_DIR%ExpertPic" (
    echo [ERROR] ExpertPic folder not found.
    goto :fail
)
if not exist "%PROJECT_DIR%config" (
    echo [ERROR] config folder not found.
    goto :fail
)
if not exist "%PROJECT_DIR%config\ai_experts.json" (
    echo [WARN] config\ai_experts.json not found. Defaults will be created at first run.
)
if not exist "%PROJECT_DIR%Example1.jpeg" (
    echo [WARN] Example1.jpeg not found. The example dialog will miss the left image.
)
if not exist "%PROJECT_DIR%Example2.png" (
    echo [WARN] Example2.png not found. The example dialog will miss the right image.
)
echo [OK] Required files checked.
echo.

echo [6/9] Cleaning old build output...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%APP_OUT%" rmdir /s /q "%APP_OUT%"
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
echo [OK] Old output cleaned.
echo.

echo [7/9] Building executable with PyInstaller...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%BUILD_DIR%" ^
    --specpath "%BUILD_DIR%" ^
    --collect-all PySide6 ^
    --collect-all shiboken6 ^
    --collect-all ultralytics ^
    --collect-all cv2 ^
    --collect-all numpy ^
    --collect-all PIL ^
    --collect-all torch ^
    --collect-all torchvision ^
    --hidden-import PySide6.QtWebEngineCore ^
    --hidden-import PySide6.QtWebEngineWidgets ^
    --hidden-import matplotlib.backends.backend_qtagg ^
    "%PROJECT_DIR%main.py"
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    goto :fail
)
echo [OK] Executable built.
echo.

echo [8/9] Copying runtime resources to release folder...
if exist "%APP_OUT%" rmdir /s /q "%APP_OUT%"
xcopy /E /I /Y "%DIST_DIR%\%APP_NAME%" "%APP_OUT%" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy PyInstaller output.
    goto :fail
)

call :copy_dir "%PROJECT_DIR%templates" "%APP_OUT%\templates" "templates"
if errorlevel 1 goto :fail
call :copy_dir "%PROJECT_DIR%downloads" "%APP_OUT%\downloads" "downloads"
if errorlevel 1 goto :fail
call :copy_dir "%PROJECT_DIR%glbmodels" "%APP_OUT%\glbmodels" "glbmodels"
if errorlevel 1 goto :fail
call :copy_dir "%PROJECT_DIR%static" "%APP_OUT%\static" "static"
if errorlevel 1 goto :fail
call :copy_dir "%PROJECT_DIR%ExpertPic" "%APP_OUT%\ExpertPic" "ExpertPic"
if errorlevel 1 goto :fail

REM Copy config except ai_settings.json, then write a sanitized copy with empty API key.
if not exist "%APP_OUT%\config" mkdir "%APP_OUT%\config"
robocopy "%PROJECT_DIR%config" "%APP_OUT%\config" /E /XF ai_settings.json >nul
if errorlevel 8 (
    echo [ERROR] Failed to copy config.
    goto :fail
)
if not exist "%PROJECT_DIR%pack_sanitize_ai_settings.py" (
    echo [ERROR] pack_sanitize_ai_settings.py not found.
    goto :fail
)
python "%PROJECT_DIR%pack_sanitize_ai_settings.py" "%PROJECT_DIR%config\ai_settings.json" "%APP_OUT%\config\ai_settings.json"
if errorlevel 1 (
    echo [ERROR] Failed to write sanitized ai_settings.json.
    goto :fail
)
echo [OK] config copied ^(API key stripped^).

if not exist "%APP_OUT%\history" mkdir "%APP_OUT%\history"
if not exist "%APP_OUT%\history\json" mkdir "%APP_OUT%\history\json"
echo [OK] history folders created.

if exist "%PROJECT_DIR%pic" (
    call :copy_dir "%PROJECT_DIR%pic" "%APP_OUT%\pic" "pic"
    if errorlevel 1 goto :fail
)
if exist "%PROJECT_DIR%Example1.jpeg" copy /Y "%PROJECT_DIR%Example1.jpeg" "%APP_OUT%\Example1.jpeg" >nul
if exist "%PROJECT_DIR%Example2.png" copy /Y "%PROJECT_DIR%Example2.png" "%APP_OUT%\Example2.png" >nul
echo [OK] Runtime resources copied.
echo.

echo [9/9] Verifying release package...
set "VERIFY_FAIL=0"
if not exist "%APP_OUT%\%APP_NAME%.exe" (
    echo [ERROR] Missing %APP_NAME%.exe
    set "VERIFY_FAIL=1"
)
if not exist "%APP_OUT%\templates\accident_scene.html" (
    echo [ERROR] Missing templates\accident_scene.html
    set "VERIFY_FAIL=1"
)
if not exist "%APP_OUT%\templates\vehicle_model_preview.html" (
    echo [ERROR] Missing templates\vehicle_model_preview.html
    set "VERIFY_FAIL=1"
)
if not exist "%APP_OUT%\glbmodels\01_sedan.glb" (
    echo [ERROR] Missing glbmodels\01_sedan.glb
    set "VERIFY_FAIL=1"
)
if not exist "%APP_OUT%\static\three\three.min.js" (
    echo [ERROR] Missing static\three\three.min.js
    set "VERIFY_FAIL=1"
)
if not exist "%APP_OUT%\ExpertPic\default_unknown.png" (
    echo [ERROR] Missing ExpertPic\default_unknown.png
    set "VERIFY_FAIL=1"
)
if not exist "%APP_OUT%\config\ai_settings.json" (
    echo [ERROR] Missing config\ai_settings.json
    set "VERIFY_FAIL=1"
)
if not exist "%APP_OUT%\history" (
    echo [ERROR] Missing history folder
    set "VERIFY_FAIL=1"
)
if not exist "%APP_OUT%\downloads" (
    echo [ERROR] Missing downloads folder
    set "VERIFY_FAIL=1"
)
if not exist "%PROJECT_DIR%pack_verify_release.py" (
    echo [ERROR] pack_verify_release.py not found.
    set "VERIFY_FAIL=1"
) else (
    python "%PROJECT_DIR%pack_verify_release.py" "%PROJECT_DIR%." "%APP_OUT%"
    if errorlevel 1 (
        echo [ERROR] Release content verification failed.
        set "VERIFY_FAIL=1"
    )
)
if "!VERIFY_FAIL!"=="1" (
    echo [ERROR] Release package verification failed.
    goto :fail
)
echo [OK] Release package verified.
echo.
echo ========================================================
echo Build completed successfully.
echo Output folder:
echo %APP_OUT%
echo.
echo Packaged resources:
echo   - templates / static / glbmodels / downloads
echo   - ExpertPic / config ^(API key cleared^)
echo   - history ^(empty^) / Example images / pic^(if present^)
echo.
echo Double-click this file to run the packed app:
echo %APP_OUT%\%APP_NAME%.exe
echo ========================================================
if /I not "%BUILD_NOPAUSE%"=="1" pause
exit /b 0

:copy_dir
set "SRC_DIR=%~1"
set "DST_DIR=%~2"
set "LABEL=%~3"
if not exist "%SRC_DIR%" (
    echo [ERROR] Source folder not found: %LABEL%
    exit /b 1
)
xcopy /E /I /Y "%SRC_DIR%" "%DST_DIR%" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy %LABEL%.
    exit /b 1
)
echo [OK] %LABEL% copied.
exit /b 0

:fail
echo.
echo ========================================================
echo Build FAILED. See errors above.
echo ========================================================
if /I not "%BUILD_NOPAUSE%"=="1" pause
exit /b 1
