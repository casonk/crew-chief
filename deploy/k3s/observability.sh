#!/usr/bin/env bash
# observability.sh — add the Hubble UI, Hubble and Cilium Prometheus metrics, and a Prometheus to scrape
# them. Run as your normal user (no sudo). Safe to repeat. Restarts the Cilium agent once; running
# pods keep their connections and the policy stays enforced while it restarts.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"

# Keep the release at the version it already has: this upgrades settings, never Cilium itself.
VERSION="$(helm -n kube-system get metadata cilium -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
echo "Cilium chart $VERSION: enabling the Hubble UI and Prometheus metrics"
helm repo add cilium https://helm.cilium.io >/dev/null
helm repo update >/dev/null
helm upgrade cilium cilium/cilium --version "$VERSION" --namespace kube-system --reuse-values \
  -f "$HERE/observability/cilium-values.yaml"
kubectl -n kube-system rollout status ds/cilium --timeout=300s
kubectl -n kube-system rollout status deploy/hubble-ui --timeout=180s

kubectl apply -f "$HERE/observability/prometheus.yaml"
kubectl -n monitoring rollout status deploy/prometheus --timeout=180s
echo "Done. Reach them with: deploy/k3s/forward.sh ui | prometheus | relay"
