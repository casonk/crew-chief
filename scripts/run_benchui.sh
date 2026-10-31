#!/usr/bin/env bash
# scripts/run_benchui.sh — foreground entrypoint for the crew-chief bench interface.
# Used by systemd as ExecStart. It binds to loopback; the shared Caddy
# (wiring-harness) is the only way in from the network.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 -m crew_chief benchui --port "${CREW_CHIEF_BENCH_PORT:-8766}"
