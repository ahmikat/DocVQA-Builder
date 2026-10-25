@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto setup_failed

set "APP_PY=.venv\Scripts\python.exe"
set "APP_PYW=.venv\Scripts\pythonw.exe"

if not exist "%APP_PY%" (
    where python >nul 2>&1
    if errorlevel 1 goto python_missing
    echo Creating the Python environment for Bangla DocVQA Builder...
    python -m venv .venv
    if errorlevel 1 goto setup_failed
)

"%APP_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto python_too_old

"%APP_PY%" -c "import PySide6.QtWidgets, fitz, PIL, openpyxl, google.genai, keyring; from zoneinfo import ZoneInfo; ZoneInfo('America/Los_Angeles')" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages. This may take a few minutes on the first run...
    "%APP_PY%" -m pip install -e .
    if errorlevel 1 goto setup_failed
)

start "" /D "%CD%" "%APP_PYW%" -m bndocvqa
if errorlevel 1 goto launch_failed
exit /b 0

:python_missing
echo Python 3.11 or newer was not found. Install Python, then double-click this file again.
goto show_error

:python_too_old
echo This app needs Python 3.11 or newer. The .venv folder uses an older Python.
goto show_error

:setup_failed
echo Setup failed. Check the error above, then try again.
goto show_error

:launch_failed
echo The app could not be launched. To see the error, run:
echo   .venv\Scripts\python.exe -m bndocvqa

:show_error
pause
exit /b 1
