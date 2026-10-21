"""Outcome and isolation checks for the test-based model benchmark."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

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
