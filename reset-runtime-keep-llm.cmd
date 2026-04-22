@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\reset_runtime_keep_llm.ps1" -StopServices
set "exit_code=%ERRORLEVEL%"

endlocal & exit /b %exit_code%
