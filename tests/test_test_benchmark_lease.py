"""The benchmark launcher must wait for a lease and reject GPU contention."""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_test_benchmark_lease.py"
SPEC = importlib.util.spec_from_file_location("test_benchmark_lease", SCRIPT)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_launcher_uses_sibling_ecu_source_and_waits(tmp_path, monkeypatch):
    source = tmp_path / "src"
    package = source / "central_ecu"
    package.mkdir(parents=True)
    (package / "__main__.py").write_text("")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    command, env = launcher.lease_command(
        SCRIPT, ["--models", "small"], {"CENTRAL_ECU_SOURCE": str(source)}
    )
    assert command[1:5] == ["-m", "central_ecu", "run", "--wait"]
    assert command[-3:] == ["--inside-lease", "--models", "small"]
    assert env["PYTHONPATH"] == str(source)


def test_launcher_refuses_unregistered_gpu_work(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "ffmpeg\n", ""),
    )
    assert launcher.quiet_gpu() == (False, "GPU still in use by: ffmpeg")
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )
    assert launcher.quiet_gpu() == (True, "GPU is idle")


def test_launcher_names_its_own_ollama_processes_and_bounds_the_wait(tmp_path, monkeypatch):
    source = tmp_path / "src"
    (source / "central_ecu").mkdir(parents=True)
    (source / "central_ecu" / "__main__.py").write_text("")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)

    command, _ = launcher.lease_command(SCRIPT, [], {"CENTRAL_ECU_SOURCE": str(source)})

    options = command[: command.index("--")]
    owned = [options[i + 1] for i, part in enumerate(options) if part == "--own-gpu-process"]
    assert owned == ["ollama", "llama-server"]
    assert options[options.index("--max-wait") + 1] == "2h"
    assert options[options.index("--on-busy") + 1] == "fail"

    command, _ = launcher.lease_command(
        SCRIPT,
        [],
        {"CENTRAL_ECU_SOURCE": str(source), "CREW_CHIEF_LEASE_MAX_WAIT": "30min"},
    )
    assert command[command.index("--max-wait") + 1] == "30min"


def test_the_ollama_runner_is_not_unregistered_gpu_work(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def holders(output):
        return lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, output, "")

    monkeypatch.setattr(launcher.subprocess, "run", holders("/usr/lib/ollama/llama-server\n"))
    assert launcher.quiet_gpu() == (True, "GPU is idle")
    monkeypatch.setattr(
        launcher.subprocess, "run", holders("/usr/lib/ollama/llama-server\n/usr/bin/ffmpeg\n")
    )
    assert launcher.quiet_gpu() == (False, "GPU still in use by: /usr/bin/ffmpeg")
