"""scripts/llamacpp_bench.sh re-runs itself under an exclusive ECU lease."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "llamacpp_bench.sh"


@pytest.fixture
def stub_ecu(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """A fake `ecu` first on PATH that records its arguments instead of leasing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "ecu-calls.log"
    ecu = bin_dir / "ecu"
    ecu.write_text(f'#!/bin/bash\necho "$*" >> {calls}\nexit 0\n', encoding="utf-8")
    ecu.chmod(ecu.stat().st_mode | stat.S_IXUSR)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CREW_CHIEF_")}
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env, calls


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_it_wraps_itself_in_an_exclusive_batch_lease(stub_ecu) -> None:
    env, calls = stub_ecu
    run(env, "qwen3:14b", "--", "-p", "64")

    line = calls.read_text().strip()
    assert line.startswith("run --gpu exclusive ")
    assert "--priority batch" in line and "--max-wait 2h" in line and "--cpu-cores 2" in line
    assert "--own-gpu-process llama-bench" in line
    # The wrapped command is this same script with the caller's arguments intact.
    assert line.endswith(f"-- bash {SCRIPT} qwen3:14b -- -p 64")


@pytest.mark.parametrize("variable", ["CREW_CHIEF_IN_LEASE", "CREW_CHIEF_NO_LEASE"])
def test_it_does_not_wrap_when_already_leased_or_opted_out(stub_ecu, variable: str) -> None:
    env, calls = stub_ecu
    result = run({**env, variable: "1"})

    assert not calls.exists()
    assert "Usage:" in result.stdout + result.stderr  # it ran on to its own argument check


def test_without_ecu_on_path_it_runs_unwrapped(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CREW_CHIEF_")}
    env["PATH"] = "/usr/bin:/bin"  # no ecu here
    result = run(env)
    assert "Usage:" in result.stdout + result.stderr
