#!/usr/bin/env bash
# scripts/run_listener.sh — foreground entrypoint for the crew-chief listener.
# Used by systemd as ExecStart — do NOT run with nohup or & here.
# The process stays in the foreground; systemd manages lifecycle.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${CREW_CHIEF_LISTENER_CONFIG:-${REPO_ROOT}/config/listener/config.toml}"

if [ ! -f "$CONFIG_PATH" ]; then
    echo "Error: listener config not found at $CONFIG_PATH" >&2
    exit 1
fi

exec python3 -m crew_chief listen \
    --config "$CONFIG_PATH" \
    --log-level "${CREW_CHIEF_LOG_LEVEL:-INFO}"
