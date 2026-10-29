#!/usr/bin/env bash
# scripts/run_benchmark.sh — weekly benchmark wrapper called by the clockwork
# systemd timer. Generates a dated JSON + HTML report, optionally wrapped in
# a tachometer resource snapshot if tachometer is on PATH.
#
# Latency numbers are only meaningful on an idle GPU. When `ecu` is on PATH the
# script re-runs itself under an exclusive ECU lease, which pauses the listener
# and other GPU consumers and waits (up to 45 minutes, inside the unit's 2 hour
# limit) for live GPU work to finish. The 2026-10-25 run had no lease, shared the
# GPU with other jobs (first-token times of 5-7 minutes) and hit the unit's time
# limit mid-run. Set CREW_CHIEF_NO_LEASE=1 to skip the lease.
set -euo pipefail

if [[ -z "${CREW_CHIEF_IN_LEASE:-}" && -z "${CREW_CHIEF_NO_LEASE:-}" ]] \
    && command -v ecu >/dev/null 2>&1; then
  export CREW_CHIEF_IN_LEASE=1
  exec ecu run --gpu exclusive --own-gpu-process llama-server \
    --cpu-cores 2 --priority batch --max-wait 45m -- bash "${BASH_SOURCE[0]}" "$@"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATE="$(date +%Y%m%d)"
RESULTS_DIR="${REPO_ROOT}/results"
JSON_OUT="${RESULTS_DIR}/bench-${DATE}.json"
HTML_OUT="${RESULTS_DIR}/bench-${DATE}.html"
TACHOMETER_MANIFEST="${REPO_ROOT}/config/tachometer/profile.toml"

mkdir -p "${RESULTS_DIR}"

BENCHMARK_CMD=(
    python3 "${REPO_ROOT}/scripts/benchmark.py"
    --prompts latency reasoning codegen summarise
    --runs 1
    --timeout 900
    --json "${JSON_OUT}"
)

echo "[run_benchmark] Starting benchmark — $(date)"

if command -v tachometer &>/dev/null && [[ -f "${TACHOMETER_MANIFEST}" ]]; then
    echo "[run_benchmark] tachometer found — wrapping for resource snapshot"
    tachometer run --manifest "${TACHOMETER_MANIFEST}" -- "${BENCHMARK_CMD[@]}"
else
    echo "[run_benchmark] tachometer not on PATH — running benchmark directly"
    "${BENCHMARK_CMD[@]}"
fi

echo "[run_benchmark] Benchmark complete — generating HTML report"
python3 "${REPO_ROOT}/scripts/report.py" "${JSON_OUT}" --out "${HTML_OUT}"

ln -sf "$(basename "${HTML_OUT}")" "${RESULTS_DIR}/latest.html"

# Retired models on warm and cold storage are benchmarked less often, on their
# tier's cadence. Skipped quietly until storage tiers are configured.
if [[ -f "${CREW_CHIEF_STORAGE_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/crew-chief/storage.toml}" ]]; then
    echo "[run_benchmark] Benchmarking warm/cold models that are due"
    PYTHONPATH="${REPO_ROOT}/src" python3 -m crew_chief storage bench-due ||
        echo "[run_benchmark] warning: storage bench-due failed"
fi

echo "[run_benchmark] Done — ${JSON_OUT}"
echo "[run_benchmark] Done — ${HTML_OUT}"
echo "[run_benchmark] Symlink updated — ${RESULTS_DIR}/latest.html"
