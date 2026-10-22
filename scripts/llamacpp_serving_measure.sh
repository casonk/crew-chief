#!/usr/bin/env bash
# Start llama-server for one model and configuration, record its GPU memory and
# generation rate, then stop it. Evidence for config/serving-policy.toml.
#
# Usage:
#   bash scripts/llamacpp_serving_measure.sh <ollama-model> <context> <kv-type>
#   bash scripts/llamacpp_serving_measure.sh qwen3:32b 32768 q8_0
#
# Run it on an idle GPU: stop other GPU services first.
# GPU memory is the increase over the baseline taken just before the server
# starts, so anything else on the GPU must stay put while it runs.

set -uo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 <ollama-model> <context> <kv-type>" >&2
    exit 2
fi
model="$1"
ctx="$2"
kv="$3"
IMAGE="${LLAMACPP_IMAGE:-ghcr.io/ggml-org/llama.cpp:full-cuda}"
MODELS_VOLUME="${CREW_CHIEF_MODELS_VOLUME:-crew-chief-models}"
HOST_NVIDIA_LIB="${HOST_NVIDIA_LIB:-/usr/lib64}"
PORT="${LLAMACPP_MEASURE_PORT:-8081}"
NAME="llamacpp-measure"

models_dir="$(podman volume inspect "$MODELS_VOLUME" --format '{{.Mountpoint}}')/models"
repo="${model%%:*}"
tag="latest"
[[ "$model" == *:* ]] && tag="${model#*:}"
[[ "$repo" == */* ]] || repo="library/$repo"
manifest="$models_dir/manifests/registry.ollama.ai/$repo/$tag"
if [[ ! -f "$manifest" ]]; then
    echo "Model not pulled in Ollama: $model" >&2
    exit 1
fi
blob="$(python3 -c "import json,sys
layers = json.load(open(sys.argv[1]))['layers']
print(next(l['digest'] for l in layers if l['mediaType'].endswith('.model')).replace(':', '-'))" "$manifest")"

# Same GPU wiring as scripts/run_ollama.sh.
gpu_args=(--security-opt label=disable --security-opt seccomp=unconfined)
for dev in /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools \
    /dev/nvidia-modeset /dev/nvidia-caps/*; do
    [[ -e "$dev" ]] && gpu_args+=(--device "$dev")
done
for lib in libcuda.so.1 libnvidia-ml.so.1 libnvidia-ptxjitcompiler.so.1 libnvidia-nvvm.so.4; do
    [[ -e "$HOST_NVIDIA_LIB/$lib" ]] &&
        gpu_args+=(-v "$(readlink -f "$HOST_NVIDIA_LIB/$lib"):/usr/local/nvidia/lib64/$lib:ro")
done
for lib in "$HOST_NVIDIA_LIB"/libnvidia-gpucomp.so.*; do
    if [[ -f "$lib" && ! -L "$lib" ]]; then
        gpu_args+=(-v "$lib:/usr/local/nvidia/lib64/$(basename "$lib"):ro")
        break
    fi
done

trap 'podman stop -t 5 "$NAME" >/dev/null 2>&1' EXIT
baseline="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)"
podman run -d --name "$NAME" --rm "${gpu_args[@]}" \
    -e LD_LIBRARY_PATH=/usr/local/nvidia/lib64:/usr/local/cuda/lib64 \
    -v "$(readlink -f "$models_dir/blobs/$blob"):/models/$blob:ro" -p "127.0.0.1:$PORT:8080" \
    --entrypoint /app/llama-server "$IMAGE" \
    -m "/models/$blob" --alias "$model" --jinja -ngl 99 -c "$ctx" -fa on \
    -ctk "$kv" -ctv "$kv" --host 0.0.0.0 --port 8080 >/dev/null

ready=0
for _ in $(seq 1 90); do
    if curl -sf "localhost:$PORT/health" >/dev/null; then
        ready=1
        break
    fi
    podman ps -q -f "name=$NAME" | grep -q . || break
    sleep 2
done
if [[ $ready -ne 1 ]]; then
    echo "RESULT model=$model ctx=$ctx kv=$kv FAILED_TO_START"
    podman logs "$NAME" 2>&1 | grep -iE "error|out of memory" | tail -3 >&2
    exit 1
fi

used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)"
rate="$(curl -s "localhost:$PORT/v1/chat/completions" -H 'content-type: application/json' \
    -d "{\"model\":\"$model\",\"max_tokens\":200,\"messages\":[{\"role\":\"user\",\"content\":\"Write a short paragraph about engines. /no_think\"}]}" |
    python3 -c "import json,sys; print(round(json.load(sys.stdin)['timings']['predicted_per_second'], 1))")"
echo "RESULT model=$model ctx=$ctx kv=$kv vram_mib=$((used - baseline)) gen_tok_s=$rate"
