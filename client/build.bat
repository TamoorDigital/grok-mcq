@echo off
REM ============================================================
REM  GrokMCQ - Build EXE script
REM  Run this on Windows to produce dist\client.exe
REM ============================================================

echo [1/4] Installing dependencies...
pip install -r requirements.txt

echo [2/4] Building EXE with PyInstaller...
pyinstaller ^
  --onefile ^
  --windowed ^
  --name GrokMCQ ^
  --add-data "icon.ico;." ^
  client.py

echo [3/4] Done! EXE is at: dist\GrokMCQ.exe
echo [4/4] Distribute dist\GrokMCQ.exe to users.
pause
