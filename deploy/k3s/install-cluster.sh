#!/usr/bin/env bash
# install-cluster.sh — single-node K3s with Cilium as the CNI and network-policy engine.
# Run as root (the agent cannot): sudo K3S_VERSION=... CILIUM_VERSION=... ./install-cluster.sh
# Versions are required, not defaulted: pick the current stable releases and record them in the doc.
#
# What it sets, and why:
#   --flannel-backend=none --disable-network-policy  Cilium replaces both, so policy is enforced once.
#   --disable=traefik --disable=servicelb            no ingress or load balancer; the pilot has no inbound traffic.
#   (no --bind-address)                              pods reach the API server at the node address, so it must
#                                                    listen there; firewalld keeps port 6443 off the LAN (checked below).
#   --secrets-encryption                             Secrets (mailbox and API credentials) are encrypted at rest.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
: "${K3S_VERSION:?set K3S_VERSION, e.g. the current stable v1.x.y+k3s1}"
: "${CILIUM_VERSION:?set CILIUM_VERSION, e.g. the current stable 1.x.y}"
KUBE_USER="${SUDO_USER:?run through sudo so the kubeconfig goes to your account}"
HOME_DIR="$(getent passwd "$KUBE_USER" | cut -d: -f6)"

# The API server listens on every address, so the firewall is what keeps it off the LAN: refuse to
# continue if any active zone opens its port.
if systemctl is-active --quiet firewalld; then
  for zone in $(firewall-cmd --get-active-zones | grep -v '^ '); do
    if firewall-cmd --zone="$zone" --list-ports --list-services | grep -qE '(^|[ ])(6443(/tcp)?|kube-apiserver)([ ]|$)'; then
      echo "firewalld zone '$zone' opens the Kubernetes API port; close it first"; exit 1
    fi
  done
fi

# firewalld: the pod and service ranges must be trusted or pod-to-pod and DNS traffic is dropped.
if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --zone=trusted --add-source=10.42.0.0/16
  firewall-cmd --permanent --zone=trusted --add-source=10.43.0.0/16
  firewall-cmd --reload
fi

curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$K3S_VERSION" sh -s - server \
  --flannel-backend=none --disable-network-policy --disable=traefik --disable=servicelb \
  --secrets-encryption --write-kubeconfig-mode=600

install -d -m 700 -o "$KUBE_USER" "$HOME_DIR/.kube"
install -m 600 -o "$KUBE_USER" /etc/rancher/k3s/k3s.yaml "$HOME_DIR/.kube/k3s.yaml"
echo "kubeconfig: $HOME_DIR/.kube/k3s.yaml   (export KUBECONFIG=\$HOME/.kube/k3s.yaml)"

# Cilium needs a CLI or Helm; Helm is used so the version is pinned in one place.
command -v helm >/dev/null || { echo "install helm first (dnf install helm)"; exit 1; }
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
helm repo add cilium https://helm.cilium.io >/dev/null
helm repo update >/dev/null
helm upgrade --install cilium cilium/cilium --version "$CILIUM_VERSION" --namespace kube-system \
  --set operator.replicas=1 \
  --set ipam.operator.clusterPoolIPv4PodCIDRList=10.42.0.0/16 \
  --set kubeProxyReplacement=false \
  --set hubble.enabled=true --set hubble.relay.enabled=true \
  --set policyEnforcementMode=default
kubectl -n kube-system rollout status ds/cilium --timeout=300s
kubectl wait --for=condition=Ready node --all --timeout=180s
echo "K3s and Cilium are up. Next, as your user: deploy/k3s/build-image.sh then deploy/k3s/apply.sh"
