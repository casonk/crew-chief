#!/usr/bin/env python3
"""Run the test benchmark under an exclusive ecu GPU lease."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys


def lease_command(
    script: pathlib.Path, args: list[str], env: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """Use an installed ECU, or the sibling checkout until installation finishes."""
    ecu = shutil.which("ecu")
    if ecu:
        prefix = [ecu]
    else:
        source = pathlib.Path(
            env.get("CENTRAL_ECU_SOURCE", script.parents[2] / "ecu" / "src")
        ).resolve()
        if not (source / "central_ecu" / "__main__.py").is_file():
            raise ValueError("ecu is unavailable; install ecu or set CENTRAL_ECU_SOURCE")
        env = {
            **env,
            "PYTHONPATH": os.pathsep.join(filter(None, (str(source), env.get("PYTHONPATH", "")))),
        }
        prefix = [sys.executable, "-m", "central_ecu"]
    return (
        [*prefix, "run", "--wait", "--", sys.executable, str(script), "--inside-lease", *args],
        env,
    )


def quiet_gpu() -> tuple[bool, str]:
    """An exclusive lease must also have no unregistered GPU compute process."""
    tool = shutil.which("nvidia-smi")
    if not tool:
        return False, "nvidia-smi is unavailable"
    try:
        result = subprocess.run(
            [tool, "--query-compute-apps=process_name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False, "GPU process query failed"
    holders = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return (
        (False, f"GPU still in use by: {', '.join(holders)}") if holders else (True, "GPU is idle")
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    script = pathlib.Path(__file__).resolve()
    benchmark = script.with_name("test_benchmark.py")
    if args in (["--help"], ["-h"]):
        os.execv(sys.executable, [sys.executable, str(benchmark), *args])
    if args[:1] == ["--inside-lease"]:
        ready, message = quiet_gpu()
        if not ready:
            print(f"benchmark deferred: {message}", file=sys.stderr)
            return 75
        os.execv(sys.executable, [sys.executable, str(benchmark), *args[1:]])
    try:
        command, env = lease_command(script, args, dict(os.environ))
    except ValueError as exc:
        print(f"benchmark cannot start: {exc}", file=sys.stderr)
        return 2
    os.execvpe(command[0], command, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
