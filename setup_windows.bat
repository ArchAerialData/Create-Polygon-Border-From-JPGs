@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1"
set "SETUP_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %SETUP_EXIT%
