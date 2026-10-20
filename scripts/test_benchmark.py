#!/usr/bin/env python3
"""Benchmark local coding agents against an existing repository test suite.

Each attempt gets a fresh clone at the same commit. A task patch introduces a
known failure, the baseline test must fail, and the agent gets a fixed deadline
to repair it. Only the final test run and edits to allowed files can pass.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone


def run(command: list[str], cwd: pathlib.Path, timeout: int, prompt: str | None = None):
    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return result.returncode, time.monotonic() - start, result.stdout[-12000:]
    except subprocess.TimeoutExpired:
        return 124, time.monotonic() - start, "Timed out"


def git(repo: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def load_task(path: pathlib.Path) -> dict:
    task = json.loads(path.read_text())
    for key in ("name", "prompt", "setup_patch", "test_command", "editable_paths"):
        if not task.get(key):
            raise ValueError(f"task is missing {key}")
    if not isinstance(task["test_command"], list) or not all(
        isinstance(part, str) for part in task["test_command"]
    ):
        raise ValueError("test_command must be an argv list")
    if not isinstance(task["editable_paths"], list) or not all(
        isinstance(part, str)
        and part
        and not part.startswith("/")
        and ".." not in pathlib.PurePosixPath(part).parts
        for part in task["editable_paths"]
    ):
        raise ValueError("editable_paths must contain relative paths")
    patch = (path.parent / task["setup_patch"]).resolve()
    if not patch.is_file():
        raise ValueError(f"setup patch does not exist: {patch}")
    task["patch_path"] = patch
    return task


def test_counts(output: str) -> dict[str, int]:
    counts = {}
    for amount, label in re.findall(
        r"\b(\d+) (passed|failed|error|errors|skipped|subtests passed)\b", output
    ):
        counts[label] = int(amount)
    return counts


def changed_paths(repo: pathlib.Path) -> list[str]:
    tracked = git(repo, "diff", "--name-only").splitlines()
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(set(tracked + untracked))


def benchmark_one(
    repo: pathlib.Path,
    base_commit: str,
    task: dict,
    model: str,
    agent_timeout: int,
    test_timeout: int,
    url: str,
) -> dict:
    attempt_start = time.monotonic()
    record = {
        "model": model,
        "task": task["name"],
        "base_commit": base_commit,
        "status": "error",
    }
    with tempfile.TemporaryDirectory(prefix="crew-chief-test-bench-") as temporary:
        work = pathlib.Path(temporary) / "checkout"
        clone_rc, _, clone_output = run(
            ["git", "clone", "--local", "--no-hardlinks", "--quiet", str(repo), str(work)],
            pathlib.Path(temporary),
            60,
        )
        if clone_rc:
            record["error"] = f"clone failed: {clone_output[-500:]}"
            return record
        git(work, "checkout", "--detach", "--quiet", base_commit)
        patch_rc, _, patch_output = run(["git", "apply", str(task["patch_path"])], work, 30)
        if patch_rc:
            record["error"] = f"setup patch failed: {patch_output[-500:]}"
            return record

        baseline_diff = git(work, "diff", "--binary")
        baseline_rc, baseline_seconds, baseline_output = run(
            task["test_command"], work, test_timeout
        )
        record.update(
            baseline_exit=baseline_rc,
            baseline_seconds=round(baseline_seconds, 2),
            baseline_counts=test_counts(baseline_output),
        )
        if baseline_rc in (0, 124) or not record["baseline_counts"].get("failed"):
            record["error"] = "baseline must have a completed test failure"
            return record

        prompt = (
            f"{task['prompt']}\n\n"
            "Work only in this checkout. Do not edit tests, test configuration, or "
            "files outside the stated editable paths. Do not commit."
        )
        agent_command = [
            sys.executable,
            str(pathlib.Path(__file__).with_name("test_benchmark_agent.py").resolve()),
            "--work",
            str(work),
            "--model",
            model,
            "--url",
            url,
            "--test-timeout",
            str(test_timeout),
            "--test-command-json",
            json.dumps(task["test_command"]),
        ]
        for path in task["editable_paths"]:
            agent_command.extend(("--editable-path", path))
        agent_rc, agent_seconds, agent_output = run(agent_command, work, agent_timeout, prompt)
        record.update(agent_exit=agent_rc, agent_seconds=round(agent_seconds, 2))
        record["agent_note"] = agent_output[-500:].strip()
        if agent_rc:
            record["agent_error"] = agent_output[-500:]

        paths = changed_paths(work)
        unexpected = [path for path in paths if path not in task["editable_paths"]]
        final_rc, final_seconds, final_output = run(task["test_command"], work, test_timeout)
        record.update(
            final_exit=final_rc,
            final_seconds=round(final_seconds, 2),
            final_counts=test_counts(final_output),
            changed_paths=paths,
            unexpected_paths=unexpected,
            changed_from_baseline=(git(work, "diff", "--binary") != baseline_diff),
        )
        record["total_seconds"] = round(time.monotonic() - attempt_start, 2)
        record["status"] = (
            "passed"
            if agent_rc == 0
            and final_rc == 0
            and not unexpected
            and record["changed_from_baseline"]
            else "failed"
        )
        if agent_rc == 124:
            record["error"] = "agent timed out"
        elif final_rc == 124:
            record["error"] = "test suite timed out"
        elif unexpected:
            record["error"] = "agent edited files outside editable_paths"
        return record


def render_html(report: dict) -> str:
    by_model: dict[str, list[dict]] = {}
    for item in report["results"]:
        by_model.setdefault(item["model"], []).append(item)
    summary_rows = []
    for model, trials in by_model.items():
        passes = [item for item in trials if item["status"] == "passed"]
        median_time = (
            f"{statistics.median(item['agent_seconds'] for item in passes):.1f}" if passes else "—"
        )
        summary_rows.append(
            "<tr>"
            f"<td>{html.escape(model)}</td><td>{len(passes)}/{len(trials)}</td>"
            f"<td>{median_time}</td></tr>"
        )
    rows = []
    for item in report["results"]:
        values = [
            item["model"],
            str(item["trial"]),
            item["task"],
            item["status"],
            str(item.get("baseline_counts", {})),
            str(item.get("final_counts", {})),
            str(item.get("agent_seconds", "—")),
            str(item.get("total_seconds", "—")),
            item.get("error", "") or item.get("agent_note", ""),
        ]
        cells = "".join(f"<td>{html.escape(value)}</td>" for value in values)
        rows.append(f"<tr class='{html.escape(item['status'])}'>{cells}</tr>")
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Test-based model benchmark</title><style>
body{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#202b38}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border:1px solid #cad2dc;padding:.55rem;text-align:left}
th{background:#e8eef5}.passed{background:#e4f6e9}.failed{background:#fff0e8}.error{background:#ffe5e5}
code{background:#edf2f7;padding:.1rem .3rem}small{color:#526171}
</style><h1>Test-based model benchmark</h1>
<p>Each attempt used a fresh checkout with a known failing test. A pass requires
the original test command to pass after an allowed code edit.</p>
<p><small>Commit: <code>"""
        + html.escape(report["base_commit"])
        + """</code> · Created: """
        + html.escape(report["created_at"])
        + """</small></p>
<h2>Model summary</h2><table><thead><tr><th>Model</th><th>Passed trials</th>
<th>Median agent seconds on passes</th></tr></thead><tbody>"""
        + "\n".join(summary_rows)
        + """</tbody></table><h2>Trial details</h2>
<table><thead><tr><th>Model</th><th>Trial</th><th>Task</th><th>Outcome</th><th>Baseline</th>
<th>Final tests</th><th>Agent seconds</th><th>Total seconds</th><th>Note</th></tr></thead>
<tbody>"""
        + "\n".join(rows)
        + "</tbody></table></html>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path, required=True)
    parser.add_argument("--task", type=pathlib.Path, required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--agent-timeout", type=int, default=300)
    parser.add_argument("--test-timeout", type=int, default=180)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()
    if args.agent_timeout < 1 or args.test_timeout < 1 or args.runs < 1:
        parser.error("timeouts and runs must be positive")
    repo = args.repo.resolve()
    task = load_task(args.task.resolve())
    base_commit = git(repo, "rev-parse", "HEAD")
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_commit": base_commit,
        "test_command": task["test_command"],
        "task_patch_sha256": hashlib.sha256(task["patch_path"].read_bytes()).hexdigest(),
        "agent_timeout_seconds": args.agent_timeout,
        "test_timeout_seconds": args.test_timeout,
        "results": [],
    }
    try:
        hardware = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            text=True,
            capture_output=True,
            check=True,
            timeout=5,
        )
        report["hardware"] = hardware.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        report["hardware"] = "unknown"
    try:
        with urllib.request.urlopen(args.url.rstrip("/") + "/api/version", timeout=5) as response:
            report["ollama_version"] = json.load(response).get("version", "unknown")
        with urllib.request.urlopen(args.url.rstrip("/") + "/api/tags", timeout=5) as response:
            tags = json.load(response).get("models", [])
        report["model_digests"] = {
            item["name"]: item.get("digest", "") for item in tags if item.get("name") in args.models
        }
    except OSError:
        report["ollama_version"] = "unavailable"
    for model in args.models:
        for trial in range(1, args.runs + 1):
            print(f"{model} trial {trial}: {task['name']} ...", flush=True)
            result = benchmark_one(
                repo, base_commit, task, model, args.agent_timeout, args.test_timeout, args.url
            )
            result["trial"] = trial
            report["results"].append(result)
            print(f"  {result['status']}: {result.get('error', result.get('final_counts', {}))}")
    out = args.out or pathlib.Path("results") / (
        "test-bench-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    page = out.with_suffix(".html")
    page.write_text(render_html(report))
    print(f"Results: {out}\nUI: {page}")
    return 0 if all(item["status"] == "passed" for item in report["results"]) else 1


if __name__ == "__main__":
    sys.exit(main())
