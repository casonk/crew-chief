#!/usr/bin/env bash
# apply.sh — create the pilot's Secrets from local files and apply the manifests.
# Needs: kubectl pointed at the pilot cluster, auto-pass working (vault reachable), the image imported.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREW="$(cd "$HERE/../.." && pwd)"
SHOCK="${SHOCK_RELAY_DIR:-$CREW/../shock-relay}"
NS=crew-chief-listener
LIVE="${CREW_CHIEF_LISTENER_CONFIG:-$CREW/config/listener/config.toml}"
GMAIL_LIVE="${GMAIL_IMAP_CONFIG:-$SHOCK/services/gmail-imap/config.local.yaml}"

WORK="$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/k3s-pilot.XXXXXX")"; chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT

# Refuse to run on a cluster that is not ready: the policy kind must exist, or the pod would start unconfined.
kubectl wait --for=condition=Ready node --all --timeout=60s \
  || { echo "the node is not Ready; check 'kubectl -n kube-system get pods' (Cilium must be Running)"; exit 1; }
kubectl get crd ciliumnetworkpolicies.cilium.io >/dev/null \
  || { echo "Cilium's CiliumNetworkPolicy kind is missing; Cilium is not installed"; exit 1; }

kubectl apply -f "$HERE/manifests/00-namespace.yaml"
python3 "$HERE/make_config.py" --source "$LIVE" --out "$WORK/config.toml"
python3 "$HERE/make_secrets.py" --listener-config "$LIVE" --gmail-config "$GMAIL_LIVE" \
  --crew-chief-src "$CREW/src" --gmail-dir "$SHOCK/services/gmail-imap" --out "$WORK/secrets"

secret() { kubectl -n "$NS" create secret generic "$@" --dry-run=client -o yaml | kubectl apply -f - >/dev/null; }
secret listener-config --from-file=config.toml="$WORK/config.toml"
secret listener-env --from-env-file="$WORK/secrets/listener.env"
secret listener-gmail --from-file=config.local.yaml="$WORK/secrets/gmail.config.local.yaml"

kubectl apply -f "$HERE/manifests/30-network-policy.yaml"   # policy first: the pod never runs unconfined
kubectl apply -f "$HERE/manifests/20-deployment.yaml"
kubectl -n "$NS" rollout status deploy/crew-chief-listener --timeout=120s
