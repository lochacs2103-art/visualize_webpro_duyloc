@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Excel Explorer
echo Dang mo Excel Explorer...

set "POLARS=%~dp0_internal\_polars_runtime_32"
if not exist "%~dp0_internal\python313.dll" (
    echo Thieu file trong thu muc _internal. Hay giai nen ZIP vao thu muc ngan, vi du C:\excel
    pause
    exit /b 1
)

if not exist "%POLARS%\_polars_runtime.pyd" (
    if not exist "%POLARS%\_polars_runtime.pyd.01" (
        echo Thieu file Polars.
        pause
        exit /b 1
    )
    echo Dang ghep Polars...
    copy /b /y "%POLARS%\_polars_runtime.pyd.01"+"%POLARS%\_polars_runtime.pyd.02"+"%POLARS%\_polars_runtime.pyd.03" "%POLARS%\_polars_runtime.pyd" >nul
    if not exist "%POLARS%\_polars_runtime.pyd" (
        echo Ghep Polars that bai.
        pause
        exit /b 1
    )
)

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
    start "" "http://127.0.0.1:8000"
    echo Web da mo san tai http://127.0.0.1:8000
    pause
    exit /b 0
)

reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Installed >nul 2>&1
if errorlevel 1 (
    if exist "%~dp0vc_redist.x64.exe" (
        echo Dang cai Visual C++ Runtime...
        "%~dp0vc_redist.x64.exe" /install /quiet /norestart
    )
)

echo Mo http://127.0.0.1:8000
excel-explorer.exe
echo.
echo Chuong trinh da tat. Ma loi: %errorlevel%
pause
