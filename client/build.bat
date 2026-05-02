@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  GrokMCQ - Build EXE script (Python 3.11 FIXED)
REM ============================================================

echo ===============================
echo [0/5] Setting up environment...
echo ===============================

REM Check Python 3.11
py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11 is not installed.
    echo Please install Python 3.11 and try again.
    pause
    exit /b
)

REM Create virtual environment if not exists
if not exist venv (
    echo Creating virtual environment with Python 3.11...
    py -3.11 -m venv venv
    if errorlevel 1 goto error
)

REM Activate venv
call venv\Scripts\activate
if errorlevel 1 goto error

echo ===============================
echo [1/5] Upgrading pip...
echo ===============================
python -m pip install --upgrade pip
if errorlevel 1 goto error

echo ===============================
echo [2/5] Installing dependencies...
echo ===============================

REM Ensure clean Pillow install (compatible)
pip uninstall pillow -y >nul 2>&1
pip install "pillow>=10,<11"
if errorlevel 1 goto error

REM Install required libraries
pip install keyboard==0.13.5
if errorlevel 1 goto error

pip install pyautogui==0.9.54
if errorlevel 1 goto error

pip install requests==2.32.3
if errorlevel 1 goto error

REM Install PyInstaller
pip install pyinstaller==6.10.0
if errorlevel 1 goto error

REM Install remaining requirements if file exists
if exist requirements.txt (
    pip install -r requirements.txt
    if errorlevel 1 goto error
) else (
    echo WARNING: requirements.txt not found, skipping...
)

echo ===============================
echo [3/5] Cleaning old builds...
echo ===============================
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist GrokMCQ.spec del GrokMCQ.spec

echo ===============================
echo [4/5] Building EXE...
echo ===============================
pyinstaller ^
  --onefile ^
  --windowed ^
  --name GrokMCQ ^
  client.py

if errorlevel 1 goto error

echo ===============================
echo [5/5] Build Complete!
echo EXE location: dist\GrokMCQ.exe
echo ===============================
goto end

:error
echo.
echo ❌ BUILD FAILED - Fix errors above.
echo.
pause
exit /b 1

:end
echo.
echo ✅ EXE is ready: dist\GrokMCQ.exe
echo You can share this file with others (no Python needed).
echo.
pause