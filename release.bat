@echo off
REM Release package: rebuild the exe, refresh the docs, zip it all.
REM Result: BINARY\disc_create_yyyyMMdd.zip (exe + README + CHANGELOG + LICENSE).
setlocal

REM --- date stamps (locale-independent) ------------------------------------
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set STAMP=%%i
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format dd.MM.yyyy"') do set DEDATE=%%i
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set ENDATE=%%i
if "%STAMP%"=="" ( echo Cannot determine date. & exit /b 1 )
echo Release stamp: %STAMP%

REM --- build the exe --------------------------------------------------------
cd SOURCE || exit /b 1
python -m pip install pyinstaller || exit /b 1
python -m PyInstaller --onefile --windowed --name disc_create --clean ui.py || exit /b 1
copy /y dist\disc_create.exe ..\BINARY\disc_create.exe || exit /b 1
rmdir /s /q build dist
del /q *.spec
cd ..

REM --- refresh build date in BINARY README ----------------------------------
powershell -NoProfile -Command "(Get-Content BINARY\README.md) -replace '(Gebaut am )\d\d\.\d\d\.\d\d\d\d', ('${1}' + '%DEDATE%') -replace '(Built )\d\d\d\d-\d\d-\d\d', ('${1}' + '%ENDATE%') | Set-Content BINARY\README.md" || exit /b 1

REM --- stage + zip ----------------------------------------------------------
set STAGE=release_stage
if exist %STAGE% rmdir /s /q %STAGE%
mkdir %STAGE%
copy /y BINARY\disc_create.exe %STAGE%\ || exit /b 1
copy /y README.md %STAGE%\ || exit /b 1
copy /y CHANGELOG.md %STAGE%\ || exit /b 1
copy /y LICENSE %STAGE%\ || exit /b 1
set ZIP=BINARY\disc_create_%STAMP%.zip
if exist %ZIP% del /q %ZIP%
powershell -NoProfile -Command "Compress-Archive -Path %STAGE%\* -DestinationPath %ZIP%" || exit /b 1
rmdir /s /q %STAGE%

echo.
echo Release ready: %ZIP%
pause
