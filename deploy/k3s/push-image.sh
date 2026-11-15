#!/usr/bin/env bash
# push-image.sh <local-image> [name:tag] — push a podman image to the in-cluster registry. No sudo.
# Example: push-image.sh localhost/crew-chief-listener:pilot   ->  pods use localhost:5000/crew-chief-listener:pilot
set -euo pipefail
SRC="${1:?usage: push-image.sh <local-image> [name:tag]}"
NAME="${2:-${SRC##*/}}"
REGISTRY_IP=10.43.0.50
curl -fsS --max-time 5 "http://$REGISTRY_IP:5000/v2/" >/dev/null || { echo "registry not reachable: run deploy/k3s/install-registry.sh"; exit 1; }
podman tag "$SRC" "$REGISTRY_IP:5000/$NAME"
podman push --tls-verify=false "$REGISTRY_IP:5000/$NAME"
echo "pushed. In a manifest use: image: localhost:5000/$NAME"
