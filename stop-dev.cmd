@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" -Action stop
set "exit_code=%ERRORLEVEL%"
endlocal & exit /b %exit_code%
