#!/usr/bin/env bash
# scripts/stop.sh — stop the crew-chief Podman container.
set -euo pipefail

CONTAINER_NAME="${CREW_CHIEF_CONTAINER:-crew-chief}"

if ! podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    echo "Container $CONTAINER_NAME does not exist."
    exit 0
fi

podman stop "$CONTAINER_NAME"
echo "crew-chief stopped."
