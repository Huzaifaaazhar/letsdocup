@echo off
REM Runs the automated test suite (synthetic documents only).
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m pytest -v
pause
