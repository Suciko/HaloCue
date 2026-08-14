@echo off
setlocal
cd /d "%~dp0"
if "%OPENAI_API_KEY%"=="" (
  echo 请先在当前 PowerShell 中设置 OPENAI_API_KEY，再运行本脚本。
  echo 密钥只从环境变量读取，不会写入项目文件。
  pause
  exit /b 2
)
python -X utf8 batch_label_spine_faces.py run --force-vision
pause
