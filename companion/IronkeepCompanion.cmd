@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0IronkeepCompanion.ps1" %*
echo.
echo Press any key to close.
pause >nul
