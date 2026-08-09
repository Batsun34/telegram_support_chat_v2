@echo off
setlocal

cd /d "%~dp0"

if not exist ".env" (
    echo ERROR: .env file not found.
    echo Create .env from .env.example and set BOT_TOKEN.
    pause
    exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_LAUNCHER=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python 3.11+ is not installed or not found in PATH.
        pause
        exit /b 1
    )
    set "PYTHON_LAUNCHER=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON_LAUNCHER% -m venv .venv
    if errorlevel 1 goto fail
)

echo Installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 goto fail

echo Applying database migrations...
".venv\Scripts\alembic.exe" upgrade head
if errorlevel 1 goto fail

echo Starting bot...
".venv\Scripts\python.exe" -m app.main
if errorlevel 1 goto fail

exit /b 0

:fail
echo.
echo Bot startup failed. See the error above.
pause
exit /b 1
