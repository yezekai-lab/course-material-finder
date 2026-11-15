@echo off
setlocal enableextensions
cd /d "%~dp0"
title Course Material Finder

echo.
echo   Course Material Finder
echo   ------------------------------------
echo.

rem ---- locate Python (prefer the one on PATH) -------------------------------
set "PY="
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  echo   [x] Python not found. Install Python 3.10+ and tick "Add Python to PATH".
  echo       https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)
echo   [1/3] python: %PY%

rem ---- dependency: requests -------------------------------------------------
%PY% -c "import requests" >nul 2>nul
if errorlevel 1 (
  echo   [2/3] installing requests ...
  %PY% -m pip install --disable-pip-version-check -q requests
  if errorlevel 1 (
    echo   [x] pip install failed. Run manually: %PY% -m pip install requests
    echo.
    pause
    exit /b 1
  )
) else (
  echo   [2/3] requests ok
)

rem ---- launch (with args: no browser, easier to script) ---------------------
set "OPEN="
if "%~1"=="" set "OPEN=--open"
echo   [3/3] starting local server ...
echo.
%PY% serve.py --port auto %OPEN% %*
echo.
echo   server stopped.
pause
