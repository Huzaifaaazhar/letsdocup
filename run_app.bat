@echo off
REM Starts BL Manager and opens it in your web browser.
REM Keep this black window open while you use the application.
REM Close it (or press Ctrl+C) to stop the application.
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
    echo BL Manager is not installed yet. Double-click install.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
echo Starting BL Manager... your browser will open in a few seconds.
echo Address: http://localhost:8501
start "" cmd /c "timeout /t 6 >nul & start http://localhost:8501"
streamlit run app.py --server.port 8501 --server.address localhost
pause
