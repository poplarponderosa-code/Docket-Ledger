@echo off
setlocal
cd /d "%~dp0"
echo.
echo  Making the Docket Ledger installer. Close Docket Ledger first if it's running.
echo.

echo [1/3] Building DocketLedger.exe ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :fail
python -m PyInstaller --noconfirm --clean --windowed --name DocketLedger --icon assets\docket-ledger.ico --add-data "assets;assets" --collect-all pypdfium2 --collect-all pypdfium2_raw run.py || goto :fail
if exist "dist\Docket Ledger" rmdir /s /q "dist\Docket Ledger"
ren "dist\DocketLedger" "Docket Ledger" || goto :fail

echo [2/3] Finding Inno Setup ...
call :find_iscc
if not defined ISCC (
    echo Inno Setup isn't installed yet. Installing it with winget, this happens once ...
    winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
    call :find_iscc
)
if not defined ISCC (
    echo.
    echo Couldn't find Inno Setup. Install it from https://jrsoftware.org/isinfo.php
    echo then run this file again.
    goto :fail
)

echo [3/3] Making the installer ...
"%ISCC%" installer.iss || goto :fail
echo.
echo Done. The installer is in the installer_output folder.
explorer installer_output
pause
exit /b 0

:find_iscc
set "ISCC="
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
exit /b 0

:fail
echo.
echo Something went wrong; see the messages above.
pause
exit /b 1
