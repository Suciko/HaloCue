@echo off
setlocal
chcp 65001 >nul
title HaloCue - Source Review
cd /d "%~dp0"
for %%V in (3.13 3.12 3.11) do (
  py -%%V -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    py -%%V -X utf8 "%~dp0tools\review_start.py" --setup %*
    goto :finished
  )
)
python -X utf8 "%~dp0tools\review_start.py" --setup %*
:finished
set "REVIEW_EXIT=%ERRORLEVEL%"
if "%REVIEW_EXIT%"=="130" exit /b 0
if not "%REVIEW_EXIT%"=="0" (
  echo.
  echo Start failed. Read START_REVIEW.md and .review-data\startup-error.log.
  pause
)
endlocal & exit /b %REVIEW_EXIT%
