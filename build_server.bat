@echo off
echo Building OpenChat Server...
cd /d "%~dp0"

REM Build with all dependencies
go build -ldflags="-s -w" -o server.exe main.go

if exist server.exe (
    echo SUCCESS: server.exe built!
    
    echo.
    echo Moving distributable files to distr/go/...
    mkdir distr\go 2>nul
    
    REM Copy executable and models.json
    copy /Y server.exe "distr\go\" >nul
    if exist models.json (
        copy /Y models.json "distr\go\" >nul
        echo Copied: models.json
    ) else (
        echo Warning: models.json not found, skipping...
    )
    
    REM Copy README if exists
    if exist server.exe-copy (
        copy /Y server.exe-copy "distr\go\" >nul
        echo Copied: server.exe-copy (fallback)
    )
    
    echo.
    echo Build complete! Files in distr/go/:
    dir distr\go /b
    
) else (
    echo ERROR: Build failed! Check errors above.
    pause
)
