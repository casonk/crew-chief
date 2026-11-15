#!/usr/bin/env bash
# build-image.sh — build the listener image from a staged tree and push it to the in-cluster registry.
# Run as the normal user, no sudo. Needs deploy/k3s/install-registry.sh (and, once, enable-registry-mirror.sh).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREW="$(cd "$HERE/../.." && pwd)"
SHOCK="${SHOCK_RELAY_DIR:-$CREW/../shock-relay}"
IMAGE="localhost/crew-chief-listener:pilot"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# The pod runs what is committed; the host listener runs whatever is in the checkout. If they differ, replies
# differ by where the message was handled. Build only from committed code, or say so explicitly.
if [ -z "${ALLOW_DIRTY:-}" ] && [ -n "$(git -C "$CREW" status --porcelain -- src)" ]; then
  echo "src/ has uncommitted changes; the image would not match what is committed. Commit them, or set ALLOW_DIRTY=1." >&2
  exit 1
fi
mkdir -p "$WORK/stage/crew-chief" "$WORK/stage/shock-relay/services"
cp -r "$CREW/src" "$WORK/stage/crew-chief/src"
cp "$SHOCK/offline_queue.py" "$WORK/stage/shock-relay/" 2>/dev/null || true
cp -r "$SHOCK/services/gmail-imap" "$WORK/stage/shock-relay/services/gmail-imap"
# Only the Gmail channel ships in phase 1; local config and caches stay out of the image.
find "$WORK/stage" \( -name '__pycache__' -o -name 'config.local.yaml' -o -name '*.pyc' \) -prune -exec rm -rf {} +
cp "$HERE/Containerfile.listener" "$WORK/Containerfile"
podman build -t "$IMAGE" -f "$WORK/Containerfile" "$WORK"
"$HERE/push-image.sh" "$IMAGE" crew-chief-listener:pilot
echo "Roll it out: kubectl -n crew-chief-listener rollout restart deploy/crew-chief-listener"
