@echo off

REM Build OpenChat Server
REM Based on AGENTS.md structure

REM Get current directory
set SCRIPT_DIR=%~dp0

REM Go to server directory
cd /d "%SCRIPT_DIR%server\go"

echo Building OpenChat Server from server/go/...

REM Build with all dependencies
if exist go.mod (
    go build -ldflags="-s -w" -o openchat-server.exe
    if errorlevel 1 (
        echo ERROR: Build failed!
        cd /d "%SCRIPT_DIR%"
        pause
        exit /b 1
    )
) else (
    echo ERROR: go.mod not found in server/go/!
    cd /d "%SCRIPT_DIR%"
    pause
    exit /b 1
)

REM Return to original directory
cd /d "%SCRIPT_DIR%"

REM Create builds directory with current date
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "DATE_DIR=%dt:~0,4%-%dt:~4,2%-%dt:~6,2%"
set "BUILD_DIR=builds\%DATE_DIR%"

mkdir "%BUILD_DIR%" 2>nul

REM Copy executable and models.json to builds/YYYY-MM-DD/
echo Copying files to %BUILD_DIR%...
copy /Y "server\go\openchat-server.exe" "%BUILD_DIR%\" >nul
copy /Y "server\go\models.json" "%BUILD_DIR%\" >nul 2>nul

REM Check if copy was successful
echo.
echo Build complete! Files in %BUILD_DIR%:
dir "%BUILD_DIR%" /b

REM Open the directory
explorer "%BUILD_DIR%"
