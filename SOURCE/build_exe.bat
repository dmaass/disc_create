@echo off
REM Rebuild disc_create.exe from this source (needs Python + internet once).
python -m pip install pyinstaller || exit /b 1
python -m PyInstaller --onefile --windowed --name disc_create --clean ui.py || exit /b 1
echo.
echo Built: dist\disc_create.exe
pause
