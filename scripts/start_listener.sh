#!/usr/bin/env bash
# scripts/start_listener.sh — start the crew-chief shock-relay listener in the background.
#
# Usage:
#   scripts/start_listener.sh [CONFIG_PATH]
#
# CONFIG_PATH defaults to config/listener/config.toml.
# The listener logs to .crew-chief-listener.log in this directory.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${REPO_ROOT}/config/listener/config.toml}"
LOG_FILE="${REPO_ROOT}/.crew-chief-listener.log"
PID_FILE="${REPO_ROOT}/.crew-chief-listener.pid"

if [ ! -f "$CONFIG_PATH" ]; then
    echo "Error: listener config not found at $CONFIG_PATH" >&2
    echo "Copy config/listener/config.toml.example to config/listener/config.toml and configure it." >&2
    exit 1
fi

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Listener is already running (PID $OLD_PID). Use scripts/stop_listener.sh to stop it."
        exit 0
    fi
    rm -f "$PID_FILE"
fi

echo "Starting crew-chief listener..."
nohup python3 -m crew_chief listen --config "$CONFIG_PATH" >> "$LOG_FILE" 2>&1 &
LISTENER_PID=$!
echo "$LISTENER_PID" > "$PID_FILE"
echo "Listener started (PID $LISTENER_PID). Logs: $LOG_FILE"
