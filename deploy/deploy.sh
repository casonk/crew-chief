#!/usr/bin/env bash
# deploy.sh — run the crew-chief listener the way you choose: dev, host or k3s. One entry point, one setting.
#
#   deploy/deploy.sh [--mode dev|host|k3s] up|down|status|verify|mode
#
# The mode comes from, first match wins:
#   1. --mode on the command line
#   2. CREW_CHIEF_DEPLOY_MODE in the environment
#   3. CREW_CHIEF_DEPLOY_MODE in config/deploy.local.env (copy config/deploy.example.env; never committed)
#   4. dev
#
# This covers the listener (the Gmail/Signal command channel), not the Ollama service. Only k3s mode touches
# kubectl, podman or a cluster. See docs/deployment.md for what each mode needs, does, and how to switch.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
K3S_DIR="${CREW_CHIEF_K3S_DIR:-$HERE/k3s}"
CONFIG_FILE="${CREW_CHIEF_DEPLOY_CONFIG:-$REPO/config/deploy.local.env}"
LISTENER_CONFIG="${CREW_CHIEF_LISTENER_CONFIG:-$REPO/config/listener/config.toml}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/crew-chief"
MARKER="$STATE_DIR/deploy-mode"
UNIT="crew-chief-listener.service"
NS="crew-chief-listener"
MODES="dev host k3s"

usage() {
  sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-2}"
}

mode="" source_of=""
cmd=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) mode="${2:?--mode needs dev, host or k3s}"; source_of="--mode"; shift 2 ;;
    --mode=*) mode="${1#--mode=}"; source_of="--mode"; shift ;;
    -h|--help) usage 0 ;;
    up|down|status|verify|mode) cmd="$1"; shift ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done
[ -n "$cmd" ] || usage 2

if [ -z "$mode" ] && [ -n "${CREW_CHIEF_DEPLOY_MODE:-}" ]; then mode="$CREW_CHIEF_DEPLOY_MODE"; source_of="environment"; fi
if [ -z "$mode" ] && [ -f "$CONFIG_FILE" ]; then
  # No `|| true`: if reading the config fails, say so rather than quietly choosing dev.
  line="$(python3 -I "$K3S_DIR/env_value.py" "$CONFIG_FILE" CREW_CHIEF_DEPLOY_MODE)"
  if [ -n "$line" ]; then mode="${line#CREW_CHIEF_DEPLOY_MODE=}"; source_of="$CONFIG_FILE"; fi
fi
if [ -z "$mode" ]; then mode="dev"; source_of="default"; fi
case " $MODES " in *" $mode "*) ;; *) echo "unknown deployment mode '$mode' (from $source_of); use one of: $MODES" >&2; exit 2 ;; esac

need() { command -v "$1" >/dev/null 2>&1 || { echo "$2" >&2; exit 1; }; }
marker_is_k3s() { [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = k3s ]; }
set_marker() { mkdir -p "$STATE_DIR"; echo "$1" > "$MARKER"; }
clear_marker() { rm -f "$MARKER"; }
kc() { KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}" "${KUBECTL:-kubectl}" "$@"; }
host_unit_installed() { systemctl --user cat "$UNIT" >/dev/null 2>&1; }
host_unit_active() { systemctl --user is-active --quiet "$UNIT" 2>/dev/null; }
pod_off() { kc -n "$NS" scale deploy/crew-chief-listener --replicas=0; }

case "$cmd:$mode" in
  mode:*) echo "$mode (from $source_of)" ;;

  # ---- dev: the listener in the foreground, no systemd, no cluster ----
  up:dev)
    [ -f "$LISTENER_CONFIG" ] || { echo "no listener config at $LISTENER_CONFIG (copy config/listener/config.toml.example)" >&2; exit 1; }
    exec env PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}" python3 -m crew_chief listen --config "$LISTENER_CONFIG"
    ;;
  down:dev) echo "dev mode runs in the foreground; stop it with Ctrl-C" ;;
  status:dev|verify:dev) echo "dev mode runs in the foreground; there is no service to check (deploy/deploy.sh up)" ;;

  # ---- host: the Clockwork-managed systemd user service ----
  up:host)
    if marker_is_k3s; then
      echo "the K3s listener is active; stopping it before the host listener starts"
      if command -v "${KUBECTL:-kubectl}" >/dev/null 2>&1; then pod_off
      else echo "kubectl is not installed: scale the Deployment to 0 yourself (docs/deployment.md) or both will answer mail" >&2; exit 1; fi
    fi
    host_unit_installed || {
      echo "$UNIT is not installed. Install it with Clockwork from its examples/crew-chief/listener-service.toml (see docs/deployment.md)" >&2
      exit 1
    }
    systemctl --user enable --now "$UNIT"
    clear_marker
    ;;
  down:host) systemctl --user disable --now "$UNIT"; clear_marker ;;
  status:host)
    printf '%-30s %-9s %s\n' "$UNIT" "$(systemctl --user is-active "$UNIT" 2>/dev/null || true)" \
      "$(systemctl --user is-enabled "$UNIT" 2>/dev/null || true)" ;;
  verify:host) systemctl --user is-active --quiet "$UNIT" && echo "$UNIT is active" ;;

  # ---- k3s: a pod, default-deny egress, secrets from the host's vault ----
  up:k3s)
    need "${KUBECTL:-kubectl}" "k3s mode needs kubectl and a running K3s (see docs/deployment.md). dev and host modes need neither."
    need podman "k3s mode needs podman, to build the image"
    export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
    curl -fsS --max-time 5 http://10.43.0.50:5000/v2/ >/dev/null 2>&1 || {
      echo "k3s mode needs the in-cluster registry: run deploy/k3s/install-registry.sh, then sudo deploy/k3s/enable-registry-mirror.sh" >&2
      exit 1
    }
    # Two listeners on one mailbox would answer every email twice, so the host listener stops first and is
    # put back if anything below fails.
    was_active=0
    if host_unit_active; then was_active=1; systemctl --user disable --now "$UNIT"; fi
    restore() {
      echo "the K3s deployment failed; restoring the previous listener" >&2
      pod_off 2>/dev/null || true
      if [ "$was_active" = 1 ]; then systemctl --user enable --now "$UNIT" || true; fi
    }
    trap restore ERR
    "$K3S_DIR/build-image.sh"
    "$K3S_DIR/apply.sh"
    "$K3S_DIR/verify.sh"
    trap - ERR
    set_marker k3s
    ;;
  down:k3s) "$0" --mode host up; echo "rolled back to the host listener; the pod is scaled to 0 and left in place (kubectl delete ns $NS removes it)" ;;
  status:k3s)
    printf '%-30s %-9s %s\n' "$UNIT" "$(systemctl --user is-active "$UNIT" 2>/dev/null || true)" \
      "$(systemctl --user is-enabled "$UNIT" 2>/dev/null || true)"
    kc -n "$NS" get deploy,pods 2>&1 || true ;;
  verify:k3s) "$K3S_DIR/verify.sh" ;;
esac
