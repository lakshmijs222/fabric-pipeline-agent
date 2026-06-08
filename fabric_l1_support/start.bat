@echo off
title Fabric L1 Support Bot

echo ================================================
echo   Microsoft Fabric L1 Support Bot
echo ================================================
echo.

cd /d D:\Claude\fabric-l1-bot\fabric_l1_support

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python first.
    pause
    exit
)

:: Install dependencies
echo [1/3] Installing dependencies...
pip install -r requirements.txt --quiet
echo Done.
echo.

:: Generate sample data if audit log is missing
if not exist "logs\audit.jsonl" (
    echo [2/3] No audit log found. Generating sample data...
    python dashboard/generate_sample_data.py
    echo Done.
) else (
    echo [2/3] Audit log found. Skipping sample data.
)
echo.

:: Start Dashboard in new window
echo [3/3] Starting Dashboard...
start "Fabric Dashboard" cmd /k "cd /d D:\Claude\fabric-l1-bot\fabric_l1_support && streamlit run dashboard/app.py --server.port 8503"
timeout /t 3 /nobreak >nul

:: Open browser
echo Opening dashboard in browser...
start http://localhost:8503
echo.

:: Start Bot in current window
echo ================================================
echo   Bot is now running. Press Ctrl+C to stop.
echo   Dashboard: http://localhost:8503
echo ================================================
echo.
python main.py

pause
