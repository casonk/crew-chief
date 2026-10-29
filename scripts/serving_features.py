#!/usr/bin/env python3
"""Measure llama-server's serving features one at a time on an idle GPU.

Experiments (each starts a fresh llama-server container, so every number has
its own GPU-memory baseline):

  kv        KV-cache type f16 / q8_0 / q4_0: GPU memory and generation rate
  cache     prompt-cache reuse across agent turns: a long shared prefix plus a
            new suffix per turn, with and without cache_prompt
  slots     parallel slots: four concurrent requests on -np 1 and -np 4
  spec      speculative decoding: a small draft model of the same family

Every request is a raw-text completion at temperature 0, so chat templates and
thinking do not change the work. Rates are llama-server's own timings.

Usage (run with the GPU to itself, e.g. under an exclusive GPU lease):

    ecu run --gpu exclusive --own-gpu-process llama-server --cpu-cores 2 \
      --priority batch --max-wait 2h -- python3 scripts/serving_features.py
    ecu run --gpu exclusive --own-gpu-process llama-server --cpu-cores 2 \
      --priority batch --max-wait 2h -- python3 scripts/serving_features.py kv cache

Writes results/serving-features-<timestamp>.{md,json}.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "src"))

import engine_matrix as em  # noqa: E402

from crew_chief import serve  # noqa: E402

PORT = 8083
CONTAINER = "llamacpp-features"
EXPERIMENTS = ("kv", "cache", "slots", "spec")
STRUCTURED = (
    'Convert each line to JSON with the keys "item", "quantity" and "unit".\n'
    "2 cups flour -> "
    '{"item": "flour", "quantity": 2, "unit": "cups"}\n'
    "3 eggs -> "
    '{"item": "eggs", "quantity": 3, "unit": "each"}\n'
    "1 tsp salt -> "
    '{"item": "salt", "quantity": 1, "unit": "tsp"}\n'
    "250 g butter -> "
    '{"item": "butter", "quantity": 250, "unit": "g"}\n'
    "4 tbsp sugar -> "
    '{"item": "sugar", "quantity": 4, "unit": "tbsp"}\n'
    "2 cloves garlic -> "
    '{"item": "garlic", "quantity": 2, "unit": "cloves"}\n'
    "500 ml milk -> "
    '{"item": "milk", "quantity": 500, "unit": "ml"}\n'
    "6 oz cheddar -> "
)


@dataclass
class Config:
    name: str
    args: list[str] = field(default_factory=list)
    draft: Path | None = None


class Server:
    """One llama-server container for one configuration."""

    def __init__(self, model: Path, config: Config, ctx: int, slots: int = 1):
        self.model, self.config, self.ctx, self.slots = model, config, ctx, slots
        self.url = f"http://127.0.0.1:{PORT}"
        self.gpu_mib = 0

    def __enter__(self) -> Server:
        em.CONTAINER = CONTAINER
        em.stop_server()
        baseline = em.wait_gpu_settled()
        mounts = ["-v", f"{self.model.resolve()}:/models/model.gguf:ro"]
        args = ["-m", "/models/model.gguf"]
        if self.config.draft:
            mounts += ["-v", f"{self.config.draft.resolve()}:/models/draft.gguf:ro"]
            args += ["-md", "/models/draft.gguf", "-ngld", "99"]
        command = [
            "podman", "run", "-d", "--name", CONTAINER, *em.gpu_podman_args(), *mounts,
            "-p", f"127.0.0.1:{PORT}:8080", "--entrypoint", "/app/llama-server", em.IMAGE,
            *args, "--host", "0.0.0.0", "--port", "8080", "-ngl", "99",
            "-c", str(self.ctx * self.slots), "-np", str(self.slots), "-fa", "on",
            "-b", str(em.BATCH), "-ub", str(em.BATCH), "--no-webui", *self.config.args,
        ]  # fmt: skip
        subprocess.run(command, capture_output=True, text=True, check=True)
        deadline = time.time() + 600
        while True:
            try:
                if em.http_json(f"{self.url}/health", timeout=5).get("status") == "ok":
                    break
            except (urllib.error.URLError, OSError, ValueError):
                pass
            state = subprocess.run(
                ["podman", "inspect", "-f", "{{.State.Running}}", CONTAINER],
                capture_output=True, text=True, check=False,
            ).stdout.strip()  # fmt: skip
            if state != "true" or time.time() > deadline:
                raise RuntimeError(em.server_logs())
            time.sleep(1.0)
        self.gpu_mib = em.wait_gpu_settled() - baseline
        return self

    def __exit__(self, *exc: object) -> None:
        em.stop_server()
        em.wait_gpu_settled()

    def complete(self, prompt: str, n: int, cache: bool = False) -> dict:
        payload = {
            "prompt": prompt, "n_predict": n, "temperature": 0, "seed": 1, "cache_prompt": cache,
        }  # fmt: skip
        return em.http_json(f"{self.url}/completion", payload)


def nonce(run: int, text: str) -> str:
    # A different first line per run defeats prompt caching.
    return f"Chapter {run + 1}.\n\n{text}"


def tps(rows: list[float]) -> float | None:
    return em.median(rows)


def run_kv(model: Path, args: argparse.Namespace) -> list[dict]:
    rows = []
    for kv in ("f16", "q8_0", "q4_0"):
        row: dict = {"experiment": "kv", "config": f"kv {kv}", "ctx": args.ctx}
        try:
            with Server(model, Config(kv, ["-ctk", kv, "-ctv", kv]), args.ctx) as server:
                row["gpu_mib"] = server.gpu_mib
                server.complete(nonce(-1, em.PROMPT), args.gen)
                runs = [server.complete(nonce(i, em.PROMPT), args.gen)["timings"]
                        for i in range(args.runs)]  # fmt: skip
                row["gen_tps"] = tps([t["predicted_per_second"] for t in runs])
                row["prompt_tps"] = tps([t["prompt_per_second"] for t in runs])
        except (subprocess.CalledProcessError, RuntimeError, urllib.error.URLError) as exc:
            row["error"] = em._error_text(exc)
        rows.append(row)
        print(f"   {row['config']:12} {row.get('gpu_mib')} MiB gen {row.get('gen_tps')}",
              file=sys.stderr, flush=True)  # fmt: skip
    return rows


def agent_prefix(tokens_hint: int) -> str:
    # About 520 tokens per copy of the prompt; each copy gets its own heading so the
    # prefix is not one repeated block.
    return "\n\n".join(f"Section {i + 1}.\n{em.PROMPT}" for i in range(tokens_hint // 520))


def run_cache(model: Path, args: argparse.Namespace) -> list[dict]:
    rows = []
    prefix = agent_prefix(args.prefix)
    for cache in (False, True):
        row: dict = {"experiment": "cache", "config": f"cache_prompt {'on' if cache else 'off'}"}
        try:
            with Server(model, Config("cache"), args.prefix + 2048) as server:
                row["gpu_mib"] = server.gpu_mib
                server.complete("warm up", 4)
                turns = []
                for turn in range(4):
                    began = time.time()
                    timings = server.complete(
                        f"{prefix}\n\nTurn {turn + 1}: summarise the section in one line:",
                        32, cache=cache,
                    )["timings"]  # fmt: skip
                    turns.append({
                        "prompt_n": timings["prompt_n"],
                        "seconds": round(time.time() - began, 2),
                    })  # fmt: skip
                row["turns"] = turns
                row["first_s"] = turns[0]["seconds"]
                row["later_s"] = round(statistics.mean(t["seconds"] for t in turns[1:]), 2)
                row["later_prompt_n"] = round(statistics.mean(t["prompt_n"] for t in turns[1:]))
        except (subprocess.CalledProcessError, RuntimeError, urllib.error.URLError) as exc:
            row["error"] = em._error_text(exc)
        rows.append(row)
        print(f"   {row['config']:20} first {row.get('first_s')} s, later {row.get('later_s')} s "
              f"({row.get('later_prompt_n')} tokens evaluated)", file=sys.stderr, flush=True)  # fmt: skip
    return rows


def run_slots(model: Path, args: argparse.Namespace) -> list[dict]:
    rows = []
    for slots in (1, 4):
        row: dict = {"experiment": "slots", "config": f"-np {slots}", "slots": slots}
        try:
            with Server(model, Config(f"np{slots}"), args.ctx, slots=slots) as server:
                row["gpu_mib"] = server.gpu_mib
                server.complete(nonce(-1, em.PROMPT), 8)
                prompts = [nonce(i, em.PROMPT) for i in range(4)]
                began = time.time()
                with ThreadPoolExecutor(max_workers=4) as pool:
                    out = list(pool.map(lambda p: server.complete(p, args.gen), prompts))
                wall = time.time() - began
                generated = sum(o["timings"]["predicted_n"] for o in out)
                row["wall_s"] = round(wall, 2)
                row["aggregate_tps"] = round(generated / wall, 1)
                row["per_request_tps"] = tps([o["timings"]["predicted_per_second"] for o in out])
        except (subprocess.CalledProcessError, RuntimeError, urllib.error.URLError) as exc:
            row["error"] = em._error_text(exc)
        rows.append(row)
        print(f"   {row['config']:8} aggregate {row.get('aggregate_tps')} tok/s, "
              f"{row.get('gpu_mib')} MiB", file=sys.stderr, flush=True)  # fmt: skip
    return rows


def run_spec(model: Path, draft: Path, args: argparse.Namespace) -> list[dict]:
    rows = []
    configs = [Config("no draft"), Config("ngram-mod", ["--spec-type", "ngram-mod"])] + [
        Config(
            f"draft max {n}",
            [
                "--spec-type",
                "draft-simple",
                "--spec-draft-n-max",
                str(n),
                "--spec-draft-n-min",
                "1",
            ],
            draft,
        )
        for n in (8, 16)
    ]
    for config in configs:
        for label, text in (("prose", em.PROMPT), ("structured", STRUCTURED)):
            row: dict = {"experiment": "spec", "config": config.name, "prompt": label}
            try:
                with Server(model, config, args.ctx) as server:
                    row["gpu_mib"] = server.gpu_mib
                    server.complete(nonce(-1, text), 16)
                    runs = [server.complete(nonce(i, text), args.gen)["timings"]
                            for i in range(args.runs)]  # fmt: skip
                    row["gen_tps"] = tps([t["predicted_per_second"] for t in runs])
                    drafted = sum(t.get("draft_n", 0) for t in runs)
                    accepted = sum(t.get("draft_n_accepted", 0) for t in runs)
                    if drafted:
                        row["accept_pct"] = round(100 * accepted / drafted)
            except (subprocess.CalledProcessError, RuntimeError, urllib.error.URLError) as exc:
                row["error"] = em._error_text(exc)
            rows.append(row)
            print(f"   {config.name:14} {label:10} gen {row.get('gen_tps')} "
                  f"accept {row.get('accept_pct')}", file=sys.stderr, flush=True)  # fmt: skip
    return rows


def table(rows: list[dict], columns: list[tuple[str, str]]) -> list[str]:
    lines = ["| " + " | ".join(h for h, _ in columns) + " |",
             "|" + "|".join("---" for _ in columns) + "|"]  # fmt: skip
    for row in rows:
        cells = [str(row.get(key, "")) if key in row else "" for _, key in columns]
        if "error" in row:
            cells[-1] = "error: " + row["error"]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render(rows: list[dict], args: argparse.Namespace, stamp: str, meta: dict) -> str:
    out = [
        f"# llama-server serving features ({stamp})",
        "",
        f"GPU {meta['gpu']}, llama.cpp {meta['llamacpp']}. Target `{args.model}`, "
        f"context {args.ctx}, {args.gen}-token replies, {args.runs} timed runs "
        "(median), flash attention on, temperature 0.",
        "",
    ]
    by = {e: [r for r in rows if r["experiment"] == e] for e in EXPERIMENTS}
    if by["kv"]:
        out += ["## KV-cache type", ""] + table(by["kv"], [
            ("KV type", "config"), ("GPU MiB", "gpu_mib"), ("Gen tok/s", "gen_tps"),
            ("Prompt tok/s", "prompt_tps"),
        ]) + [""]  # fmt: skip
    if by["cache"]:
        out += ["## Prompt-cache reuse", "",
                f"Four turns over a shared ~{args.prefix}-token prefix; each turn adds a new "
                "last line. Seconds are wall time per request.", ""]  # fmt: skip
        out += table(by["cache"], [
            ("Setting", "config"), ("First turn s", "first_s"), ("Later turns s", "later_s"),
            ("Tokens evaluated later", "later_prompt_n"),
        ]) + [""]  # fmt: skip
    if by["slots"]:
        out += ["## Parallel slots", "", "Four concurrent requests.", ""]
        out += table(by["slots"], [
            ("Setting", "config"), ("GPU MiB", "gpu_mib"), ("Wall s", "wall_s"),
            ("Aggregate tok/s", "aggregate_tps"), ("Per request tok/s", "per_request_tps"),
        ]) + [""]  # fmt: skip
    if by["spec"]:
        out += ["## Speculative decoding", "", f"Draft model: `{args.draft}`.", ""]
        out += table(by["spec"], [
            ("Setting", "config"), ("Prompt", "prompt"), ("GPU MiB", "gpu_mib"),
            ("Gen tok/s", "gen_tps"), ("Draft accepted %", "accept_pct"),
        ]) + [""]  # fmt: skip
    return "\n".join(out)


def resolve(model: str) -> Path:
    """An existing GGUF path as given, otherwise the weights Ollama pulled for ``model``."""
    path = Path(model).expanduser()
    if path.is_file():
        return path
    return serve.blob_for(model, serve.models_dir())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("experiments", nargs="*", choices=EXPERIMENTS,
                        help="Which to run (default: all).")  # fmt: skip
    parser.add_argument("--model", default="qwen3:14b", help="Target for kv, cache and slots.")
    parser.add_argument("--spec-model", default="llama3.1:8b", help="Target for spec.")
    parser.add_argument(
        "--draft",
        default="llama3.2:latest",
        help="Draft model for spec: an Ollama model or a GGUF path.",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--gen", type=int, default=128)
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--prefix", type=int, default=6000, help="Shared prefix tokens (cache).")
    parser.add_argument("--out", default=str(REPO_ROOT / "results"))
    args = parser.parse_args()
    chosen = args.experiments or list(EXPERIMENTS)

    rows: list[dict] = []
    for name in chosen:
        print(f"== {name}", file=sys.stderr, flush=True)
        if name == "spec":
            rows += run_spec(resolve(args.spec_model), resolve(args.draft), args)
        else:
            runner = {"kv": run_kv, "cache": run_cache, "slots": run_slots}[name]
            rows += runner(resolve(args.model), args)

    meta = {
        "gpu": subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, check=False,
        ).stdout.strip(),
        "llamacpp": "?",
    }  # fmt: skip
    version = subprocess.run(
        ["podman", "run", "--rm", "--entrypoint", "/app/llama-server", em.IMAGE, "--version"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    for line in (version.stdout + version.stderr).splitlines():
        if line.startswith("version:"):
            meta["llamacpp"] = line.split(":", 1)[1].strip()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    markdown = render(rows, args, stamp, meta)
    (out / f"serving-features-{stamp}.md").write_text(markdown, encoding="utf-8")
    settings = vars(args) | {"out": out.name}
    payload = {"meta": meta, "settings": settings, "rows": rows}
    (out / f"serving-features-{stamp}.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
