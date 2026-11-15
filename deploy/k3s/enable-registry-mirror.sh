#!/usr/bin/env bash
# enable-registry-mirror.sh — let K3s pull localhost:5000/<name> from the in-cluster registry.
# Run once as root: sudo deploy/k3s/enable-registry-mirror.sh
# Writes /etc/rancher/k3s/registries.yaml and restarts K3s (pods are recreated within a minute). It refuses to
# overwrite a registries.yaml that already differs, so any registry settings you have are never lost.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST=/etc/rancher/k3s/registries.yaml
if [ -e "$DEST" ]; then
  if cmp -s "$HERE/registry/registries.yaml" "$DEST"; then echo "already enabled"; exit 0; fi
  echo "$DEST exists and differs; merge $HERE/registry/registries.yaml into it by hand"; exit 1
fi
install -m 644 "$HERE/registry/registries.yaml" "$DEST"
systemctl restart k3s
echo "K3s restarted with the registry mirror. Check: kubectl get nodes"
