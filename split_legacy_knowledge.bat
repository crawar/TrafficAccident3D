@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ENV_PY=%~dp0env\python.exe"
set "PYTHONUTF8=1"

echo ========================================================
echo Split legacy accident_knowledge.json into:
echo   knowledge\playbook.json
echo   knowledge\index.json
echo   knowledge\packs\*.json
echo ========================================================
echo.

if not exist "%ENV_PY%" (
    echo [ERROR] Project env python not found:
    echo   %ENV_PY%
    echo Run create.bat first.
    pause
    exit /b 1
)

"%ENV_PY%" -c "from utils.knowledge_store import migrate_legacy_pack_if_needed; print(migrate_legacy_pack_if_needed())"
if errorlevel 1 (
    echo [ERROR] Migration failed.
    pause
    exit /b 1
)

echo.
echo Done. The original file is renamed to accident_knowledge.json.migrated if it existed.
pause
exit /b 0
