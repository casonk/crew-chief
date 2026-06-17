#!/usr/bin/env python3
"""
Ollama inference benchmark — TTFT, tokens/sec, and VRAM delta per model.

Usage
-----
    # All local models, all prompts
    python3 scripts/benchmark.py

    # Specific models
    python3 scripts/benchmark.py qwen3:14b qwen3:32b llama3.2:latest

    # Specific prompt categories
    python3 scripts/benchmark.py --prompts latency reasoning

    # Average over multiple runs
    python3 scripts/benchmark.py --runs 3

    # Save JSON output
    python3 scripts/benchmark.py --json results/bench-$(date +%Y%m%d).json

    # Custom base URL
    python3 scripts/benchmark.py --base-url http://localhost:11434
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass

BASE_URL = "http://localhost:11434"

# Standard prompt suite — add task-specific prompts to PROMPTS and pass via --prompts
PROMPTS: dict[str, str] = {
    "latency": "Reply with exactly one word: pong",
    "reasoning": (
        "Name the eight planets of our solar system in order from the Sun, "
        "one per line, with no extra text."
    ),
    "codegen": (
        "Write a Python function called fibonacci(n) that returns the nth Fibonacci "
        "number using memoization. Include only the function, no explanation."
    ),
    "summarise": (
        "Summarise the following in one sentence: "
        "The quick brown fox jumps over the lazy dog near the river bank "
        "where the willows grow tall in the summer heat."
    ),
}


@dataclass
class BenchmarkResult:
    model: str
    prompt_name: str
    ttft_ms: float
    tokens_per_sec: float
    total_tokens: int
    total_time_ms: float
    vram_delta_mb: int  # -1 when nvidia-smi unavailable
    error: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_json(path: str, payload: dict, timeout: int = 180) -> dict:
    import urllib.request

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _list_local_models() -> list[str]:
    try:
        resp = _post_json("/api/tags", {})
        return [m["name"] for m in resp.get("models", [])]
    except Exception as exc:
        print(f"Could not list local models: {exc}", file=sys.stderr)
        return []


def _vram_used_mb() -> int:
    """Return current GPU VRAM used in MB, or -1 if nvidia-smi is unavailable."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
        return int(out.strip().splitlines()[0])
    except Exception:
        return -1


def _measure_ttft(model: str, prompt: str, timeout: int = 180) -> float:
    """Return time-to-first-token in milliseconds via the streaming endpoint."""
    import http.client
    import urllib.parse

    payload = json.dumps({"model": model, "prompt": prompt, "stream": True}).encode()
    parsed = urllib.parse.urlparse(BASE_URL)
    conn = http.client.HTTPConnection(parsed.netloc, timeout=timeout)
    t0 = time.perf_counter()
    try:
        conn.request(
            "POST",
            "/api/generate",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        for raw_line in resp:
            line = raw_line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            if chunk.get("response"):
                return (time.perf_counter() - t0) * 1000
        return (time.perf_counter() - t0) * 1000
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Core benchmark
# ---------------------------------------------------------------------------


def _warmup(model: str) -> None:
    """Send one short request to ensure the model is loaded before timing begins."""
    import contextlib

    with contextlib.suppress(Exception):
        _post_json("/api/generate", {"model": model, "prompt": "hi", "stream": False}, timeout=120)


def run_benchmark(
    model: str,
    prompt_name: str,
    prompt: str,
    runs: int = 1,
) -> BenchmarkResult:
    ttft_samples: list[float] = []
    tps_samples: list[float] = []
    token_counts: list[int] = []
    total_times: list[float] = []
    vram_deltas: list[int] = []

    for _ in range(runs):
        # --- TTFT via streaming ---
        try:
            ttft = _measure_ttft(model, prompt)
        except Exception as exc:
            return BenchmarkResult(
                model=model,
                prompt_name=prompt_name,
                ttft_ms=0,
                tokens_per_sec=0,
                total_tokens=0,
                total_time_ms=0,
                vram_delta_mb=-1,
                error=str(exc),
            )
        ttft_samples.append(ttft)

        # --- Tokens/sec + VRAM via non-streaming ---
        vram_before = _vram_used_mb()
        t0 = time.perf_counter()
        try:
            resp = _post_json(
                "/api/generate",
                {"model": model, "prompt": prompt, "stream": False},
            )
        except Exception as exc:
            return BenchmarkResult(
                model=model,
                prompt_name=prompt_name,
                ttft_ms=round(sum(ttft_samples) / len(ttft_samples), 1),
                tokens_per_sec=0,
                total_tokens=0,
                total_time_ms=0,
                vram_delta_mb=-1,
                error=str(exc),
            )
        wall_ms = (time.perf_counter() - t0) * 1000
        vram_after = _vram_used_mb()

        eval_count: int = resp.get("eval_count", 0)
        eval_duration_ns: int = resp.get("eval_duration", 1) or 1
        tps = eval_count / (eval_duration_ns / 1e9)

        tps_samples.append(tps)
        token_counts.append(eval_count)
        total_times.append(wall_ms)
        if vram_before >= 0 and vram_after >= 0:
            vram_deltas.append(vram_after - vram_before)

    def _avg(lst: list) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return BenchmarkResult(
        model=model,
        prompt_name=prompt_name,
        ttft_ms=round(_avg(ttft_samples), 1),
        tokens_per_sec=round(_avg(tps_samples), 1),
        total_tokens=int(_avg(token_counts)),
        total_time_ms=round(_avg(total_times), 1),
        vram_delta_mb=int(_avg(vram_deltas)) if vram_deltas else -1,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _fmt_table(results: list[BenchmarkResult]) -> str:
    col_model = max(len(r.model) for r in results) + 2
    col_model = max(col_model, 20)
    header = (
        f"{'Model':<{col_model}} {'Prompt':<12} {'TTFT ms':>8} "
        f"{'Tok/s':>7} {'Tokens':>7} {'Total ms':>10} {'VRAM ΔMB':>10}"
    )
    sep = "-" * len(header)
    rows = [header, sep]
    for r in results:
        if r.error:
            rows.append(f"{r.model:<{col_model}} {r.prompt_name:<12}  ERROR: {r.error}")
            continue
        vram_str = f"+{r.vram_delta_mb}" if r.vram_delta_mb >= 0 else "n/a"
        rows.append(
            f"{r.model:<{col_model}} {r.prompt_name:<12} {r.ttft_ms:>8.1f} "
            f"{r.tokens_per_sec:>7.1f} {r.total_tokens:>7} "
            f"{r.total_time_ms:>10.1f} {vram_str:>10}"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    global BASE_URL

    parser = argparse.ArgumentParser(
        description="Benchmark Ollama models: TTFT, tokens/sec, VRAM delta.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "models",
        nargs="*",
        help="Models to benchmark (default: all local models from /api/tags)",
    )
    parser.add_argument(
        "--prompts",
        nargs="+",
        choices=list(PROMPTS),
        default=list(PROMPTS),
        metavar="PROMPT",
        help=f"Prompt categories to run. Choices: {', '.join(PROMPTS)}. Default: all.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per model/prompt to average (default: 1).",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Write results to this JSON file in addition to stdout.",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help=f"Ollama API base URL (default: {BASE_URL}).",
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        default=False,
        help="Skip the warm-up request per model (first TTFT will include model load time).",
    )
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")

    models = args.models or _list_local_models()
    if not models:
        print("No models found. Is Ollama running?", file=sys.stderr)
        sys.exit(1)

    total_ops = len(models) * len(args.prompts) * args.runs
    print(
        f"Benchmarking {len(models)} model(s) × {len(args.prompts)} prompt(s)"
        f" × {args.runs} run(s) = {total_ops} inference(s)"
    )
    print(f"Prompts: {', '.join(args.prompts)}")
    print()

    results: list[BenchmarkResult] = []
    for model in models:
        if not args.no_warmup:
            print(f"  {model}  [warmup] ...", end=" ", flush=True)
            _warmup(model)
            print("done")
        for prompt_name in args.prompts:
            prompt = PROMPTS[prompt_name]
            print(f"  {model}  [{prompt_name}] ...", end=" ", flush=True)
            result = run_benchmark(model, prompt_name, prompt, runs=args.runs)
            results.append(result)
            if result.error:
                print(f"ERROR: {result.error}")
            else:
                print(f"{result.tokens_per_sec:.1f} tok/s  TTFT {result.ttft_ms:.0f}ms")

    print()
    print(_fmt_table(results))

    if args.json:
        import pathlib

        out = pathlib.Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([asdict(r) for r in results], indent=2))
        print(f"\nResults saved → {out}")


if __name__ == "__main__":
    main()
