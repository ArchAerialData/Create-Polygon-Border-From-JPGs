@echo off
set "APP_DIR=%~dp0"
if exist "%APP_DIR%.venv\Scripts\python.exe" (
    "%APP_DIR%.venv\Scripts\python.exe" "%APP_DIR%src\run_jpg_boundary_gui.py" %*
) else (
    echo Virtual environment not found. Run setup_windows.bat first.
    pause
    exit /b 1
)
