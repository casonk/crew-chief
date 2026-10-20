"""Outcome and isolation checks for the test-based model benchmark."""

from __future__ import annotations

import importlib.util
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
