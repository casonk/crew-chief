#!/usr/bin/env bash
# scripts/run_ollama.sh — run the crew-chief Ollama container in the foreground.
#
# Intended as the ExecStart for the crew-chief-ollama.service user unit so that
# systemd manages the container lifecycle directly (restart, journal, linger).
#
# --replace stops any pre-existing detached container with the same name so the
# service can take ownership cleanly on start or restart.
set -euo pipefail

CONTAINER_NAME="${CREW_CHIEF_CONTAINER:-crew-chief}"
IMAGE_NAME="${CREW_CHIEF_IMAGE:-crew-chief:latest}"
PORT="${CREW_CHIEF_PORT:-11434}"
MODELS_VOLUME="${CREW_CHIEF_MODELS_VOLUME:-crew-chief-models}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Build the image if it does not already exist.
if ! podman image exists "$IMAGE_NAME" 2>/dev/null; then
    echo "Image $IMAGE_NAME not found — building from $REPO_ROOT/Containerfile ..."
    podman build -t "$IMAGE_NAME" "$REPO_ROOT"
fi

# Create the named volume for persisted model weights if missing.
if ! podman volume exists "$MODELS_VOLUME" 2>/dev/null; then
    podman volume create "$MODELS_VOLUME"
fi

# ── NVIDIA GPU passthrough ────────────────────────────────────────────────
# Build --device flags for every NVIDIA device node on the host.
# Ollama bundles CUDA 12/13 compute libraries; it needs the device nodes
# forwarded plus the host driver libraries for GPU discovery (libnvidia-ml
# is not bundled in the image).
GPU_DEVICES=()
for dev in \
    /dev/nvidia0 \
    /dev/nvidiactl \
    /dev/nvidia-uvm \
    /dev/nvidia-uvm-tools \
    /dev/nvidia-modeset; do
    [[ -e "$dev" ]] && GPU_DEVICES+=(--device "$dev")
done
# nvidia-caps devices (required by CUDA 11.8+ / driver 510+)
for cap in /dev/nvidia-caps/*; do
    [[ -e "$cap" ]] && GPU_DEVICES+=(--device "$cap")
done

# Mount the host NVIDIA driver libraries into the path the Ubuntu Ollama
# image exports via LD_LIBRARY_PATH (/usr/local/nvidia/lib64).
# libcuda.so + libnvidia-ml.so are needed for GPU enumeration; without them
# Ollama falls back to CPU even when the device nodes are present.
GPU_LIB_MOUNTS=()
if (( ${#GPU_DEVICES[@]} > 0 )); then
    HOST_NVIDIA_LIB="${HOST_NVIDIA_LIB:-/usr/lib64}"
    CONTAINER_NVIDIA_LIB="/usr/local/nvidia/lib64"
    # Resolve symlinks to real versioned files so the container doesn't get
    # dangling soname links (e.g. libcuda.so.1 → libcuda.so.580.142 which
    # doesn't exist inside the image).
    for lib in \
        libcuda.so.1 \
        libnvidia-ml.so.1 \
        libnvidia-allocator.so.1; do
        host_path="${HOST_NVIDIA_LIB}/${lib}"
        real_path="$(readlink -f "${host_path}" 2>/dev/null || true)"
        if [[ -f "$real_path" ]]; then
            GPU_LIB_MOUNTS+=(-v "${real_path}:${CONTAINER_NVIDIA_LIB}/${lib}:ro")
        fi
    done
    echo "GPU passthrough: ${GPU_DEVICES[*]}"
    echo "GPU lib mounts:  ${GPU_LIB_MOUNTS[*]:-none}"
else
    echo "No NVIDIA devices found — running on CPU."
fi

# Run in the foreground (no -d); systemd owns the process lifetime.
# --replace stops any existing container of the same name before starting.
# --security-opt label=disable is required on SELinux Enforcing hosts to allow
# the container to access the NVIDIA device nodes passed via --device; without
# it the devices appear as '??????????' inside the container and GPU discovery
# fails even though the nodes are present.
exec podman run --rm --replace \
    --name "$CONTAINER_NAME" \
    -p "${PORT}:11434" \
    -v "${MODELS_VOLUME}:/root/.ollama" \
    --security-opt label=disable \
    "${GPU_DEVICES[@]}" \
    "${GPU_LIB_MOUNTS[@]}" \
    "$IMAGE_NAME"
