@echo off
setlocal
cd /d "%~dp0"
python -X utf8 tools\install_spine_web_runtime.py
if errorlevel 1 goto :done
python -X utf8 -m playwright install chromium
:done
pause
