#!/usr/bin/env bash
# scripts/run_ollama.sh — run the crew-chief Ollama container in the foreground.
#
# Intended as the ExecStart for the crew-chief-ollama.service user unit so that
# systemd manages the container lifecycle directly (restart, journal, linger).
#
# --replace stops any pre-existing detached container with the same name so the
# service can take ownership cleanly on start or restart.
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

# Run in the foreground (no -d); systemd owns the process lifetime.
# --replace stops any existing container of the same name before starting.
exec podman run --rm --replace \
    --name "$CONTAINER_NAME" \
    -p "${PORT}:11434" \
    -v "${MODELS_VOLUME}:/root/.ollama" \
    "$IMAGE_NAME"
