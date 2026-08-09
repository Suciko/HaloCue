@echo off
chcp 65001 >nul
title AA 自动写剧本 - 环境检查
cd /d "%~dp0"

py -3 -c "import sys" >nul 2>&1
if errorlevel 1 goto :try_python
py -3 "%~dp0launcher.py" --check
goto :finished

:try_python
python -c "import sys" >nul 2>&1
if errorlevel 1 goto :python_missing
python "%~dp0launcher.py" --check
goto :finished

:python_missing
echo 无法检查：这台电脑没有找到 Python 3.9 或更高版本。

:finished
echo.
pause
