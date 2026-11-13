#!/usr/bin/env bash
# build-image.sh — build the listener image from a staged tree and import it into K3s.
# Run as the normal user; the final import step uses sudo.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREW="$(cd "$HERE/../.." && pwd)"
SHOCK="${SHOCK_RELAY_DIR:-$CREW/../shock-relay}"
IMAGE="localhost/crew-chief-listener:pilot"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/stage/crew-chief" "$WORK/stage/shock-relay/services"
cp -r "$CREW/src" "$WORK/stage/crew-chief/src"
cp "$SHOCK/offline_queue.py" "$WORK/stage/shock-relay/" 2>/dev/null || true
cp -r "$SHOCK/services/gmail-imap" "$WORK/stage/shock-relay/services/gmail-imap"
# Only the Gmail channel ships in phase 1; local config and caches stay out of the image.
find "$WORK/stage" \( -name '__pycache__' -o -name 'config.local.yaml' -o -name '*.pyc' \) -prune -exec rm -rf {} +
cp "$HERE/Containerfile.listener" "$WORK/Containerfile"
podman build -t "$IMAGE" -f "$WORK/Containerfile" "$WORK"
echo "Importing $IMAGE into K3s (needs sudo)"
podman save "$IMAGE" | sudo k3s ctr images import -
