#!/bin/sh
# PROTOTYPE: sets up .venv on the first run, then starts the spike on http://127.0.0.1:5090
cd "$(dirname "$0")" || exit 1
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
exec .venv/bin/python app.py
