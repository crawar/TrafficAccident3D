@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PROJECT_DIR=%~dp0.."
set "ENV_PY=%PROJECT_DIR%\env\python.exe"
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn"
set "PYTHONUTF8=1"

echo ========================================================
echo Generate TrafficAccident3D briefing PPTX
echo python-pptx is installed into the project env only
echo ========================================================
echo.

if not exist "%ENV_PY%" (
    echo [ERROR] Project env python not found:
    echo   %ENV_PY%
    echo Run create.bat in the project root first.
    pause
    exit /b 1
)

echo [1/2] Installing python-pptx into project env...
"%ENV_PY%" -m pip install python-pptx -i "%PIP_INDEX%" --trusted-host "%PIP_TRUSTED_HOST%"
if errorlevel 1 (
    echo [ERROR] Failed to install python-pptx.
    pause
    exit /b 1
)
echo.

echo [2/2] Generating PPTX...
"%ENV_PY%" "%~dp0generate_ppt.py"
if errorlevel 1 (
    echo [ERROR] PPT generation failed.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo Done. Output:
echo   %~dp0TrafficAccident3D项目介绍.pptx
echo ========================================================
pause
exit /b 0
