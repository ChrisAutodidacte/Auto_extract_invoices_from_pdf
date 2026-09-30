@echo off
chcp 65001 > nul
title Smart PDF Invoice Splitter - Chris Figures It Out
echo ============================================================
echo   SMART PDF INVOICE SPLITTER AND RENAMER (GEMINI AI)
echo ============================================================
echo.

:: Check if .env configuration file exists
if not exist "%~dp0.env" (
    echo [WARNING] The .env configuration file was not found.
    echo Please copy .env.example to .env and insert your Google Gemini API key.
    echo.
    echo Get your free key at https://aistudio.google.com/
    echo.
    pause
    exit /b 1
)

:: Activate virtual environment if present
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
)

:: Run Python script
python "%~dp0invoice_processor.py"

echo.
echo ============================================================
echo Process finished.
echo.
pause
