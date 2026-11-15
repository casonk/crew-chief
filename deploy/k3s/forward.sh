#!/usr/bin/env bash
# forward.sh <ui|prometheus|relay> — open a local port to an in-cluster service. Nothing is exposed
# on the network: the forward listens on 127.0.0.1 only and ends when you press Ctrl-C.
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
# 8081 belongs to the Auto Pass web service, so the UI defaults to 8091.
UI_PORT="${HUBBLE_UI_PORT:-8091}"
case "${1:-}" in
  ui)         echo "Hubble UI:  http://127.0.0.1:$UI_PORT"; exec kubectl -n kube-system port-forward --address 127.0.0.1 svc/hubble-ui "$UI_PORT:80" ;;
  prometheus) echo "Prometheus: http://127.0.0.1:9090"; exec kubectl -n monitoring port-forward --address 127.0.0.1 svc/prometheus 9090:9090 ;;
  relay)      echo "Hubble relay: hubble observe --server 127.0.0.1:4245 ..."; exec kubectl -n kube-system port-forward --address 127.0.0.1 svc/hubble-relay 4245:80 ;;
  *) echo "usage: $0 ui|prometheus|relay"; exit 2 ;;
esac
