"""Tests for crew_chief.code_launcher — offline, no Ollama or claude required."""

from __future__ import annotations

import json
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from crew_chief import code_launcher
from crew_chief.cli import build_parser
from crew_chief.code_launcher import (
    LEASE_ENV,
    LaunchError,
    build_argv,
    build_env,
    check_model,
    is_resume,
    launch,
    lease_prefix,
    ollama_tool_models,
    policy_gpu_mib,
    record_session,
)


def _fake_get_json(capabilities: dict[str, list[str]]):
    def fake(url, timeout, payload=None):
        if url.endswith("/api/tags"):
            return {"models": [{"name": name} for name in capabilities]}
        if url.endswith("/api/show"):
            return {"capabilities": capabilities[payload["model"]]}
        raise AssertionError(url)

    return fake


CAPS = {
    "qwen3:14b": ["completion", "tools", "thinking"],
    "gemma3:27b": ["completion", "vision"],
}


class TestModelCheck(unittest.TestCase):
    def test_lists_only_tool_capable_models(self):
        with patch.object(code_launcher, "_get_json", _fake_get_json(CAPS)):
            self.assertEqual(ollama_tool_models("http://x"), ["qwen3:14b"])

    def test_rejects_chat_only_model(self):
        with patch.object(code_launcher, "_get_json", _fake_get_json(CAPS)):
            with self.assertRaisesRegex(LaunchError, "qwen3:14b"):
                check_model("ollama", "http://x", "gemma3:27b")

    def test_accepts_tool_model(self):
        with patch.object(code_launcher, "_get_json", _fake_get_json(CAPS)):
            check_model("ollama", "http://x", "qwen3:14b")

    def test_unreachable_server(self):
        with patch.object(code_launcher, "_get_json", side_effect=OSError("refused")):
            with self.assertRaisesRegex(LaunchError, "not reachable"):
                ollama_tool_models("http://x")


class TestEnvAndArgv(unittest.TestCase):
    def test_env_points_every_model_slot_at_local_model(self):
        env = build_env("http://localhost:11434", "qwen3:14b", 32768, {"PATH": "/bin"})
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://localhost:11434")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "")
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "32768")
        for key in (
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_SMALL_FAST_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
        ):
            self.assertEqual(env[key], "qwen3:14b")
        self.assertEqual(env["PATH"], "/bin")

    def test_argv_pins_session_id(self):
        self.assertEqual(
            build_argv("m", ["-p", "hi"], "abc"),
            ["claude", "--model", "m", "--session-id", "abc", "-p", "hi"],
        )

    def test_resume_detection(self):
        self.assertTrue(is_resume(["--resume", "abc"]))
        self.assertTrue(is_resume(["--resume=abc"]))
        self.assertTrue(is_resume(["-c"]))
        self.assertFalse(is_resume(["-p", "fix it"]))


class TestRegistry(unittest.TestCase):
    def test_record_is_owner_only_jsonl(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "crew-chief" / "code-sessions.jsonl"
            record_session(path, "s1", "ollama", "http://x", "qwen3:14b", "/repo")
            record_session(path, "s2", "llamacpp", "http://y", "q", "/repo")
            lines = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([e["session_id"] for e in lines], ["s1", "s2"])
            self.assertEqual(lines[0]["model"], "qwen3:14b")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class TestLaunch(unittest.TestCase):
    def _launch(self, passthrough):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_STATE_HOME": tmp}):
            with (
                patch.object(code_launcher.shutil, "which", return_value="/bin/claude"),
                patch.object(code_launcher, "check_model"),
                patch.object(code_launcher.os, "execvpe") as execvpe,
            ):
                launch("ollama", "http://x/", "qwen3:14b", 32768, passthrough)
            registry = Path(tmp) / "crew-chief" / "code-sessions.jsonl"
            entries = registry.read_text().splitlines() if registry.exists() else []
            return execvpe.call_args.args, entries

    def test_new_session_is_recorded_with_pinned_id(self):
        (prog, argv, env), entries = self._launch([])
        self.assertEqual(prog, "claude")
        self.assertEqual(len(entries), 1)
        session_id = json.loads(entries[0])["session_id"]
        self.assertEqual(argv[argv.index("--session-id") + 1], session_id)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://x")

    def test_resume_is_not_recorded_again(self):
        (_, argv, _), entries = self._launch(["--resume", "abc"])
        self.assertNotIn("--session-id", argv)
        self.assertEqual(entries, [])

    def test_missing_claude(self):
        with patch.object(code_launcher.shutil, "which", return_value=None):
            with self.assertRaisesRegex(LaunchError, "not on PATH"):
                launch("ollama", "http://x", "m", 1, [])


class TestCliParsing(unittest.TestCase):
    def test_passthrough_after_double_dash(self):
        args = build_parser().parse_args(["code", "-m", "qwen3:32b", "--", "--resume", "abc"])
        self.assertEqual(args.code_model, "qwen3:32b")
        self.assertEqual(args.claude_args, ["--", "--resume", "abc"])


if __name__ == "__main__":
    unittest.main()


def _ecu_on_path(name):
    return "/usr/bin/ecu" if name == "ecu" else None


class TestLease(unittest.TestCase):
    def test_a_measured_ollama_model_is_leased_through_ecu_run(self):
        prefix = lease_prefix("qwen3:14b", "ollama", 14024, which=_ecu_on_path, environ={})
        self.assertEqual(prefix[:4], ["/usr/bin/ecu", "run", "--model", "qwen3:14b"])
        self.assertIn("--policy", prefix)
        self.assertEqual(prefix[prefix.index("--priority") + 1], "interactive")
        self.assertEqual(prefix[-1], "--")

    def test_there_is_no_lease_when_nothing_safe_can_be_asked_for(self):
        cases = {
            "unmeasured model": ("ollama", None, _ecu_on_path, {}),
            "zero size": ("ollama", 0, _ecu_on_path, {}),
            "llama.cpp holds its memory first": ("llamacpp", 23740, _ecu_on_path, {}),
            "no ecu on PATH": ("ollama", 14024, lambda _name: None, {}),
            "already inside a lease": ("ollama", 14024, _ecu_on_path, {LEASE_ENV: "1"}),
            "opted out": ("ollama", 14024, _ecu_on_path, {"CREW_CHIEF_NO_LEASE": "1"}),
        }
        for label, (backend, size, which, environ) in cases.items():
            with self.subTest(label):
                self.assertIsNone(lease_prefix("m", backend, size, which=which, environ=environ))

    def test_policy_gpu_mib_reads_the_measured_size_and_never_raises(self):
        class Entry:
            gpu_mib = 14024

        class Policy:
            def __init__(self, entry):
                self.entry = entry

            def get(self, _model):
                return self.entry

        self.assertEqual(policy_gpu_mib("m", lambda: Policy(Entry())), 14024)
        self.assertIsNone(policy_gpu_mib("m", lambda: Policy(None)))

        class Unmeasured:
            gpu_mib = None

        self.assertIsNone(policy_gpu_mib("m", lambda: Policy(Unmeasured())))

        from crew_chief.serving_policy import PolicyError

        def broken():
            raise PolicyError("unreadable")

        self.assertIsNone(policy_gpu_mib("m", broken))

    def _launch(self, gpu_mib, environ=None):
        env = {"CREW_CHIEF_NO_LEASE": "", **(environ or {})}
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_STATE_HOME": tmp, **env}):
            with (
                patch.object(code_launcher.shutil, "which", return_value="/usr/bin/tool"),
                patch.object(code_launcher, "check_model"),
                patch.object(code_launcher.os, "execvpe") as execvpe,
            ):
                launch("ollama", "http://x/", "qwen3:14b", 32768, [], gpu_mib=gpu_mib)
        return execvpe.call_args.args

    def test_launch_runs_claude_inside_the_lease_and_marks_the_environment(self):
        prog, argv, env = self._launch(14024)

        self.assertEqual(prog, "/usr/bin/tool")  # the mocked `ecu` on PATH
        self.assertEqual(argv[1:3], ["run", "--model"])
        split = argv.index("--")
        self.assertEqual(argv[split + 1], "claude")  # the session itself follows the prefix
        self.assertEqual(env[LEASE_ENV], "1")

    def test_launch_without_a_size_execs_claude_directly_as_before(self):
        prog, argv, env = self._launch(None)
        self.assertEqual(prog, "claude")
        self.assertNotIn(LEASE_ENV, env)

    def test_no_lease_env_opts_out_at_launch(self):
        prog, _, _ = self._launch(14024, {"CREW_CHIEF_NO_LEASE": "1"})
        self.assertEqual(prog, "claude")

    def test_the_parser_accepts_no_lease(self):
        args = build_parser().parse_args(["code", "--no-lease"])
        self.assertTrue(args.no_lease)
        self.assertFalse(build_parser().parse_args(["code"]).no_lease)
