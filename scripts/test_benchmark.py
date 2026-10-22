#!/usr/bin/env python3
"""Benchmark local coding agents against an existing repository test suite.

Each attempt gets a fresh clone at the same commit. A reviewed task patch or
tests taken from a later commit expose a known failure. The agent gets a fixed
deadline to repair it. Only the final test run and edits to allowed files pass.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
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
    for key in ("name", "prompt", "test_command", "editable_paths"):
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
    if ("setup_patch" in task) == ("evolution" in task):
        raise ValueError("task needs exactly one of setup_patch or evolution")
    if "setup_patch" in task:
        patch = (path.parent / task["setup_patch"]).resolve()
        if not patch.is_file():
            raise ValueError(f"setup patch does not exist: {patch}")
        task["patch_path"] = patch
    else:
        evolution = task["evolution"]
        if not isinstance(evolution, dict) or not all(
            evolution.get(key) for key in ("before", "after", "test_paths")
        ):
            raise ValueError("evolution needs before, after, and test_paths")
        paths = evolution["test_paths"]
        if (
            not isinstance(paths, list)
            or not paths
            or not all(
                isinstance(part, str)
                and part
                and not part.startswith("/")
                and ".." not in pathlib.PurePosixPath(part).parts
                for part in paths
            )
        ):
            raise ValueError("test_paths must contain relative paths")
        if set(paths) & set(task["editable_paths"]):
            raise ValueError("test_paths and editable_paths must not overlap")
    return task


def load_suite(
    path: pathlib.Path, portfolio_root: pathlib.Path
) -> list[tuple[str, pathlib.Path, dict]]:
    """Load reviewed cases from multiple portfolio checkouts."""
    suite = json.loads(path.read_text())
    if (
        not isinstance(suite, dict)
        or not isinstance(suite.get("cases"), list)
        or not suite["cases"]
    ):
        raise ValueError("suite needs a nonempty cases list")
    cases = []
    for case in suite["cases"]:
        if not isinstance(case, dict) or set(case) != {"repo", "task"}:
            raise ValueError("each suite case needs repo and task")
        repo_name = case["repo"]
        if (
            not isinstance(repo_name, str)
            or not repo_name
            or pathlib.PurePosixPath(repo_name).is_absolute()
            or ".." in pathlib.PurePosixPath(repo_name).parts
        ):
            raise ValueError("suite repo must be relative to portfolio root")
        repo = (portfolio_root / repo_name).resolve()
        if not repo.is_relative_to(portfolio_root) or not (repo / ".git").exists():
            raise ValueError(f"suite repo is not a checkout: {repo_name}")
        task_name = case["task"]
        if (
            not isinstance(task_name, str)
            or not task_name
            or pathlib.PurePosixPath(task_name).is_absolute()
            or ".." in pathlib.PurePosixPath(task_name).parts
        ):
            raise ValueError("suite task must be relative to benchmark repository")
        task_path = (path.parent / task_name).resolve()
        if not task_path.is_relative_to(path.parent.resolve()):
            raise ValueError("suite task escapes suite directory")
        cases.append((repo_name, repo, load_task(task_path)))
    if len({task["name"] for _, _, task in cases}) != len(cases):
        raise ValueError("suite task names must be unique")
    return cases


def prepare_evolution(
    repo: pathlib.Path, task: dict, patch_dir: pathlib.Path, test_timeout: int
) -> dict:
    """Review a real before/after change without exposing the source fix to the agent."""
    evolution = task["evolution"]
    before = git(repo, "rev-parse", f"{evolution['before']}^{{commit}}")
    after = git(repo, "rev-parse", f"{evolution['after']}^{{commit}}")
    if (
        before == after
        or subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", before, after], check=False
        ).returncode
    ):
        raise ValueError(f"{task['name']}: before must be an ancestor of after")
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--binary", before, after, "--", *evolution["test_paths"]],
        check=True,
        capture_output=True,
    ).stdout
    if not diff:
        raise ValueError(f"{task['name']}: selected tests did not change")
    reference_paths = git(repo, "diff", "--name-only", before, after, "--", *task["editable_paths"])
    if not reference_paths:
        raise ValueError(f"{task['name']}: reference commit did not change editable source")
    patch = patch_dir / f"evolution-{uuid.uuid4().hex}.patch"
    patch.write_bytes(diff)
    task["patch_path"] = patch
    task["base_commit"] = before
    review = {
        "name": task["name"],
        "mode": "evolution",
        "before_commit": before,
        "after_commit": after,
        "test_paths": evolution["test_paths"],
        "reference_changed_paths": reference_paths.splitlines(),
        "test_patch_sha256": hashlib.sha256(diff).hexdigest(),
        "test_command": task["test_command"],
    }
    with tempfile.TemporaryDirectory(prefix="crew-chief-evolution-review-") as temporary:
        old = pathlib.Path(temporary) / "before"
        new = pathlib.Path(temporary) / "after"
        for work, commit in ((old, before), (new, after)):
            clone_rc, _, clone_output = run(
                ["git", "clone", "--local", "--no-hardlinks", "--quiet", str(repo), str(work)],
                pathlib.Path(temporary),
                60,
            )
            if clone_rc:
                raise ValueError(f"{task['name']}: review clone failed: {clone_output[-500:]}")
            git(work, "checkout", "--detach", "--quiet", commit)
        old_rc, old_seconds, old_output = run(task["test_command"], old, test_timeout)
        if old_rc:
            raise ValueError(
                f"{task['name']}: old suite must pass before new tests: {old_output[-500:]}"
            )
        review["old_suite"] = {"counts": test_counts(old_output), "seconds": round(old_seconds, 2)}
        apply_rc, _, apply_output = run(["git", "apply", str(patch)], old, 30)
        if apply_rc:
            raise ValueError(f"{task['name']}: test patch does not apply: {apply_output[-500:]}")
        baseline_rc, baseline_seconds, baseline_output = run(
            task["test_command"], old, test_timeout
        )
        baseline_counts = test_counts(baseline_output)
        if baseline_rc in (0, 124) or not (
            baseline_counts.get("failed")
            or baseline_counts.get("error")
            or baseline_counts.get("errors")
        ):
            raise ValueError(f"{task['name']}: new tests must fail on the old source")
        review["new_tests_on_old_source"] = {
            "counts": baseline_counts,
            "seconds": round(baseline_seconds, 2),
        }
        reference_rc, reference_seconds, reference_output = run(
            task["test_command"], new, test_timeout
        )
        if reference_rc:
            raise ValueError(
                f"{task['name']}: reference suite must pass: {reference_output[-500:]}"
            )
        review["reference_suite"] = {
            "counts": test_counts(reference_output),
            "seconds": round(reference_seconds, 2),
        }
    task["history_review"] = review
    return review


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

        # Keep injected tests or regressions in the index so later diffs show
        # only the agent's edits, including attempts to alter the new tests.
        git(work, "add", "-A")
        baseline_rc, baseline_seconds, baseline_output = run(
            task["test_command"], work, test_timeout
        )
        record.update(
            baseline_exit=baseline_rc,
            baseline_seconds=round(baseline_seconds, 2),
            baseline_counts=test_counts(baseline_output),
        )
        if baseline_rc in (0, 124) or not (
            record["baseline_counts"].get("failed")
            or record["baseline_counts"].get("error")
            or record["baseline_counts"].get("errors")
        ):
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
            "--provider-timeout",
            str(max(1, agent_timeout - 5)),
            "--test-command-json",
            json.dumps(task["test_command"]),
        ]
        for path in task["editable_paths"]:
            agent_command.extend(("--editable-path", path))
        agent_rc, agent_seconds, agent_output = run(agent_command, work, agent_timeout, prompt)
        record.update(agent_exit=agent_rc, agent_seconds=round(agent_seconds, 2))
        metrics = re.search(r"BENCHMARK_TOOL_CALLS=(\{[^\n]*\})", agent_output)
        if metrics:
            record["tool_calls"] = json.loads(metrics.group(1))
            agent_output = agent_output.replace(metrics.group(0), "").strip()
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
            changed_from_baseline=bool(git(work, "diff", "--binary")),
        )
        record["total_seconds"] = round(time.monotonic() - attempt_start, 2)
        record["status"] = "failed"
        if agent_rc == 124:
            record["status"] = "timeout"
            record["failure_kind"] = "agent_timeout"
            record["error"] = "agent timed out"
        elif agent_rc:
            record["status"] = "error"
            record["failure_kind"] = "agent_error"
            record["error"] = "agent process failed"
        elif final_rc == 124:
            record["status"] = "error"
            record["failure_kind"] = "test_timeout"
            record["error"] = "test suite timed out"
        elif unexpected:
            record["failure_kind"] = "scope_violation"
            record["error"] = "agent edited files outside editable_paths"
        elif final_rc == 0 and record["changed_from_baseline"]:
            record["status"] = "passed"
        elif not record["changed_from_baseline"]:
            calls = record.get("tool_calls", {})
            if calls.get("replace_text", 0):
                record["failure_kind"] = "invalid_edit_attempts"
            elif not any(calls.values()):
                record["failure_kind"] = "no_tool_use"
            else:
                record["failure_kind"] = "no_edit"
        else:
            record["failure_kind"] = "tests_failed"
        return record


def render_html(report: dict) -> str:
    by_model: dict[str, list[dict]] = {}
    for item in report["results"]:
        by_model.setdefault(item["model"], []).append(item)
    summary_rows = []
    for model, trials in by_model.items():
        passes = [item for item in trials if item["status"] == "passed"]
        timeouts = sum(item["status"] == "timeout" for item in trials)
        errors = sum(item["status"] == "error" for item in trials)
        profile = report.get("model_profiles", {}).get(model, {})
        median_time = (
            f"{statistics.median(item['agent_seconds'] for item in passes):.1f}" if passes else "—"
        )
        summary_rows.append(
            "<tr>"
            f"<td>{html.escape(model)}</td><td>{html.escape(profile.get('family', '—'))}</td>"
            f"<td>{html.escape(profile.get('parameter_size', '—'))}</td>"
            f"<td>{html.escape(profile.get('quantization', '—'))}</td>"
            f"<td>{len(passes)}/{len(trials)}</td>"
            f"<td>{timeouts}</td><td>{errors}</td><td>{median_time}</td></tr>"
        )
    rows = []
    for item in report["results"]:
        values = [
            item["model"],
            str(item["trial"]),
            item.get("repo", "—"),
            item["task"],
            item["status"],
            item.get("failure_kind", "—"),
            str(item.get("baseline_counts", {})),
            str(item.get("final_counts", {})),
            str(item.get("tool_calls", {})),
            str(item.get("agent_seconds", "—")),
            str(item.get("total_seconds", "—")),
            item.get("error", "") or item.get("agent_note", ""),
        ]
        cells = "".join(f"<td>{html.escape(value)}</td>" for value in values)
        rows.append(f"<tr class='{html.escape(item['status'])}'>{cells}</tr>")
    history_rows = []
    for case in report.get("case_reviews", []):
        values = [
            case.get("repo", "—"),
            case["name"],
            case["before_commit"][:12],
            str(case["old_suite"]["counts"]),
            str(case["new_tests_on_old_source"]["counts"]),
            case["after_commit"][:12],
            str(case["reference_suite"]["counts"]),
            ", ".join(case["test_paths"]),
            ", ".join(case["reference_changed_paths"]),
        ]
        history_rows.append(
            "<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in values) + "</tr>"
        )
    history_html = ""
    if history_rows:
        history_html = (
            "<h2>Historical case review</h2><p>Only the selected later tests were applied "
            "to the old checkout. The reference source change was withheld from agents.</p>"
            "<table><thead><tr><th>Repository</th><th>Case</th><th>Before</th><th>Old suite</th>"
            "<th>New tests on old source</th><th>After</th><th>Reference suite</th>"
            "<th>Selected test files</th><th>Reference source files</th></tr></thead><tbody>"
            + "\n".join(history_rows)
            + "</tbody></table>"
        )
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Test-based model benchmark</title><style>
body{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#202b38}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border:1px solid #cad2dc;padding:.55rem;text-align:left}
th{background:#e8eef5}.passed{background:#e4f6e9}.failed{background:#fff0e8}.error{background:#ffe5e5}.timeout{background:#fff3cd}
code{background:#edf2f7;padding:.1rem .3rem}small{color:#526171}
nav{display:flex;gap:.6rem;flex-wrap:wrap;margin-bottom:1.3rem}
nav a{padding:.45rem .8rem;border:1px solid #cad2dc;border-radius:6px;color:#004085;text-decoration:none}
nav a[aria-current="page"]{background:#004085;color:white;border-color:#004085}
</style><nav aria-label="Benchmark reports"><a href="latest.html">Inference speed</a>
<a href="test-bench-latest.html" aria-current="page">Test outcomes</a></nav>
<h1>Test-based model benchmark</h1>
<p>Each attempt used a fresh checkout with a known failing test. A pass requires
the fixed test command to pass after an allowed code edit.</p>
<p><small>Case count: """
        + str(len(report.get("tasks", [1])))
        + """ · Created: """
        + html.escape(report["created_at"])
        + (" · Updated: " + html.escape(report["updated_at"]) if report.get("updated_at") else "")
        + """</small></p>"""
        + history_html
        + """<h2>Model summary</h2><table><thead><tr><th>Model</th><th>Family</th>
<th>Parameters</th><th>Quantization</th><th>Passed trials</th>
<th>Timeouts</th><th>Agent errors</th><th>Median agent seconds on passes</th></tr></thead><tbody>"""
        + "\n".join(summary_rows)
        + """</tbody></table><h2>Trial details</h2>
<table><thead><tr><th>Model</th><th>Trial</th><th>Repository</th><th>Task</th><th>Outcome</th><th>Failure kind</th>
<th>Baseline</th><th>Final tests</th><th>Tool calls</th><th>Agent seconds</th>
<th>Total seconds</th><th>Note</th></tr></thead>
<tbody>"""
        + "\n".join(rows)
        + "</tbody></table></html>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=pathlib.Path)
    parser.add_argument("--task", type=pathlib.Path, action="append")
    parser.add_argument("--suite", type=pathlib.Path)
    parser.add_argument("--portfolio-root", type=pathlib.Path)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--agent-timeout", type=int, default=300)
    parser.add_argument("--test-timeout", type=int, default=180)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()
    if args.agent_timeout < 1 or args.test_timeout < 1 or args.runs < 1:
        parser.error("timeouts and runs must be positive")
    if args.suite:
        if args.repo or args.task or not args.portfolio_root:
            parser.error("--suite requires --portfolio-root and excludes --repo/--task")
        cases = load_suite(args.suite.resolve(), args.portfolio_root.resolve())
    else:
        if not args.repo or not args.task or args.portfolio_root:
            parser.error("--repo and --task are required without --suite")
        repo = args.repo.resolve()
        cases = [(repo.name, repo, load_task(path.resolve())) for path in args.task]
    if len({task["name"] for _, _, task in cases}) != len(cases):
        parser.error("task names must be unique in one report")
    report = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agent_timeout_seconds": args.agent_timeout,
        "test_timeout_seconds": args.test_timeout,
        "tasks": [],
        "case_reviews": [],
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
        report["model_profiles"] = {
            item["name"]: {
                "family": item.get("details", {}).get("family", "unknown"),
                "parameter_size": item.get("details", {}).get("parameter_size", "unknown"),
                "quantization": item.get("details", {}).get("quantization_level", "unknown"),
                "weight_bytes": item.get("size", 0),
            }
            for item in tags
            if item.get("name") in args.models
        }
    except OSError:
        report["ollama_version"] = "unavailable"
    with tempfile.TemporaryDirectory(prefix="crew-chief-benchmark-patches-") as temporary:
        for repo_name, repo, task in cases:
            if "evolution" in task:
                print(f"Reviewing historical case: {task['name']} ...", flush=True)
                review = prepare_evolution(repo, task, pathlib.Path(temporary), args.test_timeout)
                review["repo"] = repo_name
                report["case_reviews"].append(review)
            else:
                task["base_commit"] = git(repo, "rev-parse", "HEAD")
            report["tasks"].append(
                {
                    "repo": repo_name,
                    "name": task["name"],
                    "mode": "evolution" if "evolution" in task else "seeded_regression",
                    "base_commit": task["base_commit"],
                    "test_command": task["test_command"],
                    "task_patch_sha256": hashlib.sha256(
                        task["patch_path"].read_bytes()
                    ).hexdigest(),
                }
            )
        for repo_name, repo, task in cases:
            for model in args.models:
                for trial in range(1, args.runs + 1):
                    print(f"{model} trial {trial}: {task['name']} ...", flush=True)
                    result = benchmark_one(
                        repo,
                        task["base_commit"],
                        task,
                        model,
                        args.agent_timeout,
                        args.test_timeout,
                        args.url,
                    )
                    result["trial"] = trial
                    result["repo"] = repo_name
                    report["results"].append(result)
                    print(
                        f"  {result['status']}: {result.get('error', result.get('final_counts', {}))}"
                    )
    out = args.out or pathlib.Path("results") / (
        "test-bench-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    page = out.with_suffix(".html")
    page.write_text(render_html(report))
    for artifact in (out, page):
        latest = artifact.with_name(f"test-bench-latest{artifact.suffix}")
        if artifact == latest:
            continue
        if latest.exists() and not latest.is_symlink():
            raise FileExistsError(f"Refusing to replace non-symlink report: {latest}")
        pending = latest.with_name(f".{latest.name}.{uuid.uuid4().hex}")
        pending.symlink_to(artifact.name)
        os.replace(pending, latest)
    print(f"Results: {out}\nUI: {page}")
    return 0 if all(item["status"] == "passed" for item in report["results"]) else 1


if __name__ == "__main__":
    sys.exit(main())
