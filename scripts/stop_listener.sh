#!/usr/bin/env bash
# scripts/stop_listener.sh — stop a background crew-chief listener process.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="${REPO_ROOT}/.crew-chief-listener.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found — listener does not appear to be running."
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    rm -f "$PID_FILE"
    echo "Listener (PID $PID) stopped."
else
    echo "Process $PID not running — cleaning up stale PID file."
    rm -f "$PID_FILE"
fi
