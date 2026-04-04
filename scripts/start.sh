#!/usr/bin/env bash
# scripts/start.sh — build (if needed) and start the crew-chief Podman container.
set -euo pipefail

CONTAINER_NAME="${CREW_CHIEF_CONTAINER:-crew-chief}"
IMAGE_NAME="${CREW_CHIEF_IMAGE:-crew-chief:latest}"
PORT="${CREW_CHIEF_PORT:-11434}"
MODELS_VOLUME="${CREW_CHIEF_MODELS_VOLUME:-crew-chief-models}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Build the image if it does not already exist.
if ! podman image exists "$IMAGE_NAME" 2>/dev/null; then
    echo "Image $IMAGE_NAME not found — building from $REPO_ROOT/Containerfile ..."
    podman build -t "$IMAGE_NAME" "$REPO_ROOT"
fi

# Create the named volume for persisted model weights if missing.
if ! podman volume exists "$MODELS_VOLUME" 2>/dev/null; then
    podman volume create "$MODELS_VOLUME"
fi

# Start or resume the container.
if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    state=$(podman inspect --format '{{.State.Status}}' "$CONTAINER_NAME")
    if [ "$state" = "running" ]; then
        echo "Container $CONTAINER_NAME is already running on http://localhost:${PORT}"
        exit 0
    fi
    echo "Resuming stopped container $CONTAINER_NAME ..."
    podman start "$CONTAINER_NAME"
else
    echo "Creating container $CONTAINER_NAME ..."
    podman run -d \
        --name "$CONTAINER_NAME" \
        -p "${PORT}:11434" \
        -v "${MODELS_VOLUME}:/root/.ollama" \
        "$IMAGE_NAME"
fi

echo "crew-chief is running on http://localhost:${PORT}"
