@echo off
rem Builds "dist\Docket Ledger\DocketLedger.exe".
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name DocketLedger --icon assets\docket-ledger.ico ^
  --add-data "assets;assets" --collect-all pypdfium2 --collect-all pypdfium2_raw run.py
if errorlevel 1 exit /b 1
if exist "dist\Docket Ledger" rmdir /s /q "dist\Docket Ledger"
ren "dist\DocketLedger" "Docket Ledger"
echo.
echo Done. Run "dist\Docket Ledger\DocketLedger.exe"
