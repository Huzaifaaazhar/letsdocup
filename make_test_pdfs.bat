@echo off
REM Creates SYNTHETIC (fake) BL PDFs in the "sample_pdfs" folder for testing.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python tools\make_sample_pdfs.py
echo.
echo Open the "sample_pdfs" folder to find the test files.
pause
