#!/usr/bin/env bash
# Mac/Linux equivalent of run_app.bat
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt; }
. .venv/bin/activate
streamlit run app.py --server.port 8501 --server.address localhost
