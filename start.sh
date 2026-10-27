#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
echo "⚡ Starting Jarvis #1 Speed-to-Lead Outbound OS (Dubai) on Port 5555..."

# 1. Start Autonomous 24x7 Heartbeat Loop (Scout, Profiler, Email Writer)
if pgrep -f "harvey run" >/dev/null 2>&1; then
    echo "🤖 Jarvis 24x7 Autonomous Heartbeat Brain is ALREADY active!"
else
    echo "🚀 Starting Jarvis 24x7 Autonomous Heartbeat Daemon..."
    nohup ./.venv/bin/harvey run >> data/heartbeat.log 2>&1 &
    sleep 1
    echo "✅ Jarvis 24x7 Autonomous Brain is now running in background (PID: $!)."
fi

# 2. Start Web Dashboard UI
if lsof -i :5555 >/dev/null 2>&1; then
    echo "⚡ Port 5555 Dashboard is already running. Opening browser..."
    open "http://localhost:5555/#today"
else
    (sleep 1 && open "http://localhost:5555/#today" &)
    ./.venv/bin/harvey dashboard --port 5555 --host 0.0.0.0
fi
