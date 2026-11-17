@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Excel Explorer
echo Dang mo Excel Explorer...
echo Bam run.bat nay. Dung bam truc tiep file excel-explorer.exe.

REM May khac khong can Python. File nay mo ban da dong goi.
set "APP=%~dp0excel-explorer\dist\excel-explorer"
set "EXCEL_EXPLORER_HOME=%~dp0excel-explorer"
set "POLARS=%APP%\_internal\_polars_runtime_32"

if not exist "%APP%\excel-explorer.exe" (
    echo.
    echo Khong thay file exe:
    echo %APP%\excel-explorer.exe
    echo Hay giai nen ca file ZIP, roi chay run.bat o thu muc goc.
    pause
    exit /b 1
)

if not exist "%APP%\_internal\python313.dll" (
    echo.
    echo Thieu file trong thu muc _internal.
    echo ZIP giai nen bi thieu vi duong dan qua dai.
    echo Hay giai nen vao thu muc ngan, vi du C:\excel
    pause
    exit /b 1
)

if not exist "%POLARS%\_polars_runtime.pyd" (
    if not exist "%POLARS%\_polars_runtime.pyd.01" (
        echo.
        echo Thieu file Polars. ZIP tai ve chua du.
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
    if exist "%APP%\vc_redist.x64.exe" (
        echo Dang cai Visual C++ Runtime...
        "%APP%\vc_redist.x64.exe" /install /quiet /norestart
    ) else (
        echo Chua co Visual C++ Runtime. Neu cua so bao thieu DLL, hay cai vc_redist.x64.exe trong thu muc exe.
    )
)

echo Mo http://127.0.0.1:8000
cd /d "%APP%"
excel-explorer.exe
echo.
echo Chuong trinh da tat. Ma loi: %errorlevel%
echo Doc dong chu o phia tren. Dong cua so nay sau khi chup lai loi.
pause
