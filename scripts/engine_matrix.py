#!/usr/bin/env python3
"""Compare engines and model files like for like: Ollama, llama.cpp on Ollama's
file, and llama.cpp on the llama.cpp-native file (config/gguf-sources.toml).

Every configuration gets the same raw-text prompt (no chat template, so thinking
and templates do not change the work), the same reply length, context size,
batch sizes and flash-attention setting, one warm-up and N timed runs. Rates
are the engines' own timings; the median is reported.

Usage (run with the GPU to itself, e.g. under an exclusive GPU lease):

    ecu run --gpu exclusive --own-gpu-process llama-server --cpu-cores 2 \
      --priority batch --max-wait 2h -- python3 scripts/engine_matrix.py
    ecu run --gpu exclusive --own-gpu-process llama-server --cpu-cores 2 \
      --priority batch --max-wait 2h -- python3 scripts/engine_matrix.py qwen3:14b gemma3:27b-it-qat --runs 5

Writes results/engine-matrix-<timestamp>.{md,json}.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from crew_chief import gguf_sources as gs  # noqa: E402
from crew_chief import model_storage as ms  # noqa: E402

OLLAMA = os.environ.get("CREW_CHIEF_URL", "http://localhost:11434").rstrip("/")
IMAGE = os.environ.get("LLAMACPP_IMAGE", "ghcr.io/ggml-org/llama.cpp:full-cuda")
HOST_NVIDIA_LIB = Path(os.environ.get("HOST_NVIDIA_LIB", "/usr/lib64"))
PORT = int(os.environ.get("LLAMACPP_MATRIX_PORT", "8082"))
CONTAINER = "llamacpp-matrix"
BATCH = 512  # Ollama 0.40 starts its runner with -b 512 -ub 512

# About 500 tokens of plain prose; the model continues it.
PROMPT = (
    "The history of bridge building is a history of materials and of the people who "
    "learned to trust them. The earliest crossings were fallen trees and flat stones laid "
    "across shallow streams, and for thousands of years the span of a bridge was limited "
    "by the length of the longest timber a community could move. Roman engineers changed "
    "that with the semicircular stone arch, which carries its load in compression and "
    "turns the weight of the road into a thrust that the piers and abutments can resist. "
    "Their aqueducts and road bridges stood for centuries because stone is strong when it "
    "is squeezed, and the arch keeps every voussoir squeezed. Medieval builders refined "
    "the pointed arch and added houses, chapels and shops to their bridges, so that a "
    "crossing such as old London Bridge became a street in its own right. The industrial "
    "revolution brought cast iron, which is strong in compression but brittle in tension, "
    "and then wrought iron and steel, which can be pulled as well as pushed. With steel "
    "came trusses, cantilevers and suspension bridges whose decks hang from cables slung "
    "between towers. Each new form demanded new mathematics: engineers learned to compute "
    "the forces in every member of a truss, to predict how a cable would sag under load, "
    "and, after several famous failures, to account for wind. The collapse of a slender "
    "suspension bridge in a moderate breeze taught a generation that a structure can be "
    "strong enough and still fail, because aerodynamic forces can feed energy into its "
    "motion until it tears itself apart. Modern designers test models in wind tunnels, "
    "shape decks like aircraft wings turned upside down, and add dampers that soak up "
    "vibration. Concrete, reinforced with steel bars and later prestressed with tensioned "
    "tendons, made long, elegant spans affordable, and computers now let engineers "
    "analyse thousands of load cases before a single pile is driven. Yet the questions a "
    "bridge builder asks have barely changed since the first log was dragged across a "
    "stream: how far must it reach, what must it carry, what will the ground beneath it "
    "bear, and what will the weather do to it over a hundred years? In the chapters that "
    "follow, we examine each of these questions in turn, beginning with"
)


def http_json(url: str, payload: dict | None = None, timeout: int = 600) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode() or "{}")


def gpu_used_mib() -> int:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(out.split()[0])


def wait_gpu_settled(timeout: float = 30.0) -> int:
    """Wait until GPU memory stops changing; return the settled value."""
    last, deadline = gpu_used_mib(), time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        now = gpu_used_mib()
        if abs(now - last) < 32:
            return now
        last = now
    return last


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def nonce_prompt(run: int) -> str:
    # A different first line per run defeats prompt caching on both engines.
    return f"Chapter {run + 1}.\n\n{PROMPT}"


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def ollama_unload_all() -> None:
    for model in http_json(f"{OLLAMA}/api/ps").get("models", []):
        http_json(f"{OLLAMA}/api/generate", {"model": model["name"], "keep_alive": 0})


def measure_ollama(model: str, args: argparse.Namespace) -> dict:
    ollama_unload_all()
    baseline = wait_gpu_settled()
    options = {
        "num_ctx": args.ctx,
        "num_predict": args.gen,
        "num_batch": BATCH,
        "temperature": 0,
        "seed": 1,
    }

    def generate(run: int) -> dict:
        payload = {"model": model, "prompt": nonce_prompt(run), "raw": True, "stream": False}
        return http_json(f"{OLLAMA}/api/generate", {**payload, "options": options})

    result: dict = {"config": "ollama", "file": "ollama"}
    try:
        warm = generate(-1)
        result["load_s"] = round(warm.get("load_duration", 0) / 1e9, 1)
        result["gpu_mib"] = wait_gpu_settled() - baseline
        loaded = next(m for m in http_json(f"{OLLAMA}/api/ps")["models"] if m["name"] == model)
        result["on_gpu_pct"] = round(100 * loaded.get("size_vram", 0) / max(loaded["size"], 1))
        gen, prompt, tokens, windows = [], [], [], []
        for run in range(args.runs):
            began = time.time()
            r = generate(run)
            windows.append((began, time.time()))
            gen.append(r["eval_count"] / (r["eval_duration"] / 1e9))
            prompt.append(r["prompt_eval_count"] / (r["prompt_eval_duration"] / 1e9))
            tokens.append(r["eval_count"])
        result.update(gen_tps=median(gen), prompt_tps=median(prompt), gen_tokens=min(tokens))
        result["prompt_tokens"] = r["prompt_eval_count"]
        result["windows"] = windows
    except (urllib.error.URLError, KeyError, StopIteration, OSError) as exc:
        result["error"] = _error_text(exc)
    finally:
        ollama_unload_all()
        wait_gpu_settled()
    return result


# ---------------------------------------------------------------------------
# llama.cpp (llama-server)
# ---------------------------------------------------------------------------


def gpu_podman_args() -> list[str]:
    """Same GPU wiring as scripts/run_ollama.sh."""
    args = ["--security-opt", "label=disable", "--security-opt", "seccomp=unconfined"]
    for dev in [
        "/dev/nvidia0",
        "/dev/nvidiactl",
        "/dev/nvidia-uvm",
        "/dev/nvidia-uvm-tools",
        "/dev/nvidia-modeset",
        *map(str, Path("/dev/nvidia-caps").glob("*")),
    ]:
        if Path(dev).exists():
            args += ["--device", dev]
    target = "/usr/local/nvidia/lib64"
    for lib in [
        "libcuda.so.1",
        "libnvidia-ml.so.1",
        "libnvidia-ptxjitcompiler.so.1",
        "libnvidia-nvvm.so.4",
    ]:
        path = HOST_NVIDIA_LIB / lib
        if path.exists():
            args += ["-v", f"{path.resolve()}:{target}/{lib}:ro"]
    for path in sorted(HOST_NVIDIA_LIB.glob("libnvidia-gpucomp.so.*")):
        if path.is_file() and not path.is_symlink():
            args += ["-v", f"{path}:{target}/{path.name}:ro"]
            break
    return args + ["-e", f"LD_LIBRARY_PATH={target}:/usr/local/cuda/lib64"]


def stop_server() -> None:
    subprocess.run(["podman", "rm", "-f", "-t", "2", CONTAINER], capture_output=True, check=False)


def server_logs() -> str:
    out = subprocess.run(["podman", "logs", CONTAINER], capture_output=True, text=True, check=False)
    lines = [ln for ln in (out.stdout + out.stderr).splitlines() if "error" in ln.lower()]
    # Prefer llama.cpp's own reason ("error loading model: ...") over the exit line.
    reasons = [
        ln.split("error loading model:", 1)[1] for ln in lines if "error loading model:" in ln
    ]
    if reasons:
        return "load failed: " + reasons[-1].strip()
    return lines[-1].strip() if lines else "server did not become ready"


def measure_llamacpp(label: str, model_file: Path, args: argparse.Namespace) -> dict:
    result: dict = {"config": "llama.cpp", "file": label}
    stop_server()
    baseline = wait_gpu_settled()
    command = [
        "podman", "run", "-d", "--name", CONTAINER, *gpu_podman_args(),
        "-v", f"{model_file.resolve()}:/models/model.gguf:ro",
        "-p", f"127.0.0.1:{PORT}:8080",
        "--entrypoint", "/app/llama-server", IMAGE,
        "-m", "/models/model.gguf", "--host", "0.0.0.0", "--port", "8080",
        "-ngl", "99", "-c", str(args.ctx), "-fa", "auto",
        "-b", str(BATCH), "-ub", str(BATCH), "-np", "1", "--no-webui",
    ]  # fmt: skip
    started = time.time()
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        deadline = started + 600
        while True:
            try:
                if http_json(f"http://127.0.0.1:{PORT}/health", timeout=5).get("status") == "ok":
                    break
            except (urllib.error.URLError, OSError, ValueError):
                pass
            running = subprocess.run(
                ["podman", "container", "exists", CONTAINER], check=False
            ).returncode
            state = subprocess.run(
                ["podman", "inspect", "-f", "{{.State.Running}}", CONTAINER],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if running != 0 or state != "true" or time.time() > deadline:
                raise RuntimeError(server_logs())
            time.sleep(1.0)
        result["load_s"] = round(time.time() - started, 1)
        result["gpu_mib"] = wait_gpu_settled() - baseline
        result["on_gpu_pct"] = 100

        def complete(run: int) -> dict:
            payload = {
                "prompt": nonce_prompt(run),
                "n_predict": args.gen,
                "temperature": 0,
                "seed": 1,
                "cache_prompt": False,
            }
            return http_json(f"http://127.0.0.1:{PORT}/completion", payload)

        complete(-1)
        gen, prompt, tokens, windows = [], [], [], []
        for run in range(args.runs):
            began = time.time()
            timings = complete(run)["timings"]
            windows.append((began, time.time()))
            gen.append(timings["predicted_per_second"])
            prompt.append(timings["prompt_per_second"])
            tokens.append(timings["predicted_n"])
        result.update(gen_tps=median(gen), prompt_tps=median(prompt), gen_tokens=min(tokens))
        result["prompt_tokens"] = timings["prompt_n"]
        result["windows"] = windows
    except (subprocess.CalledProcessError, RuntimeError, urllib.error.URLError, KeyError) as exc:
        result["error"] = _error_text(exc)
    finally:
        stop_server()
        wait_gpu_settled()
    return result


def mark_contention(rows: list[dict], log_path: str | None) -> None:
    """Count, per row, the timed runs that overlapped GPU contention.

    Under an ECU lease, ECU_CONTENTION_LOG lists every monitor sample where
    something outside the lease used the GPU.
    """
    if not log_path or not Path(log_path).is_file():
        return
    busy = []
    for line in Path(log_path).read_text().splitlines():
        record = json.loads(line)
        if "t" in record:
            names = sorted({b["name"].rsplit("/", 1)[-1] for b in record["busy"]})
            busy.append((record["t"], names))
    for row in rows:
        hits = set()
        names: set[str] = set()
        for index, (start, end) in enumerate(row.get("windows", [])):
            # The monitor samples every few seconds; widen the window to match.
            for t, who in busy:
                if start - 3 <= t <= end + 3:
                    hits.add(index)
                    names.update(who)
        row["contended_runs"] = len(hits)
        if hits:
            row["contended_by"] = sorted(names)


def _error_text(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return (exc.stderr or str(exc)).strip().splitlines()[-1]
    if isinstance(exc, urllib.error.HTTPError):
        try:
            return json.loads(exc.read().decode()).get("error", str(exc))
        except ValueError:
            return str(exc)
    return str(exc)[:200]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def render(rows: list[dict], args: argparse.Namespace, stamp: str, meta: dict) -> str:
    lines = [
        f"# Engine matrix {stamp}",
        "",
        f"- GPU: {meta['gpu']}; Ollama {meta['ollama']}; `{IMAGE}` build {meta['llamacpp']}",
        f"- Raw-text prompt of about 500 tokens (exact count per row in the JSON), "
        f"{args.gen}-token reply, "
        f"context {args.ctx}, batch {BATCH}/{BATCH}, flash attention auto, f16 KV cache, "
        f"temperature 0; 1 warm-up + {args.runs} runs, median.",
        "- `ollama file` = the blob Ollama pulled; `native` = the llama.cpp-format file "
        "from config/gguf-sources.toml (same weights and quantization).",
        "- GPU MiB = increase over the idle baseline once loaded; load includes "
        "starting llama-server.",
        "- Contention: "
        + (
            "checked against the GPU lease monitor; CONTENDED marks runs that "
            "overlapped other GPU work."
            if meta.get("contention_checked")
            else "not checked (run under a GPU lease to check)."
        ),
        "",
        "| Model | Engine | File | Gen tok/s | Prompt tok/s | Load s | GPU MiB | On GPU | Note |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        notes = [row["error"]] if row.get("error") else []
        if row.get("gen_tokens", args.gen) < args.gen:
            notes.append(f"stopped at {row['gen_tokens']} tokens")
        if row.get("contended_runs"):
            who = ", ".join(row.get("contended_by", []))
            notes.append(f"CONTENDED: {row['contended_runs']}/{args.runs} runs ({who})")
        note = "; ".join(notes)
        cells = [
            row["model"],
            row["config"],
            row["file"],
            row.get("gen_tps", "—"),
            row.get("prompt_tps", "—"),
            row.get("load_s", "—"),
            row.get("gpu_mib", "—"),
            f"{row['on_gpu_pct']}%" if "on_gpu_pct" in row else "—",
            note.replace("|", "/"),
        ]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="*", help="Ollama model names (default: all with sources).")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--gen", type=int, default=128, help="Reply length in tokens.")
    parser.add_argument("--ctx", type=int, default=8192, help="Context size for every engine.")
    parser.add_argument("--out", default=str(REPO_ROOT / "results"))
    args = parser.parse_args()

    sources = gs.load_sources()
    try:
        tiers = ms.load_tiers()
    except ms.StorageError:
        tiers = {"hot": ms.hot_dir()}
    hot = tiers["hot"]
    models = [ms.canonical(m) for m in args.models] or sorted(
        m for m, x in sources.items() if not x.draft
    )

    meta = {
        "gpu": subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "ollama": http_json(f"{OLLAMA}/api/version").get("version"),
        "llamacpp": "?",
    }
    rows: list[dict] = []
    for model in models:
        print(f"== {model}", file=sys.stderr, flush=True)
        first = len(rows)
        configs: list[tuple[str, Path | None]] = []
        manifest = ms.manifest_path(hot, model)
        if manifest.is_file():
            data = json.loads(manifest.read_text())
            weights = [x for x in data["layers"] if x["mediaType"].endswith(".model")]
            blob = hot / "blobs" / weights[0]["digest"].replace(":", "-") if weights else None
            rows.append({"model": model, **measure_ollama(model, args)})
            configs.append(("ollama file", blob))
        source = sources.get(model)
        if source:
            configs.append(("native", gs.find(source, tiers)))
        for label, path in configs:
            if path is None:
                rows.append({"model": model, "config": "llama.cpp", "file": label,
                             "error": "file not available"})  # fmt: skip
                continue
            rows.append({"model": model, **measure_llamacpp(label, path, args)})
        for row in rows[first:]:
            print(f"   {row['config']:9} {row['file']:11} gen {row.get('gen_tps')} "
                  f"{row.get('error', '')}", file=sys.stderr, flush=True)  # fmt: skip

    version = subprocess.run(
        ["podman", "run", "--rm", "--entrypoint", "/app/llama-server", IMAGE, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in (version.stdout + version.stderr).splitlines():
        if line.startswith("version:"):
            meta["llamacpp"] = line.split(":", 1)[1].strip()
    mark_contention(rows, os.environ.get("ECU_CONTENTION_LOG"))
    meta["contention_checked"] = bool(os.environ.get("ECU_CONTENTION_LOG"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    markdown = render(rows, args, stamp, meta)
    (out / f"engine-matrix-{stamp}.md").write_text(markdown, encoding="utf-8")
    settings = vars(args) | {"batch": BATCH}
    settings["out"] = out.name  # results can be committed without a host-specific path
    payload = {"meta": meta, "settings": settings, "rows": rows}
    (out / f"engine-matrix-{stamp}.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
