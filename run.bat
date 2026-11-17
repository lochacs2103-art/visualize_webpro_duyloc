@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Excel Explorer

REM May khac khong can Python. File nay mo ban da dong goi.
set "APP=%~dp0excel-explorer\dist\excel-explorer"
set "EXCEL_EXPLORER_HOME=%~dp0excel-explorer"

if not exist "%APP%\excel-explorer.exe" (
    echo Khong thay ban dong goi:
    echo %APP%\excel-explorer.exe
    echo Hay copy ca thu muc, khong chi copy moi file run.bat.
    pause
    exit /b 1
)

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
    start "" "http://127.0.0.1:8000"
    exit /b 0
)

reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Installed >nul 2>&1
if errorlevel 1 (
    if exist "%APP%\vc_redist.x64.exe" (
        echo Dang cai Visual C++ Runtime...
        "%APP%\vc_redist.x64.exe" /install /quiet /norestart
    ) else (
        echo Chua co Visual C++ Runtime. App van mo, mot so file lon co the cham hon.
    )
)

start "Excel Explorer" "%APP%\excel-explorer.exe"
