@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    echo Virtual environment not found at .venv\Scripts\python.exe
    echo Create it first with: py -3.11 -m venv .venv
    exit /b 1
)

if "%*"=="" (
    echo No arguments passed. Launching demo mode for a safe startup.
    "%PYTHON_EXE%" -m homelab_ai --demo
) else (
    "%PYTHON_EXE%" -m homelab_ai %*
)

exit /b %ERRORLEVEL%
