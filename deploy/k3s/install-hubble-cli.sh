#!/usr/bin/env bash
# install-hubble-cli.sh — install the `hubble` CLI to ~/.local/bin, checking its SHA-256.
# Run as your normal user. HUBBLE_VERSION defaults to the installed Cilium chart version (they release together).
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/k3s.yaml}"
VERSION="${HUBBLE_VERSION:-v$(helm -n kube-system get metadata cilium -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')}"
case "$(uname -m)" in x86_64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) echo "unsupported arch"; exit 1 ;; esac
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
BASE="https://github.com/cilium/hubble/releases/download/$VERSION"
curl -fsSL -o "$TMP/hubble.tgz" "$BASE/hubble-linux-$ARCH.tar.gz"
curl -fsSL -o "$TMP/hubble.sha256" "$BASE/hubble-linux-$ARCH.tar.gz.sha256sum"
( cd "$TMP" && sed "s#hubble-linux-$ARCH.tar.gz#hubble.tgz#" hubble.sha256 | sha256sum -c - )
tar -xzf "$TMP/hubble.tgz" -C "$TMP" hubble
install -d "$HOME/.local/bin"
install -m 755 "$TMP/hubble" "$HOME/.local/bin/hubble"
"$HOME/.local/bin/hubble" version
