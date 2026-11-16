@echo off
setlocal
TITLE CodeX Library - Local Web App
cd /d "%~dp0"
echo.
echo =============================================================
echo       CodeX Library Management - Web Application
 echo =============================================================
echo.
echo Launching your local library app at http://127.0.0.1:8766
 echo Keep this window open while using the application.
echo.
where py >nul 2>nul
if not errorlevel 1 (
    py -3 server.py
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3 is required. Install it from https://www.python.org/downloads/
        echo During installation, select Add Python to PATH.
        pause
        exit /b 1
    )
    python server.py
)
echo.
echo The application has closed.
pause
