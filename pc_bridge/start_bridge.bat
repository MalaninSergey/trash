@echo off
REM Start PC bridge to JupyterHub (Windows)
cd /d "%~dp0"
python jupyter_pc_bridge.py %*
if errorlevel 1 (
  echo.
  echo If python not found, try: py jupyter_pc_bridge.py
  pause
)
