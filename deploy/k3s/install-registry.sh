#!/usr/bin/env bash
# install-registry.sh — start the in-cluster image registry. Run as your normal user; safe to repeat.
# Pods can pull from it only after the one-time root step: sudo deploy/k3s/enable-registry-mirror.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
kubectl wait --for=condition=Ready node --all --timeout=60s
kubectl get crd ciliumnetworkpolicies.cilium.io >/dev/null
kubectl apply -f "$HERE/registry/registry.yaml"
kubectl -n registry rollout status deploy/registry --timeout=180s
# kube-proxy takes a few seconds to program a new Service, so retry before calling it a failure.
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://10.43.0.50:5000/v2/ >/dev/null 2>&1; then
    echo "registry answers at 10.43.0.50:5000"; ok=1; break
  fi
  sleep 2
done
[ "${ok:-0}" = 1 ] || { echo "registry did not answer at 10.43.0.50:5000"; exit 1; }
echo "Next, once, as root: sudo deploy/k3s/enable-registry-mirror.sh"
