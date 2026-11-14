#!/usr/bin/env bash
# verify.sh — prove the policy from inside the pod. Each probe states what it expects.
# A pass means the policy did what it claims; a failure means the pilot is not safe to leave running.
set -uo pipefail
NS=crew-chief-listener
# A verifier that cannot run its probes must fail, not pass: "closed" is only meaningful when the
# probe actually executed inside a running pod.
POD="$(kubectl -n "$NS" get pod -l app=crew-chief-listener --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
[ -n "$POD" ] || { echo "FAIL  no running listener pod in namespace $NS; nothing was verified"; exit 2; }
fail=0
probe() { # probe <expect: open|closed> <label> <host> <port>
  local expect="$1" label="$2" host="$3" port="$4" got
  got="$(kubectl -n "$NS" exec "$POD" -- python3 -c "
import socket
try:
    socket.create_connection(('$host',$port),timeout=6).close(); print('open')
except OSError:
    print('closed')" 2>/dev/null)"
  case "$got" in
    open|closed) ;;
    *) echo "FAIL  $label: the probe could not run inside the pod"; fail=1; return ;;
  esac
  if [ "$got" = "$expect" ]; then echo "ok    $label ($host:$port is $got)"; else echo "FAIL  $label ($host:$port is $got, expected $expect)"; fail=1; fi
}
probe open   "Gmail IMAP"                imap.gmail.com 993
probe open   "Gmail SMTP"                smtp.gmail.com 587
probe open   "Anthropic API"             api.anthropic.com 443
probe closed "arbitrary internet host"   example.com 443
probe closed "other port on an allowed host" imap.gmail.com 443
probe closed "link-local metadata address" 169.254.169.254 80
probe closed "Kubernetes API"            kubernetes.default.svc 443
NODE_IP="$(kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' | awk '{print $1}')"
probe closed "host Ollama (node address)" "$NODE_IP" 11434
probe closed "host SSH (node address)"    "$NODE_IP" 22
echo "--- no API token mounted:"
kubectl -n "$NS" exec "$POD" -- sh -c 'ls /var/run/secrets/kubernetes.io 2>&1 | head -1' 2>&1 | sed 's/^/    /'
echo "--- security context:"
kubectl -n "$NS" get pod "$POD" -o jsonpath='{.spec.containers[0].securityContext}{"\n"}'
exit $fail
