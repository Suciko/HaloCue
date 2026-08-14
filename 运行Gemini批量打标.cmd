@echo off
setlocal
cd /d "%~dp0"

if "%OPENAI_API_KEY%"=="" (
  echo Missing OPENAI_API_KEY.
  echo In PowerShell, run: $env:OPENAI_API_KEY = "your Gemini gateway key"
  pause
  exit /b 2
)

echo [1/2] Labeling Spine expressions in stable four-face comparison batches...
python -X utf8 batch_label_spine_faces.py run --model gemini-3.7-flash --batch-size 4 --api-workers 2
if errorlevel 1 goto :failed

echo [2/2] Labeling unreviewed backgrounds with image and filename context...
python -X utf8 label_assets.py --model gemini-3.7-flash --bg --batch 8 --px 960
if errorlevel 1 goto :failed

echo.
echo Completed. Reports are saved under out\spine-face-batch\report.json.
pause
exit /b 0

:failed
echo.
echo Batch stopped. Completed character and background labels are already saved.
echo Rerun this file to resume.
pause
exit /b 1
