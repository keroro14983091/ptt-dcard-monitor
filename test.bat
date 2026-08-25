@echo off
setlocal
cd /d "%~dp0"
title System Test
set PYTHONIOENCODING=utf-8

set "PYTHON_EXEC=C:\Users\106111\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not exist "%PYTHON_EXEC%" (
    set "PYTHON_EXEC=python"
)

"%PYTHON_EXEC%" -m unittest tests/test_system.py
pause
