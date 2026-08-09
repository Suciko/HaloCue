@echo off
chcp 65001 >nul
title AA 自动写剧本
cd /d "%~dp0"

py -3 -c "import sys" >nul 2>&1
if errorlevel 1 goto :try_python
py -3 "%~dp0launcher.py"
set "AA_EXIT=%errorlevel%"
goto :finished

:try_python
python -c "import sys" >nul 2>&1
if errorlevel 1 goto :python_missing
python "%~dp0launcher.py"
set "AA_EXIT=%errorlevel%"
goto :finished

:python_missing
echo.
echo 无法启动：这台电脑没有找到 Python 3。
echo 请先安装 Python 3.9 或更高版本，安装时勾选“Add Python to PATH”。
echo.
set "AA_EXIT=1"

:finished
if "%AA_EXIT%"=="0" goto :done
echo.
echo 启动没有完成。请查看同目录的“启动失败日志.txt”，
echo 或双击总目录里的“检查运行环境.cmd”。
pause

:done
exit /b %AA_EXIT%
