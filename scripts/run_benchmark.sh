#!/usr/bin/env bash
# scripts/run_benchmark.sh — weekly benchmark wrapper called by the clockwork
# systemd timer. Generates a dated JSON + HTML report, optionally wrapped in
# a tachometer resource snapshot if tachometer is on PATH.
set -euo pipefail

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

echo "[run_benchmark] Done — ${JSON_OUT}"
echo "[run_benchmark] Done — ${HTML_OUT}"
