#!/usr/bin/env python3
"""Restricted local tool loop used by the test-based benchmark."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from crew_chief.agent import Agent  # noqa: E402
from crew_chief.providers.ollama import OllamaProvider  # noqa: E402
from crew_chief.tools import Tool  # noqa: E402


class ReadRepoFile(Tool):
    name = "read_file"
    description = (
        "Read a UTF-8 source or test file in this checkout. Paths are relative to the checkout."
    )
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self, root: pathlib.Path):
        self.root = root

    def execute(self, arguments: dict) -> str:
        path = pathlib.Path(str(arguments.get("path", "")))
        if path.is_absolute() or ".." in path.parts:
            return "Access denied: use a relative path within the checkout."
        candidate = self.root / path
        target = candidate.resolve()
        if not target.is_relative_to(self.root) or not target.is_file() or candidate.is_symlink():
            return "Access denied: file is outside the checkout or missing."
        if not (path.parts and path.parts[0] in ("src", "tests")):
            return "Access denied: only source and test files are readable."
        return target.read_text(errors="replace")[:12000]


class ReplaceText(Tool):
    name = "replace_text"
    description = (
        "Replace one exact text span in an allowed source file. Paths are relative to the checkout."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
        "required": ["path", "old", "new"],
    }

    def __init__(self, root: pathlib.Path, allowed: list[str]):
        self.root = root
        self.allowed = set(allowed)

    def execute(self, arguments: dict) -> str:
        path = str(arguments.get("path", ""))
        if path not in self.allowed:
            return "Access denied: path is not editable."
        candidate = self.root / path
        target = candidate.resolve()
        if not target.is_relative_to(self.root) or not target.is_file() or candidate.is_symlink():
            return "Access denied: invalid file."
        old = str(arguments.get("old", ""))
        new = str(arguments.get("new", ""))
        if not old or old == new:
            return "No change: old text must be nonempty and different."
        original = target.read_text()
        count = original.count(old)
        if count != 1:
            return f"No change: old text occurs {count} times; expected exactly once."
        target.write_text(original.replace(old, new, 1))
        return "Replaced one occurrence."


class RunTests(Tool):
    name = "run_tests"
    description = "Run the fixed repository test command and return its exit code and brief output."
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, root: pathlib.Path, command: list[str], timeout: int):
        self.root = root
        self.command = command
        self.timeout = timeout

    def execute(self, arguments: dict) -> str:  # noqa: ARG002
        try:
            result = subprocess.run(
                self.command,
                cwd=self.root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout,
                check=False,
            )
            return f"exit code: {result.returncode}\n{result.stdout[-4000:]}"
        except subprocess.TimeoutExpired:
            return "Tests timed out."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=pathlib.Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--test-timeout", type=int, required=True)
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--editable-path", action="append", required=True)
    parser.add_argument("--test-command-json", required=True)
    args = parser.parse_args()
    import json

    root = args.work.resolve()
    tools = [
        ReadRepoFile(root),
        ReplaceText(root, args.editable_path),
        RunTests(root, json.loads(args.test_command_json), args.test_timeout),
    ]
    agent = Agent(
        provider=OllamaProvider(base_url=args.url, model=args.model, timeout=90),
        tools=tools,
        max_iterations=args.max_iterations,
        system_prompt=(
            "You are repairing a deliberately broken repository. Read relevant source and tests, "
            "use replace_text to edit only the allowed file, then run_tests. Do not claim success "
            "until the tests pass. You have no shell tool. Keep changes minimal."
        ),
    )
    print(agent.run(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
