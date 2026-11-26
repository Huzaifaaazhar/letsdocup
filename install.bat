@echo off
REM ============================================================
REM  BL Manager - one-time installation (Windows)
REM  Double-click this file. It creates a private Python
REM  environment in the ".venv" folder and installs everything.
REM ============================================================
cd /d "%~dp0"
echo.
echo === BL Manager installation ===
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    set PY=py -3
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python is not installed or not on PATH.
        echo Install Python 3.12 from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH" during installation.
        pause
        exit /b 1
    )
    set PY=python
)
%PY% --version
if not exist .venv (
    echo Creating private Python environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo ERROR: could not create the environment.
        pause
        exit /b 1
    )
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
echo.
echo Installing core components...
python -m pip install "pymupdf>=1.24" "streamlit>=1.50" "pandas>=2.0" "openpyxl>=3.1" "reportlab>=4.0" "pytest>=8.0"
if errorlevel 1 (
    echo ERROR: installation of core components failed. See the messages above.
    pause
    exit /b 1
)
echo.
echo Installing OCR component for scanned PDFs (optional)...
python -m pip install "rapidocr_onnxruntime>=1.2"
if errorlevel 1 (
    echo WARNING: OCR could not be installed. The application will still work
    echo for normal text PDFs, but scanned pages cannot be read.
)
echo.
echo === Installation finished. Double-click run_app.bat to start. ===
pause
