#!/usr/bin/env bash
# Benchmark Ollama-pulled models with llama.cpp's own llama-bench.
#
# Runs the official llama.cpp CUDA image under rootless Podman, reading the
# GGUF blobs straight from the crew-chief-models volume (no re-download).
#
# Usage:
#   bash scripts/llamacpp_bench.sh qwen3:14b llama3.1:8b
#   bash scripts/llamacpp_bench.sh qwen3:32b -- -p 4096 -n 256 -ctk q8_0 -ctv q8_0
#   bash scripts/llamacpp_bench.sh ~/models/Qwen3.5-27B-Q4_K_M.gguf
#
# Arguments before -- are Ollama model names or paths to .gguf files (for
# llama.cpp-native downloads, e.g. when llama.cpp cannot read Ollama's copy of
# a model); results label a file by its name only. Anything after -- is passed to
# llama-bench and replaces the default test set. Results are printed and saved
# to results/llamacpp-bench-<timestamp>.{md,jsonl}.
#
# For clean numbers, nothing else should be on the GPU. When `ecu` is on PATH
# the script re-runs itself under an exclusive ECU lease, which unloads Ollama
# models, pauses the listener and other GPU consumers, waits (up to 2 hours) for
# live GPU work to finish, and restores everything afterwards. Set
# CREW_CHIEF_NO_LEASE=1 to skip that and manage the GPU by hand
# (podman exec crew-chief ollama stop <model>; systemctl --user stop
# crew-chief-listener).
#
# Environment:
#   LLAMACPP_IMAGE        default: ghcr.io/ggml-org/llama.cpp:full-cuda
#   CREW_CHIEF_MODELS_VOLUME  default: crew-chief-models
#   CREW_CHIEF_MODELS_DIR     an Ollama-layout models directory to read instead
#                             of the volume (a warm or cold storage tier)
#   HOST_NVIDIA_LIB       default: /usr/lib64

set -euo pipefail

if [[ -z "${CREW_CHIEF_IN_LEASE:-}" && -z "${CREW_CHIEF_NO_LEASE:-}" ]] \
    && command -v ecu >/dev/null 2>&1; then
  export CREW_CHIEF_IN_LEASE=1
  exec ecu run --gpu exclusive --own-gpu-process llama-bench --own-gpu-process llama-server \
    --cpu-cores 2 --priority batch --max-wait 2h -- bash "${BASH_SOURCE[0]}" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE="${LLAMACPP_IMAGE:-ghcr.io/ggml-org/llama.cpp:full-cuda}"
MODELS_VOLUME="${CREW_CHIEF_MODELS_VOLUME:-crew-chief-models}"
HOST_NVIDIA_LIB="${HOST_NVIDIA_LIB:-/usr/lib64}"
CONTAINER_NVIDIA_LIB="/usr/local/nvidia/lib64"

# Default sweep: short and long prompt processing, generation, flash attention off/on.
DEFAULT_BENCH_ARGS=(-ngl 99 -p 512,4096 -n 128 -fa 0,1 -r 3)

models=()
bench_args=()
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--" ]]; then
        shift
        bench_args=("$@")
        break
    fi
    models+=("$1")
    shift
done
if [[ ${#models[@]} -eq 0 ]]; then
    echo "Usage: $0 <ollama-model> [...] [-- <llama-bench args>]" >&2
    exit 2
fi
if [[ ${#bench_args[@]} -eq 0 ]]; then
    bench_args=("${DEFAULT_BENCH_ARGS[@]}")
fi

# A warm or cold storage tier uses the same layout as the volume, so its
# models are benchmarked in place (see `crew-chief storage bench-due`).
volume_dir="${CREW_CHIEF_MODELS_DIR:-$(podman volume inspect "$MODELS_VOLUME" --format '{{.Mountpoint}}')/models}"

# Ollama stores each model as a manifest whose "model" layer is a GGUF blob.
blob_for() {
    local name="$1" repo tag manifest
    repo="${name%%:*}"
    tag="latest"
    [[ "$name" == *:* ]] && tag="${name#*:}"
    [[ "$repo" == */* ]] || repo="library/$repo"
    manifest="$volume_dir/manifests/registry.ollama.ai/$repo/$tag"
    if [[ ! -f "$manifest" ]]; then
        echo "Model not pulled in Ollama: $name" >&2
        return 1
    fi
    python3 - "$manifest" <<'EOF'
import json, sys
layers = json.load(open(sys.argv[1]))["layers"]
digest = next(l["digest"] for l in layers if l["mediaType"].endswith(".model"))
print(digest.replace(":", "-"))
EOF
}

# Same GPU wiring as scripts/run_ollama.sh: device nodes plus host driver libs.
gpu_args=(--security-opt label=disable --security-opt seccomp=unconfined)
for dev in /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools \
    /dev/nvidia-modeset /dev/nvidia-caps/*; do
    [[ -e "$dev" ]] && gpu_args+=(--device "$dev")
done
for lib in libcuda.so.1 libnvidia-ml.so.1 libnvidia-ptxjitcompiler.so.1 libnvidia-nvvm.so.4; do
    if [[ -e "$HOST_NVIDIA_LIB/$lib" ]]; then
        gpu_args+=(-v "$(readlink -f "$HOST_NVIDIA_LIB/$lib"):$CONTAINER_NVIDIA_LIB/$lib:ro")
    fi
done
for lib in "$HOST_NVIDIA_LIB"/libnvidia-gpucomp.so.*; do
    if [[ -f "$lib" && ! -L "$lib" ]]; then
        gpu_args+=(-v "$lib:$CONTAINER_NVIDIA_LIB/$(basename "$lib"):ro")
        break
    fi
done

# Other GPU work skews results and can leave too little VRAM to load a model.
busy="$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null || true)"
if [[ -n "$busy" ]]; then
    echo "Warning: other processes are using the GPU; results will be noisy:" >&2
    echo "$busy" | sed 's/^/  /' >&2
fi

failures=()
stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$REPO_DIR/results"
md_out="$REPO_DIR/results/llamacpp-bench-$stamp.md"
json_out="$REPO_DIR/results/llamacpp-bench-$stamp.jsonl"
{
    echo "# llama-bench $stamp"
    echo
    echo "- image: \`$IMAGE\`"
    echo "- GPU: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo unknown)"
    echo "- args: \`${bench_args[*]}\`"
} >"$md_out"

for model in "${models[@]}"; do
    if [[ "$model" == *.gguf ]]; then
        if [[ ! -f "$model" ]]; then
            echo "GGUF file not found: $model" >&2
            failures+=("$model")
            continue
        fi
        host_file="$(readlink -f "$model")"
        blob="$(basename "$model")"
        label="$blob"
    else
        blob="$(blob_for "$model")"
        # readlink: a model rotated to slower storage is a link in the volume.
        host_file="$(readlink -f "$volume_dir/blobs/$blob")"
        label="$model"
    fi
    echo
    echo "== $label ($blob)"
    run=(podman run --rm "${gpu_args[@]}"
        -e "LD_LIBRARY_PATH=$CONTAINER_NVIDIA_LIB:/usr/local/cuda/lib64"
        -v "$host_file:/models/$blob:ro"
        --entrypoint /app/llama-bench "$IMAGE"
        -m "/models/$blob" "${bench_args[@]}")
    printf '\n## %s\n\n' "$label" >>"$md_out"
    # Markdown table on stdout; the same rows as JSON lines on stderr (-oe),
    # mixed with load logs that are filtered out below.
    err_log="$(mktemp)"
    if ! "${run[@]}" -o md -oe jsonl 2>"$err_log" | tee -a "$md_out"; then
        echo "llama-bench failed for $label:" >&2
        grep -iE "error|fail|out of memory" "$err_log" | tail -5 >&2
        printf '\nFAILED: %s\n' "$(grep -iE "error" "$err_log" | tail -1)" >>"$md_out"
        failures+=("$label")
    fi
    python3 - "$label" "$err_log" >>"$json_out" <<'EOF'
import json, sys
model, path = sys.argv[1], sys.argv[2]
for line in open(path):
    if line.startswith("{"):
        row = json.loads(line)
        row["ollama_model"] = model
        print(json.dumps(row))
EOF
    rm -f "$err_log"
done

echo
echo "Saved: $md_out"
echo "       $json_out"
if [[ ${#failures[@]} -gt 0 ]]; then
    echo "Failed: ${failures[*]}" >&2
    exit 1
fi
