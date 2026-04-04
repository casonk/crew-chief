#!/usr/bin/env bash
# scripts/status.sh — report whether the crew-chief service is running and reachable.
set -euo pipefail

CONTAINER_NAME="${CREW_CHIEF_CONTAINER:-crew-chief}"
PORT="${CREW_CHIEF_PORT:-11434}"

echo "=== Container state ==="
if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    podman inspect --format 'Name: {{.Name}}  Status: {{.State.Status}}' "$CONTAINER_NAME"
else
    echo "Container $CONTAINER_NAME does not exist."
fi

echo ""
echo "=== Service health ==="
if curl -sf "http://localhost:${PORT}/" >/dev/null 2>&1; then
    echo "Service is reachable at http://localhost:${PORT}"
else
    echo "Service is NOT reachable at http://localhost:${PORT}"
fi
