@echo off
cd /d "%~dp0"
call venv\Scripts\activate
python -m pip install pyinstaller
pyinstaller --noconfirm excel-explorer.spec
if exist dist-ship\run.bat copy /Y dist-ship\run.bat dist\excel-explorer\run.bat
if exist vc_redist.x64.exe copy /Y vc_redist.x64.exe dist\excel-explorer\vc_redist.x64.exe
if exist dist-ship\README.txt copy /Y dist-ship\README.txt dist\excel-explorer\README.txt
echo Build xong: dist\excel-explorer\excel-explorer.exe
