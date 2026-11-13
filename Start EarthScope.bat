@echo off
rem EarthScope AI launcher - double-click this file. It works from any location.
title EarthScope AI
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo First run: creating the Python environment and installing packages.
    echo This can take several minutes...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    "venv\Scripts\python.exe" -m pip install --upgrade pip
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Package installation failed. Check your internet connection and run this file again.
        pause
        exit /b 1
    )
)

echo Starting EarthScope AI... your browser will open at http://localhost:8501
echo Keep this window open while you use the app. Close it to stop the app.
"venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
pause
