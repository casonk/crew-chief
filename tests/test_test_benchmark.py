"""Outcome and isolation checks for the test-based model benchmark."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "test_benchmark.py"
SPEC = importlib.util.spec_from_file_location("test_benchmark", SCRIPT)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def git(repo: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


@pytest.fixture
def broken_task(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    source = repo / "src" / "value.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "base",
    )
    source.write_text("VALUE = 0\n")
    patch = tmp_path / "break.patch"
    patch.write_text(git(repo, "diff") + "\n")
    git(repo, "restore", "--", "src/value.py")
    task = {
        "name": "repair value",
        "prompt": "Restore the value.",
        "patch_path": patch,
        "test_command": [
            "python3",
            "-c",
            "import pathlib,sys; ok='VALUE = 1' in pathlib.Path('src/value.py').read_text(); print('1 passed' if ok else '1 failed'); sys.exit(0 if ok else 1)",
        ],
        "editable_paths": ["src/value.py"],
    }
    return repo, task


def test_benchmark_requires_real_repair_and_rejects_other_edits(broken_task, monkeypatch):
    repo, task = broken_task
    original_run = benchmark.run
    action = {"repair": False, "extra": False}

    def fake_run(command, cwd, timeout, prompt=None):
        if "test_benchmark_agent.py" in " ".join(command):
            if action["repair"]:
                (cwd / "src/value.py").write_text("VALUE = 1\n")
            if action["extra"]:
                (cwd / "tests.py").write_text("edited\n")
            return 0, 0.1, "done"
        return original_run(command, cwd, timeout, prompt)

    monkeypatch.setattr(benchmark, "run", fake_run)
    base = git(repo, "rev-parse", "HEAD")
    outcome = benchmark.benchmark_one(repo, base, task, "fake", 10, 10, "http://localhost")
    assert outcome["status"] == "failed"
    assert outcome["baseline_counts"] == outcome["final_counts"] == {"failed": 1}

    action["repair"] = True
    outcome = benchmark.benchmark_one(repo, base, task, "fake", 10, 10, "http://localhost")
    assert outcome["status"] == "passed"
    assert outcome["final_counts"] == {"passed": 1}

    action["extra"] = True
    outcome = benchmark.benchmark_one(repo, base, task, "fake", 10, 10, "http://localhost")
    assert outcome["status"] == "failed"
    assert outcome["unexpected_paths"] == ["tests.py"]


def test_historical_replay_withholds_reference_fix_and_rejects_test_edits(tmp_path, monkeypatch):
    repo = tmp_path / "history"
    repo.mkdir()
    git(repo, "init", "-q")
    source = repo / "src" / "value.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    tests = repo / "tests" / "test_value.py"
    tests.parent.mkdir()
    tests.write_text(
        "from pathlib import Path\n\n"
        "def test_positive():\n"
        "    assert 'VALUE = 1' in Path('src/value.py').read_text() or "
        "'VALUE = 2' in Path('src/value.py').read_text()\n"
    )
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "before",
    )
    before = git(repo, "rev-parse", "HEAD")
    with tests.open("a") as stream:
        stream.write(
            "\ndef test_new_rule():\n    assert 'VALUE = 2' in Path('src/value.py').read_text()\n"
        )
    source.write_text("VALUE = 2\n")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "after",
    )
    after = git(repo, "rev-parse", "HEAD")
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "historical rule",
                "prompt": "Comply with the new rule.",
                "evolution": {
                    "before": before,
                    "after": after,
                    "test_paths": ["tests/test_value.py"],
                },
                "test_command": ["pytest", "-q"],
                "editable_paths": ["src/value.py"],
            }
        )
    )
    task = benchmark.load_task(manifest)
    review = benchmark.prepare_evolution(repo, task, tmp_path, 15)
    assert review["old_suite"]["counts"] == {"passed": 1}
    assert review["new_tests_on_old_source"]["counts"] == {"failed": 1, "passed": 1}
    assert review["reference_suite"]["counts"] == {"passed": 2}

    original_run = benchmark.run
    action = {"edit_test": False}

    def fake_run(command, cwd, timeout, prompt=None):
        if "test_benchmark_agent.py" in " ".join(command):
            if action["edit_test"]:
                (cwd / "tests/test_value.py").write_text("def test_tampered():\n    assert True\n")
            else:
                (cwd / "src/value.py").write_text("VALUE = 2\n")
            return 0, 0.1, "done"
        return original_run(command, cwd, timeout, prompt)

    monkeypatch.setattr(benchmark, "run", fake_run)
    outcome = benchmark.benchmark_one(repo, before, task, "fake", 10, 15, "http://localhost")
    assert outcome["status"] == "passed"
    assert outcome["changed_paths"] == ["src/value.py"]
    action["edit_test"] = True
    outcome = benchmark.benchmark_one(repo, before, task, "fake", 10, 15, "http://localhost")
    assert outcome["status"] == "failed"
    assert outcome["unexpected_paths"] == ["tests/test_value.py"]


def test_suite_resolves_cases_and_rejects_path_escape(tmp_path, broken_task):
    repo, task = broken_task
    portfolio = tmp_path / "portfolio"
    portfolio.mkdir()
    checkout = portfolio / "utility"
    repo.rename(checkout)
    task_manifest = tmp_path / "task.json"
    task_manifest.write_text(
        json.dumps(
            {
                "name": task["name"],
                "prompt": "Restore the value.",
                "setup_patch": task["patch_path"].name,
                "test_command": task["test_command"],
                "editable_paths": task["editable_paths"],
            }
        )
    )
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps({"cases": [{"repo": "utility", "task": "task.json"}]}))
    cases = benchmark.load_suite(suite, portfolio)
    assert [(name, path) for name, path, _ in cases] == [("utility", checkout)]

    suite.write_text(json.dumps({"cases": [{"repo": "../outside", "task": "task.json"}]}))
    with pytest.raises(ValueError, match="relative to portfolio root"):
        benchmark.load_suite(suite, portfolio)


def test_tracked_public_suite_references_valid_unique_tasks():
    suite_path = SCRIPT.parents[1] / "benchmarks" / "public-history-suite.json"
    cases = json.loads(suite_path.read_text())["cases"]
    assert cases

    tasks = []
    for case in cases:
        assert set(case) == {"repo", "task"}
        task_path = (suite_path.parent / case["task"]).resolve()
        assert task_path.is_relative_to(suite_path.parent)
        tasks.append(benchmark.load_task(task_path))

    assert len({task["name"] for task in tasks}) == len(tasks)
    assert all("evolution" in task for task in tasks)


def make_history(tmp_path):
    """A repo with a before commit and an after commit that adds a failing-then-fixed test."""
    repo = tmp_path / "history"
    repo.mkdir()
    git(repo, "init", "-q")
    source = repo / "src" / "value.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    tests = repo / "tests" / "test_value.py"
    tests.parent.mkdir()
    tests.write_text(
        "from pathlib import Path\n\ndef test_positive():\n"
        "    assert 'VALUE' in Path('src/value.py').read_text()\n"
    )
    identity = ("-c", "user.name=Test", "-c", "user.email=test@example.invalid")
    git(repo, "add", ".")
    git(repo, *identity, "commit", "-qm", "before")
    before = git(repo, "rev-parse", "HEAD")
    with tests.open("a") as stream:
        stream.write(
            "\ndef test_new_rule():\n    assert 'VALUE = 2' in Path('src/value.py').read_text()\n"
        )
    source.write_text("VALUE = 2\n")
    git(repo, "add", ".")
    git(repo, *identity, "commit", "-qm", "after")
    manifest = tmp_path / "history-task.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "historical rule",
                "prompt": "Comply with the new rule.",
                "evolution": {
                    "before": before,
                    "after": git(repo, "rev-parse", "HEAD"),
                    "test_paths": ["tests/test_value.py"],
                },
                "test_command": ["pytest", "-q"],
                "editable_paths": ["src/value.py"],
            }
        )
    )
    return repo, manifest


def test_an_unchanged_historical_case_is_not_reviewed_twice(tmp_path, monkeypatch):
    repo, manifest = make_history(tmp_path)
    suite_runs = []
    original_run = benchmark.run

    def counting_run(command, cwd, timeout, prompt=None):
        if command == ["pytest", "-q"]:
            suite_runs.append(cwd)
        return original_run(command, cwd, timeout, prompt)

    monkeypatch.setattr(benchmark, "run", counting_run)
    cache: dict = {}

    first = benchmark.prepare_evolution(repo, benchmark.load_task(manifest), tmp_path, 30, cache)
    assert len(suite_runs) == 3 and "cached_from" not in first and len(cache) == 1

    task = benchmark.load_task(manifest)
    second = benchmark.prepare_evolution(repo, task, tmp_path, 30, cache)
    assert len(suite_runs) == 3, "the cached review ran no test suite"
    assert second["cached_from"] > 0
    for name in benchmark.REVIEW_SUITES:
        assert second[name] == first[name]
    # The trial still needs everything a fresh review sets on the task.
    assert task["patch_path"].is_file() and task["history_review"] is second
    assert task["base_commit"] == first["before_commit"]


def test_the_review_cache_follows_the_inputs_that_decide_the_result(tmp_path, monkeypatch):
    repo, manifest = make_history(tmp_path)
    cache: dict = {}
    benchmark.prepare_evolution(repo, benchmark.load_task(manifest), tmp_path, 30, cache)
    (key,) = cache

    stale = {key: {**cache[key], "created": 1.0}}  # far older than the time limit
    task = benchmark.load_task(manifest)
    assert "cached_from" not in benchmark.prepare_evolution(repo, task, tmp_path, 30, stale)

    changed = json.loads(manifest.read_text())
    changed["test_command"] = ["pytest", "-q", "-x"]
    manifest.write_text(json.dumps(changed))
    task = benchmark.load_task(manifest)
    assert "cached_from" not in benchmark.prepare_evolution(repo, task, tmp_path, 30, cache)
    assert len(cache) == 2

    uncached = benchmark.prepare_evolution(repo, benchmark.load_task(manifest), tmp_path, 30, None)
    assert "cached_from" not in uncached
    assert benchmark.load_review_cache(None) is None
    assert benchmark.load_review_cache(tmp_path / "missing.json") == {}


class Interrupted(BaseException):
    """Stands in for a lease preemption or a crash in the middle of a sweep."""


@pytest.fixture
def sweep(broken_task, tmp_path, monkeypatch):
    repo, task = broken_task
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "name": task["name"],
                "prompt": task["prompt"],
                "setup_patch": task["patch_path"].name,
                "test_command": task["test_command"],
                "editable_paths": task["editable_paths"],
            }
        )
    )
    calls = []
    state = {"die_on": None}

    def fake_trial(repo, base_commit, task, model, agent_timeout, test_timeout, url):
        calls.append(model)
        if state["die_on"] == len(calls):
            raise Interrupted
        return {"model": model, "task": task["name"], "status": "passed", "total_seconds": 1.0}

    def urlopen(*args, **kwargs):
        raise OSError("no ollama in tests")

    monkeypatch.setattr(benchmark, "benchmark_one", fake_trial)
    monkeypatch.setattr(benchmark.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(benchmark, "render_html", lambda report: "<html></html>")
    out = tmp_path / "out" / "sweep.json"

    def run_main(*extra):
        argv = ["test_benchmark.py", "--repo", str(repo), "--task", str(manifest)]
        argv += ["--models", "alpha", "--runs", "3", "--out", str(out), "--no-latest"]
        argv += ["--no-review-cache", *extra]
        monkeypatch.setattr(sys, "argv", argv)
        return benchmark.main()

    return run_main, out, calls, state


def test_an_interrupted_sweep_resumes_without_repeating_finished_trials(sweep, capsys):
    run_main, out, calls, state = sweep
    state["die_on"] = 3

    with pytest.raises(Interrupted):
        run_main()

    partial = out.with_suffix(".partial.json")
    saved = json.loads(partial.read_text())
    assert saved["partial"] is True and [r["trial"] for r in saved["results"]] == [1, 2]
    assert not out.exists()

    assert run_main() == 2, "a fresh run must not silently overwrite saved progress"
    assert "--resume" in capsys.readouterr().err

    state["die_on"] = None
    calls.clear()
    assert run_main("--resume") == 0
    assert calls == ["alpha"], "only the unfinished trial ran"
    final = json.loads(out.read_text())
    assert [r["trial"] for r in final["results"]] == [1, 2, 3]
    assert final["resumed_trials"] == 2 and "partial" not in final
    assert not partial.exists()


def test_resume_refuses_trials_recorded_under_other_conditions(sweep, capsys):
    run_main, out, calls, state = sweep
    state["die_on"] = 2
    with pytest.raises(Interrupted):
        run_main()
    capsys.readouterr()

    assert run_main("--resume", "--agent-timeout", "99") == 2
    assert "timing tiers differ" in capsys.readouterr().err

    saved = json.loads(out.with_suffix(".partial.json").read_text())
    saved["tasks"][0]["task_patch_sha256"] = "0" * 64
    out.with_suffix(".partial.json").write_text(json.dumps(saved))
    assert run_main("--resume") == 2
    assert "changed (task_patch_sha256)" in capsys.readouterr().err
