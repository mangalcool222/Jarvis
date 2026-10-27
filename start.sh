#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
echo "⚡ Starting Jarvis #1 Speed-to-Lead Outbound OS (Dubai) on Port 5555..."
if lsof -i :5555 >/dev/null 2>&1; then
    echo "Port 5555 is already running. Opening browser..."
    open "http://localhost:5555/#today"
else
    (sleep 1 && open "http://localhost:5555/#today" &)
    ./.venv/bin/harvey dashboard --port 5555 --host 0.0.0.0
fi
