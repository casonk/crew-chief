"""crew_chief.serve — start the backend a model's serving-policy entry names.

``crew-chief serve <model>`` runs ``llama-server`` in a Podman container with the
entry's context window, KV-cache type and flash-attention setting, under an ECU
lease sized from its measured ``gpu_mib``, and stops it on exit. Models whose entry
names Ollama need nothing started: Ollama loads them on demand. Stdlib only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from crew_chief.code_launcher import LEASE_ENV
from crew_chief.serving_policy import ModelPolicy, canonical

IMAGE = os.environ.get("LLAMACPP_IMAGE", "ghcr.io/ggml-org/llama.cpp:full-cuda")
SWAP_IMAGE = os.environ.get("LLAMA_SWAP_IMAGE", "ghcr.io/mostlygeek/llama-swap:cuda")
SWAP_CONTAINER_NAME = "crew-chief-llama-swap"
MODELS_VOLUME = os.environ.get("CREW_CHIEF_MODELS_VOLUME", "crew-chief-models")
HOST_NVIDIA_LIB = Path(os.environ.get("HOST_NVIDIA_LIB", "/usr/lib64"))
CONTAINER_NAME = "crew-chief-llama-server"
CONTAINER_PORT = 8080
_NVIDIA_LIBS = (
    "libcuda.so.1",
    "libnvidia-ml.so.1",
    "libnvidia-ptxjitcompiler.so.1",
    "libnvidia-nvvm.so.4",
)


class ServeError(RuntimeError):
    """The model cannot be served as its policy entry says."""


def models_dir(run: Callable = subprocess.run) -> Path:
    """Where the Ollama volume keeps manifests and blobs."""
    try:
        out = run(
            ["podman", "volume", "inspect", MODELS_VOLUME, "--format", "{{.Mountpoint}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ServeError(f"cannot find the {MODELS_VOLUME} volume: {exc}") from exc
    return Path(out) / "models"


def blob_for(model: str, root: Path) -> Path:
    """The weights file Ollama pulled for ``model``, following storage-tier links."""
    name = canonical(model)
    repo, _, tag = name.partition(":")
    if "/" not in repo:
        repo = f"library/{repo}"
    manifest = root / "manifests" / "registry.ollama.ai" / repo / (tag or "latest")
    try:
        layers = json.loads(manifest.read_text(encoding="utf-8"))["layers"]
        digest = next(x["digest"] for x in layers if x["mediaType"].endswith(".model"))
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        raise ServeError(f"{model} is not pulled in Ollama ({manifest})") from exc
    blob = (root / "blobs" / digest.replace(":", "-")).resolve()
    if not blob.is_file():
        raise ServeError(f"the weights for {model} are missing: {blob}")
    return blob


def gpu_args(lib_dir: Path = HOST_NVIDIA_LIB) -> list[str]:
    """Device and driver-library wiring, the same as scripts/run_ollama.sh."""
    args = ["--security-opt", "label=disable", "--security-opt", "seccomp=unconfined"]
    devices = [
        "/dev/nvidia0",
        "/dev/nvidiactl",
        "/dev/nvidia-uvm",
        "/dev/nvidia-uvm-tools",
        "/dev/nvidia-modeset",
        *sorted(str(p) for p in Path("/dev/nvidia-caps").glob("*")),
    ]
    for dev in devices:
        if os.path.exists(dev):
            args += ["--device", dev]
    for lib in _NVIDIA_LIBS:
        path = lib_dir / lib
        if path.exists():
            args += ["-v", f"{path.resolve()}:/usr/local/nvidia/lib64/{lib}:ro"]
    for lib in sorted(lib_dir.glob("libnvidia-gpucomp.so.*")):
        if lib.is_file() and not lib.is_symlink():
            args += ["-v", f"{lib}:/usr/local/nvidia/lib64/{lib.name}:ro"]
            break
    return args


def server_port(base_url: str) -> int:
    return urlparse(base_url).port or 8081


def podman_argv(
    model: str,
    entry: ModelPolicy,
    blob: Path,
    port: int,
    gpu: list[str] | None = None,
    draft: Path | None = None,
) -> list[str]:
    """The ``podman run`` command that serves ``model`` as its entry says."""
    if not entry.context:
        raise ServeError(f"{model}: the policy entry has no context window")
    return [
        "podman", "run", "--rm", "--name", CONTAINER_NAME,
        *(gpu if gpu is not None else gpu_args()),
        "-e", "LD_LIBRARY_PATH=/usr/local/nvidia/lib64:/usr/local/cuda/lib64",
        "-v", f"{blob}:/models/{blob.name}:ro", *draft_mount(draft),
        "-p", f"127.0.0.1:{port}:{CONTAINER_PORT}",
        "--entrypoint", "/app/llama-server", IMAGE,
        *server_flags(model, entry, blob.name, draft), "--host", "0.0.0.0",
        "--port", str(CONTAINER_PORT),
    ]  # fmt: skip


def draft_mount(draft: Path | None) -> list[str]:
    return ["-v", f"{draft}:/models/{draft.name}:ro"] if draft else []


def server_flags(
    model: str, entry: ModelPolicy, blob_name: str, draft: Path | None = None
) -> list[str]:
    """The llama-server flags a policy entry sets, without host and port."""
    flags = ["-fa", "on" if entry.flash_attention else "off"]
    if entry.speculative:
        flags += ["--spec-type", entry.speculative]
    if draft:
        flags += [
            "-md", f"/models/{draft.name}", "-ngld", "99", "--spec-type", "draft-simple",
            "--spec-draft-n-max", str(entry.draft_tokens), "--spec-draft-n-min", "1",
        ]  # fmt: skip
    return [
        "-m", f"/models/{blob_name}", "--alias", model, "--jinja", "-ngl", "99",
        "-c", str(entry.context), *flags, "-ctk", entry.kv_cache, "-ctv", entry.kv_cache,
    ]  # fmt: skip


def swap_config(models: list[tuple[str, ModelPolicy, Path, Path | None]], ttl: int = 300) -> str:
    """A llama-swap config that serves each model with its policy settings.

    llama-swap starts one llama-server per request's model, stops the previous
    one, and unloads an idle model after ``ttl`` seconds. Values are JSON strings,
    which YAML accepts, so no YAML library is needed.
    """
    lines = ["healthCheckTimeout: 500", "models:"]
    for model, entry, blob, draft in models:
        if not entry.context:
            raise ServeError(f"{model}: the policy entry has no context window")
        cmd = " ".join(
            [
                "/app/llama-server",
                "--port",
                "${PORT}",
                *server_flags(model, entry, blob.name, draft),
            ]
        )
        lines += [f"  {json.dumps(model)}:", f"    ttl: {ttl}", f"    cmd: {json.dumps(cmd)}"]
    return "\n".join(lines) + "\n"


def swap_argv(
    models: list[tuple[str, ModelPolicy, Path, Path | None]],
    config: Path,
    port: int,
    gpu: list[str] | None = None,
) -> list[str]:
    """The ``podman run`` command for llama-swap in front of ``models``."""
    mounts: list[str] = []
    for _, _, blob, draft in models:
        mounts += ["-v", f"{blob}:/models/{blob.name}:ro", *draft_mount(draft)]
    return [
        "podman", "run", "--rm", "--name", SWAP_CONTAINER_NAME,
        *(gpu if gpu is not None else gpu_args()),
        "-e", "LD_LIBRARY_PATH=/usr/local/nvidia/lib64:/usr/local/cuda/lib64",
        *mounts, "-v", f"{config}:/config/config.yaml:ro",
        "-p", f"127.0.0.1:{port}:{CONTAINER_PORT}",
        SWAP_IMAGE, "-config", "/config/config.yaml", "-listen", f":{CONTAINER_PORT}",
    ]  # fmt: skip


HEADROOM_MIB = int(os.environ.get("CREW_CHIEF_SERVE_HEADROOM_MIB", "1024"))


def gpu_total_mib(run: Callable = subprocess.run) -> int | None:
    try:
        out = run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return int(out.splitlines()[0])
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        return None


def lease_size(gpu_mib: int, total_mib: int | None) -> list[str]:
    """The lease size arguments: measured memory plus load-time headroom.

    The policy records memory once the model is loaded; loading allocates compute
    buffers on top, which fails when a small neighbour holds the margin. A model
    that does not fit with headroom takes the whole GPU instead.
    """
    if total_mib is None or gpu_mib + HEADROOM_MIB > total_mib:
        return ["--gpu", "exclusive"]
    return ["--gpu-mib", str(gpu_mib + HEADROOM_MIB)]


def lease_command(
    model: str,
    argv: list[str],
    gpu_mib: int,
    *,
    total_mib: int | None = None,
    which=shutil.which,
    environ=None,
) -> list[str] | None:
    """``ecu run`` around ``argv`` for a measured model, or None to run it bare."""
    env = os.environ if environ is None else environ
    if env.get(LEASE_ENV) or env.get("CREW_CHIEF_NO_LEASE"):
        return None
    ecu = which("ecu")
    if ecu is None:
        return None
    return [
        ecu, "run", *lease_size(gpu_mib, total_mib),
        "--priority", "interactive", "--own-gpu-process", "llama-server", "--", *argv,
    ]  # fmt: skip


def plan(model: str, entry: ModelPolicy | None, base_url: str, run: Callable = subprocess.run):
    """The command that serves ``model``, or None when its backend needs none."""
    if entry is None:
        raise ServeError(f"{model} is not in the serving policy; add an entry first")
    if entry.status == "retired":
        raise ServeError(f"{model} is retired; restore it with `crew-chief storage restore`")
    if entry.backend != "llamacpp":
        return None
    return podman_argv(
        model, entry, blob_for(model, models_dir(run)), server_port(base_url),
        draft=draft_for(entry),
    )  # fmt: skip


def draft_for(entry: ModelPolicy) -> Path | None:
    """The downloaded draft model file an entry names, or None when it has none."""
    if not entry.draft:
        return None
    from crew_chief import gguf_sources as gs
    from crew_chief import model_storage as ms

    try:
        source = gs.load_sources().get(canonical(entry.draft))
        if source is None:
            raise ServeError(f"{entry.name}: draft {entry.draft} is not in gguf-sources.toml")
        try:
            tiers = ms.load_tiers()
        except ms.StorageError:
            tiers = None
        path = gs.find(source, tiers)
    except gs.SourceError as exc:
        raise ServeError(str(exc)) from exc
    if path is None:
        raise ServeError(
            f"{entry.name}: draft file for {entry.draft} is not downloaded; "
            f"run `crew-chief gguf fetch {entry.draft}`"
        )
    return path


def plan_swap(
    names: list[str], policy, run: Callable = subprocess.run
) -> list[tuple[str, ModelPolicy, Path, Path | None]]:
    """Each model with its policy entry, weights file and draft file, ready for ``swap_config``."""
    entries = []
    for name in names:
        entry = policy.get(name)
        if entry is None:
            raise ServeError(f"{name} is not in the serving policy; add an entry first")
        if entry.status == "retired":
            raise ServeError(f"{name} is retired; restore it with `crew-chief storage restore`")
        entries.append((name, entry))
    root = models_dir(run)
    return [(name, entry, blob_for(name, root), draft_for(entry)) for name, entry in entries]


def serve(command: list[str], model: str, gpu_mib: int | None, leased: bool) -> None:
    """Replace this process with the server, under a lease when one applies."""
    wrapped = (
        lease_command(model, command, gpu_mib, total_mib=gpu_total_mib())
        if leased and gpu_mib
        else None
    )
    sys.stdout.flush()
    if wrapped is not None:
        print(f"crew-chief: serving {model} under an ECU lease ({gpu_mib} MiB)", file=sys.stderr)
        os.execvpe(wrapped[0], wrapped, {**os.environ, LEASE_ENV: "1"})
    os.execvp(command[0], command)
