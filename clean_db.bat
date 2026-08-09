@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   Telegram Support Bot - DATABASE RESET
echo ==========================================
echo.
echo WARNING: This will permanently delete all bot data.
echo Stop the bot before continuing.
echo.

if not exist ".env" (
    echo [ERROR] .env not found.
    echo Put this file in the project root next to .env and alembic.ini.
    echo.
    pause
    exit /b 1
)

if not exist "alembic.ini" (
    echo [ERROR] alembic.ini not found.
    echo Put this file in the project root.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\alembic.exe" (
    echo [ERROR] .venv\Scripts\alembic.exe not found.
    echo Create the virtual environment first:
    echo   powershell -ExecutionPolicy Bypass -File .\scripts\setup_venv.ps1
    echo.
    pause
    exit /b 1
)

set "DATABASE_URL="
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /I "%%A"=="DATABASE_URL" set "DATABASE_URL=%%B"
)

if not defined DATABASE_URL (
    set "DATABASE_URL=sqlite+aiosqlite:///./support_chat.db"
    echo [INFO] DATABASE_URL is not set in .env.
    echo [INFO] Using default: !DATABASE_URL!
)

for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
    "$u=$env:DATABASE_URL; " ^
    "if (-not $u.StartsWith('sqlite+aiosqlite:///')) { exit 2 }; " ^
    "$p=$u.Substring('sqlite+aiosqlite:///'.Length); " ^
    "if ($p.StartsWith('./')) { $p=$p.Substring(2) }; " ^
    "$p=$p -replace '/', [IO.Path]::DirectorySeparatorChar; " ^
    "[IO.Path]::GetFullPath((Join-Path (Get-Location) $p))"`) do (
    set "DB_FILE=%%P"
)

if not defined DB_FILE (
    echo [ERROR] Could not parse SQLite DATABASE_URL:
    echo   !DATABASE_URL!
    echo.
    echo Expected format, for example:
    echo   sqlite+aiosqlite:///./support_chat.db
    echo.
    pause
    exit /b 1
)

echo Database:
echo   !DB_FILE!
echo.
echo Type DELETE to erase ALL users, messages, moderator state and bans.
set /p "CONFIRM=> "

if /I not "!CONFIRM!"=="DELETE" (
    echo.
    echo Cancelled. Nothing was changed.
    pause
    exit /b 0
)

echo.
echo [1/3] Removing SQLite files...

if exist "!DB_FILE!" (
    del /f /q "!DB_FILE!" || goto :delete_error
)

if exist "!DB_FILE!-wal" (
    del /f /q "!DB_FILE!-wal" || goto :delete_error
)

if exist "!DB_FILE!-shm" (
    del /f /q "!DB_FILE!-shm" || goto :delete_error
)

echo [2/3] Recreating empty database schema...
".venv\Scripts\alembic.exe" upgrade head
if errorlevel 1 goto :alembic_error

echo [3/3] Done.
echo.
echo Database was cleared and recreated successfully.
echo You can start the bot now:
echo   .\scripts\run.ps1
echo.
pause
exit /b 0

:delete_error
echo.
echo [ERROR] Could not delete the database.
echo Make sure the bot is fully stopped and no program has the DB open.
echo Nothing else will be changed.
echo.
pause
exit /b 1

:alembic_error
echo.
echo [ERROR] Database files were removed, but Alembic failed to recreate the schema.
echo Fix the error above, then run:
echo   .\.venv\Scripts\alembic.exe upgrade head
echo.
pause
exit /b 1
