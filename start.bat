@echo off
setlocal
cd /d "%~dp0"
title PTT Dcard Monitor
set PYTHONIOENCODING=utf-8

echo ================================================================
echo Starting PTT and Dcard Monitor Service...
echo ================================================================

set "PYTHON_EXEC=C:\Users\106111\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not exist "%PYTHON_EXEC%" (
    echo [WARNING] Python executable not found at specified path, falling back to python...
    set "PYTHON_EXEC=python"
)

"%PYTHON_EXEC%" main.py

echo.
echo ================================================================
echo Service stopped.
echo ================================================================
pause
