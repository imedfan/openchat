@echo off
set "GO_EXE=C:\Program Files\Go\bin\go.exe"
"%GO_EXE%" version
cd /d "%~dp0server\go"
"%GO_EXE%" build -ldflags="-s -w" -o openchat-server.exe .
if exist openchat-server.exe (
    echo SUCCESS: Build completed!
) else (
    echo ERROR: Build failed.
)
