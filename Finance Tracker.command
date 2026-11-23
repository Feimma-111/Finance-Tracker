#!/bin/bash
# Double-click this file in Finder to open the finance tracker dashboard.
# A Terminal window opens to run the server; close it (or press Ctrl-C) to stop.

cd "$(dirname "$0")" || exit 1
URL="http://127.0.0.1:8000"

# Already running? Just open the browser.
if curl -s -m 1 "$URL/api/profile" > /dev/null 2>&1; then
  open "$URL"
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "Setup needed: run  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  read -r -p "Press Enter to close."
  exit 1
fi

if [ ! -d frontend/dist ]; then
  echo "Building the website (first run only)..."
  export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
  (cd frontend && npm install --no-fund --no-audit && npm run build) || {
    read -r -p "Build failed. Press Enter to close."
    exit 1
  }
fi

.venv/bin/python main.py --web --open
