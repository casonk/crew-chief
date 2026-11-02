"""Tests for crew_chief.cli — every command is driven through ``main()`` and fully offline.

The CLI is thin wiring, so the things worth pinning are the decisions it makes: which
collaborator it calls with what, which failure becomes which exit status, and what it
refuses to do. Collaborators are patched at the module the CLI imports them from; nothing
here touches the real serving policy, the storage state file, the network, a subprocess
or the real home directory.
"""

from __future__ import annotations

import contextlib
import io
import json
import runpy
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from crew_chief import cli
from crew_chief import model_storage as ms
from crew_chief.client import DEFAULT_BASE_URL
from crew_chief.serving_policy import (
    ModelPolicy,
    PolicyError,
    ServingPolicy,
    TaskPolicy,
)


def run(*argv: str):
    """Run ``main`` and return (exit status or None, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    status = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as exc:
            status = exc.code if exc.code is not None else 0
    return status, out.getvalue(), err.getvalue()


class CliCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = mock.MagicMock()
        patcher = mock.patch.object(cli, "CrewChiefClient", return_value=self.client)
        self.client_class = patcher.start()
        self.addCleanup(patcher.stop)
        # logging.basicConfig would reconfigure the test runner's logging for everyone
        patcher = mock.patch.object(cli.logging, "basicConfig")
        self.basic_config = patcher.start()
        self.addCleanup(patcher.stop)

    def patch(self, target: str, *args, **kwargs):
        patcher = mock.patch(target, *args, **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started


class ParserTests(unittest.TestCase):
    def test_a_command_is_required(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cli.build_parser().parse_args([])
        self.assertEqual(raised.exception.code, 2)

    def test_short_aliases_name_the_same_commands(self) -> None:
        parser = cli.build_parser()
        self.assertEqual(parser.parse_args(["g", "hi"]).prompt, "hi")
        for alias in ("h", "m"):
            self.assertEqual(parser.parse_args([alias]).command, alias)
        self.assertEqual(parser.parse_args(["l", "--config", "c.toml"]).config, "c.toml")
        self.assertEqual(parser.parse_args(["a", "task"]).prompt, "task")
        self.assertEqual(parser.parse_args(["c"]).command, "c")

    def test_global_options_have_defaults_and_can_be_overridden(self) -> None:
        parser = cli.build_parser()
        self.assertEqual(parser.parse_args(["health"]).url, DEFAULT_BASE_URL)
        args = parser.parse_args(
            ["--url", "http://h:1", "--timeout", "3", "--model", "m", "models"]
        )
        self.assertEqual((args.url, args.timeout, args.model), ("http://h:1", 3, "m"))

    def test_listen_requires_a_config_and_validates_the_log_level(self) -> None:
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in (["listen"], ["listen", "--config", "c", "--log-level", "LOUD"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    parser.parse_args(argv)

    def test_taskbench_needs_a_runner_and_a_known_split(self) -> None:
        parser = cli.build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in (
                ["taskbench", "t.json"],
                ["taskbench", "t.json", "--runner", "r", "--split", "x"],
            ):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    parser.parse_args(argv)
        args = parser.parse_args(["taskbench", "t.json", "--runner", "a", "--runner", "b"])
        self.assertEqual((args.runner, args.split), (["a", "b"], "test"))

    def test_the_old_split_names_are_still_accepted(self) -> None:
        parser = cli.build_parser()
        for name in ("dev", "heldout"):
            self.assertEqual(
                parser.parse_args(["taskbench", "t", "--runner", "r", "--split", name]).split, name
            )


class SimpleCommandTests(CliCase):
    def test_generate_prints_the_response(self) -> None:
        self.client.generate.return_value = "an answer"
        status, out, _ = run("generate", "a question")
        self.assertIsNone(status)
        self.assertEqual(out, "an answer\n")
        self.client.generate.assert_called_once_with("a question")

    def test_the_global_options_build_the_client(self) -> None:
        run("--url", "http://h:1", "--model", "m", "--timeout", "7", "generate", "p")
        self.client_class.assert_called_once_with(base_url="http://h:1", model="m", timeout=7)

    def test_health_exit_status_follows_reachability(self) -> None:
        for reachable, text, status in ((True, "ok", 0), (False, "unreachable", 1)):
            self.client.health.return_value = reachable
            with self.subTest(reachable=reachable):
                code, out, _ = run("health")
                self.assertEqual((code, out.strip()), (status, text))

    def test_models_lists_one_per_line(self) -> None:
        self.client.list_models.return_value = ["a:1", "b:2"]
        self.assertEqual(run("models")[1], "a:1\nb:2\n")

    def test_module_entry_point_runs_main(self) -> None:
        with mock.patch("crew_chief.cli.main") as main:
            runpy.run_module("crew_chief", run_name="__main__")
        main.assert_called_once_with()


class ListenTests(CliCase):
    def test_a_bad_config_exits_2_without_starting_the_listener(self) -> None:
        from crew_chief.config_loader import ConfigError

        self.patch("crew_chief.config_loader.load", side_effect=ConfigError("no such file"))
        listener = self.patch("crew_chief.listener.run")
        status, _, err = run("listen", "--config", "x.toml")
        self.assertEqual(status, 2)
        self.assertIn("Error: no such file", err)
        listener.assert_not_called()

    def test_a_good_config_starts_the_listener_and_honours_once(self) -> None:
        load = self.patch("crew_chief.config_loader.load", return_value="CFG")
        listener = self.patch("crew_chief.listener.run")
        run("listen", "--config", "x.toml", "--once", "--log-level", "DEBUG")
        load.assert_called_once_with("x.toml")
        listener.assert_called_once_with("CFG", once=True)
        self.assertEqual(self.basic_config.call_args.kwargs["level"], cli.logging.DEBUG)
        run("l", "--config", "x.toml")
        listener.assert_called_with("CFG", once=False)


class CodeTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.launch = self.patch("crew_chief.code_launcher.launch")
        self.resolve = self.patch(
            "crew_chief.code_launcher.resolve_serving",
            return_value=("ollama", "http://base", 32768, ["using the policy"]),
        )
        self.gpu = self.patch("crew_chief.code_launcher.policy_gpu_mib", return_value=1234)

    def test_list_prints_the_tool_capable_models_and_launches_nothing(self) -> None:
        models = self.patch("crew_chief.code_launcher.ollama_tool_models", return_value=["a", "b"])
        status, out, _ = run("--url", "http://h:1/", "code", "--list")
        self.assertIsNone(status)
        self.assertEqual(out, "a\nb\n")
        models.assert_called_once_with("http://h:1")
        self.launch.assert_not_called()

    def test_launch_gets_what_the_policy_resolved(self) -> None:
        _, _, err = run("code", "-m", "qwen3:14b", "--backend", "llamacpp", "--context", "8192")
        self.resolve.assert_called_once_with(
            "qwen3:14b", backend="llamacpp", url=None, context=8192
        )
        self.assertIn("crew-chief: using the policy", err)
        self.launch.assert_called_once_with(
            backend="ollama",
            base_url="http://base",
            model="qwen3:14b",
            context=32768,
            passthrough=[],
            skip_check=False,
            gpu_mib=1234,
        )

    def test_only_a_non_default_url_overrides_the_policy(self) -> None:
        run("--url", "http://h:1", "code")
        self.assertEqual(self.resolve.call_args.kwargs["url"], "http://h:1")
        run("code")
        self.assertIsNone(self.resolve.call_args.kwargs["url"])

    def test_arguments_after_the_separator_go_to_claude(self) -> None:
        run("code", "--", "--resume", "abc")
        self.assertEqual(self.launch.call_args.kwargs["passthrough"], ["--resume", "abc"])

    def test_no_lease_and_skip_check_are_passed_through(self) -> None:
        run("code", "--no-lease", "--skip-check")
        kwargs = self.launch.call_args.kwargs
        self.assertIsNone(kwargs["gpu_mib"])
        self.assertTrue(kwargs["skip_check"])
        self.gpu.assert_not_called()

    def test_a_launch_error_exits_2(self) -> None:
        from crew_chief.code_launcher import LaunchError

        self.launch.side_effect = LaunchError("server unreachable")
        status, _, err = run("code")
        self.assertEqual(status, 2)
        self.assertIn("Error: server unreachable", err)


class ScoringProfileTests(unittest.TestCase):
    def args(self, **kwargs):
        return SimpleNamespace(no_score=False, profiles=None, **kwargs)

    def test_no_score_skips_loading_entirely(self) -> None:
        with mock.patch("crew_chief.scoring.load_profiles") as load:
            self.assertEqual(
                cli._scoring_profiles(SimpleNamespace(no_score=True, profiles="x")), []
            )
        load.assert_not_called()

    def test_an_explicit_profile_file_must_load(self) -> None:
        from crew_chief import scoring

        with mock.patch("crew_chief.scoring.load_profiles", return_value=["p"]) as load:
            self.assertEqual(
                cli._scoring_profiles(SimpleNamespace(no_score=False, profiles="p.toml")), ["p"]
            )
        self.assertEqual(load.call_args.args, (Path("p.toml"),))
        with (
            mock.patch("crew_chief.scoring.load_profiles", side_effect=scoring.ScoringError("bad")),
            contextlib.redirect_stderr(io.StringIO()) as err,
            self.assertRaises(SystemExit) as raised,
        ):
            cli._scoring_profiles(SimpleNamespace(no_score=False, profiles="p.toml"))
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Error: bad", err.getvalue())

    def test_the_default_file_is_optional(self) -> None:
        from crew_chief import scoring

        with mock.patch("crew_chief.scoring.load_profiles", side_effect=scoring.ScoringError("x")):
            self.assertEqual(cli._scoring_profiles(self.args()), [])
        with mock.patch("crew_chief.scoring.load_profiles", return_value=["d"]) as load:
            self.assertEqual(cli._scoring_profiles(self.args()), ["d"])
        load.assert_called_once_with()


class FakeTask:
    name = "Message Routing"
    split = "test"
    zero_shot = False

    def __init__(self, zero_shot: bool = False) -> None:
        self.zero_shot = zero_shot
        self.items = [1, 2, 3]
        self.examples = [1, 2]

    def select(self, split):
        self.split = split
        return self

    def without_examples(self):
        return FakeTask(zero_shot=True)


class TaskbenchTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "nested" / "results"
        self.task = FakeTask()
        self.load_task = self.patch("crew_chief.taskbench.load_task", return_value=self.task)
        self.runner = SimpleNamespace(name="rules")
        self.make_runner = self.patch("crew_chief.taskbench.make_runner", return_value=self.runner)
        self.bench_run = self.patch("crew_chief.taskbench.run", return_value={"accuracy": 1.0})
        self.render = self.patch("crew_chief.taskbench.render_markdown", return_value="# report\n")
        self.patch("crew_chief.cli._scoring_profiles", return_value=["profile"])

    def written(self):
        return sorted(p.name for p in self.out.iterdir())

    def test_a_run_saves_markdown_and_json_named_for_the_task_and_split(self) -> None:
        status, out, err = run("taskbench", "t.json", "--runner", "rules", "--out", str(self.out))
        self.assertIsNone(status)
        names = self.written()
        self.assertEqual(len(names), 2)
        for name in names:
            self.assertTrue(name.startswith("taskbench-message-routing-test-"), name)
        self.assertEqual(sorted(Path(n).suffix for n in names), [".json", ".md"])
        self.assertIn("# report", out)
        self.assertIn("running rules on 3 test items (2 train examples in the prompt)", err)
        saved = next(p for p in self.out.iterdir() if p.suffix == ".json")
        self.assertEqual(json.loads(saved.read_text()), [{"accuracy": 1.0}])
        self.render.assert_called_once()
        self.assertEqual(self.render.call_args.args[3], ["profile"])

    def test_every_runner_is_run_in_order(self) -> None:
        self.make_runner.side_effect = lambda spec, task: SimpleNamespace(name=spec)
        run("taskbench", "t.json", "--runner", "a", "--runner", "b", "--out", str(self.out))
        self.assertEqual([c.args[1].name for c in self.bench_run.call_args_list], ["a", "b"])

    def test_zero_shot_is_recorded_in_the_file_name_and_the_message(self) -> None:
        _, _, err = run(
            "taskbench", "t.json", "--runner", "r", "--zero-shot", "--out", str(self.out)
        )
        self.assertIn("zero-shot", err)
        self.assertTrue(all("-zeroshot-" in n for n in self.written()), self.written())

    def test_the_split_selects_the_items(self) -> None:
        run("taskbench", "t.json", "--runner", "r", "--split", "train", "--out", str(self.out))
        self.assertEqual(self.task.split, "train")
        self.assertTrue(all("-train-" in n for n in self.written()))

    def test_a_task_error_exits_2_and_writes_nothing(self) -> None:
        from crew_chief import taskbench as tb

        self.load_task.side_effect = tb.TaskError("not a task file")
        status, _, err = run("taskbench", "t.json", "--runner", "r", "--out", str(self.out))
        self.assertEqual(status, 2)
        self.assertIn("Error: not a task file", err)
        self.assertFalse(self.out.exists())

    def test_an_unknown_runner_exits_2(self) -> None:
        from crew_chief import taskbench as tb

        self.make_runner.side_effect = tb.TaskError("no such runner: x")
        status, _, err = run("taskbench", "t.json", "--runner", "x", "--out", str(self.out))
        self.assertEqual(status, 2)
        self.assertIn("no such runner", err)


class RoutebenchTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "results"
        self.patch("crew_chief.taskbench.load_task", side_effect=lambda p: f"task:{p}")
        self.patch("crew_chief.taskbench.make_runner", return_value=SimpleNamespace(name="router"))
        self.bench = self.patch("crew_chief.routerbench.run_benchmark", return_value="RESULT")
        self.patch("crew_chief.routerbench.render_svg", return_value="<svg/>")
        self.markdown = self.patch("crew_chief.routerbench.render_markdown", return_value="# md\n")
        self.patch("crew_chief.routerbench.to_json", return_value='{"r": 1}\n')
        self.patch("crew_chief.cli._scoring_profiles", return_value=[])

    def test_defaults_cover_the_installed_models_and_thresholds(self) -> None:
        status, out, err = run("routebench", "a.json", "b.json", "--out", str(self.out))
        self.assertIsNone(status)
        tasks, candidates, router = self.bench.call_args.args
        self.assertEqual(tasks, ["task:a.json", "task:b.json"])
        self.assertEqual(
            candidates,
            [f"systemone:{m}" for m in ("tev1", "clef-flash", "nimble", "clef")],
        )
        self.assertEqual(self.bench.call_args.kwargs["thresholds"], (0.6, 0.8, 0.95))
        self.assertIn("routing with router over 4 candidates", err)
        self.assertIn("# md", out)

    def test_explicit_candidates_and_thresholds_replace_the_defaults(self) -> None:
        run(
            "routebench", "a.json", "--candidate", "ollama:x", "--threshold", "0.5",
            "--threshold", "0.9", "--out", str(self.out),
        )  # fmt: skip
        self.assertEqual(self.bench.call_args.args[1], ["ollama:x"])
        self.assertEqual(self.bench.call_args.kwargs["thresholds"], (0.5, 0.9))

    def test_three_files_are_written_and_the_markdown_links_the_chart(self) -> None:
        run("routebench", "a.json", "--out", str(self.out))
        by_suffix = {p.suffix: p for p in self.out.iterdir()}
        self.assertEqual(set(by_suffix), {".md", ".svg", ".json"})
        self.assertEqual(by_suffix[".svg"].read_text(), "<svg/>")
        self.assertEqual(self.markdown.call_args.kwargs["chart"], by_suffix[".svg"].name)

    def test_a_route_error_exits_2_without_writing(self) -> None:
        from crew_chief import routerbench as rb

        self.bench.side_effect = rb.RouteError("no held-out items")
        status, _, err = run("routebench", "a.json", "--out", str(self.out))
        self.assertEqual(status, 2)
        self.assertIn("no held-out items", err)
        self.assertFalse(self.out.exists())


class BenchuiTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.server = mock.MagicMock()
        self.server.serve_forever.side_effect = KeyboardInterrupt
        self.make_server = self.patch("crew_chief.benchui.make_server", return_value=self.server)

    def test_a_non_loopback_address_is_refused_before_binding(self) -> None:
        for host in ("0.0.0.0", "192.168.1.5", "example.com"):
            with self.subTest(host=host):
                status, _, err = run("benchui", "--host", host)
                self.assertEqual(status, 2)
                self.assertIn("loopback", err)
        self.make_server.assert_not_called()

    def test_loopback_addresses_and_localhost_are_served(self) -> None:
        for host in ("127.0.0.1", "::1", "localhost"):
            with self.subTest(host=host):
                status, _, err = run("benchui", "--host", host, "--port", "9000")
                self.assertIsNone(status)
                self.assertIn(f"http://{host}:9000/", err)
        self.assertEqual(self.make_server.call_args.args[2:4], ("localhost", 9000))

    def test_ctrl_c_stops_the_server_and_shuts_the_job_runner_down(self) -> None:
        run("benchui")
        self.server.serve_forever.assert_called_once_with()
        self.server.RequestHandlerClass.app.jobs.shutdown.assert_called_once_with()

    def test_the_job_runner_is_shut_down_even_if_serving_fails(self) -> None:
        self.server.serve_forever.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            run("benchui")
        self.server.RequestHandlerClass.app.jobs.shutdown.assert_called_once_with()

    def test_allowed_hosts_merge_flags_and_the_environment_without_blanks(self) -> None:
        with mock.patch.dict("os.environ", {"CREW_CHIEF_BENCH_HOSTS": " a.test, ,b.test,"}):
            run("benchui", "--allow-host", "c.test", "--allow-host", "  ")
        self.assertEqual(self.make_server.call_args.args[4], ("c.test", "a.test", "b.test"))

    def test_directories_default_when_not_given(self) -> None:
        from crew_chief import benchui

        run("benchui")
        state, results = self.make_server.call_args.args[:2]
        self.assertEqual(state, benchui.DEFAULT_STATE)
        self.assertEqual(results, benchui.REPO_ROOT / "results")
        run("benchui", "--state-dir", "/s", "--results-dir", "/r")
        self.assertEqual(self.make_server.call_args.args[:2], (Path("/s"), Path("/r")))


def _policy(**kwargs) -> ServingPolicy:
    models = {
        "qwen3:14b": ModelPolicy(name="qwen3:14b", status="unreviewed", note="small"),
        "qwen3:32b": ModelPolicy(name="qwen3:32b", backend="llamacpp", gpu_mib=22000),
    }
    tasks = {"route": TaskPolicy(name="route", model="qwen3:14b", fallback=("qwen3:32b",))}
    return ServingPolicy(models=models, tasks=tasks, **kwargs)


class ServeTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.policy = _policy()
        self.patch("crew_chief.serving_policy.load_policy", return_value=self.policy)
        self.plan = self.patch("crew_chief.serve.plan", return_value=["podman", "run", "x"])
        self.serve = self.patch("crew_chief.serve.serve")

    def test_several_models_need_swap(self) -> None:
        status, _, err = run("serve", "a", "b")
        self.assertEqual(status, 2)
        self.assertIn("--swap", err)
        self.plan.assert_not_called()

    def test_dry_run_prints_the_command_and_starts_nothing(self) -> None:
        status, out, _ = run("serve", "qwen3:32b", "--dry-run")
        self.assertIsNone(status)
        self.assertEqual(out.strip(), "podman run x")
        self.serve.assert_not_called()
        self.assertEqual(self.plan.call_args.args[0], "qwen3:32b")
        self.assertEqual(self.plan.call_args.args[2], "http://localhost:8081")

    def test_serving_runs_under_a_lease_unless_told_not_to(self) -> None:
        run("serve", "qwen3:32b")
        self.serve.assert_called_once_with(["podman", "run", "x"], "qwen3:32b", 22000, leased=True)
        run("serve", "qwen3:32b", "--no-lease")
        self.assertIs(self.serve.call_args.kwargs["leased"], False)

    def test_a_model_the_backend_loads_on_demand_needs_nothing_started(self) -> None:
        self.plan.return_value = None
        status, out, _ = run("serve", "qwen3:14b")
        self.assertIsNone(status)
        self.assertIn("qwen3:14b is served by ollama", out)
        self.serve.assert_not_called()

    def test_policy_and_serve_errors_exit_2(self) -> None:
        from crew_chief.serve import ServeError

        for error in (PolicyError("no policy"), ServeError("no blob")):
            self.plan.side_effect = error
            with self.subTest(error=error):
                status, _, err = run("serve", "qwen3:32b")
                self.assertEqual(status, 2)
                self.assertIn(str(error), err)


class ServeSwapTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.patch("crew_chief.serving_policy.load_policy", return_value=_policy())
        entry = lambda mib: ModelPolicy(name="m", gpu_mib=mib)  # noqa: E731
        self.models = [("a", entry(8000), Path("a"), None), ("b", entry(None), Path("b"), None)]
        self.plan_swap = self.patch("crew_chief.serve.plan_swap", return_value=self.models)
        self.config = self.patch("crew_chief.serve.swap_config", return_value="models: {}\n")
        self.argv = self.patch("crew_chief.serve.swap_argv", return_value=["llama-swap"])
        self.serve = self.patch("crew_chief.serve.serve")
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch("pathlib.Path.home", return_value=Path(self.tmp.name))

    def test_dry_run_prints_the_config_and_writes_nothing(self) -> None:
        status, out, _ = run("serve", "--swap", "a", "b", "--dry-run", "--ttl", "60")
        self.assertIsNone(status)
        self.assertEqual(out, "models: {}\n")
        self.config.assert_called_once_with(self.models, 60)
        self.serve.assert_not_called()
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_a_real_run_writes_the_config_under_home_and_leases_the_largest_model(self) -> None:
        status, _, err = run("serve", "--swap", "a", "b", "--port", "9001")
        self.assertIsNone(status)
        path = Path(self.tmp.name) / ".cache" / "crew-chief" / "llama-swap.yaml"
        self.assertEqual(path.read_text(), "models: {}\n")
        self.argv.assert_called_once_with(self.models, path, 9001)
        self.serve.assert_called_once_with(["llama-swap"], "llama-swap", 8000, leased=True)
        self.assertIn("llama-swap on 127.0.0.1:9001 for 2 model(s)", err)

    def test_no_lease_is_honoured(self) -> None:
        run("serve", "--swap", "a", "--no-lease")
        self.assertIs(self.serve.call_args.kwargs["leased"], False)

    def test_an_unplannable_swap_exits_2(self) -> None:
        self.plan_swap.side_effect = PolicyError("a is not in the policy")
        status, _, err = run("serve", "--swap", "a", "--dry-run")
        self.assertEqual(status, 2)
        self.assertIn("not in the policy", err)


class PolicyTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.policy = _policy()
        self.load = self.patch("crew_chief.serving_policy.load_policy", return_value=self.policy)

    def test_show_lists_every_model_or_one(self) -> None:
        _, out, _ = run("policy", "show")
        self.assertIn("qwen3:14b: unreviewed, ollama", out)
        self.assertIn("qwen3:32b: unreviewed, llamacpp", out)
        _, out, _ = run("policy", "show", "qwen3:32b")
        self.assertNotIn("qwen3:14b", out)
        self.assertIn("22000 MiB", out)

    def test_an_unknown_model_exits_1(self) -> None:
        status, out, err = run("policy", "show", "nope:1b")
        self.assertEqual(status, 1)
        self.assertEqual(out, "")
        self.assertIn("nope:1b: not in the serving policy", err)

    def test_task_shows_one_task_or_all_of_them(self) -> None:
        _, out, _ = run("policy", "show", "--task", "route")
        self.assertIn("task route: unreviewed, chat", out)
        self.assertIn("qwen3:14b -> qwen3:32b", out)
        _, out, _ = run("policy", "show", "--task")
        self.assertIn("task route", out)

    def test_an_unknown_task_exits_1(self) -> None:
        status, _, err = run("policy", "show", "--task", "nope")
        self.assertEqual(status, 1)
        self.assertIn("nope: not a task in the serving policy", err)

    def test_check_reports_counts_and_exits_by_errors(self) -> None:
        for errors, warnings, status in (([], [], 0), ([], ["w"], 0), (["e"], ["w"], 1)):
            with (
                self.subTest(errors=errors),
                mock.patch("crew_chief.serving_policy.review", return_value=(errors, warnings)),
            ):
                code, out, _ = run("policy", "check")
                self.assertEqual(code, status)
                self.assertIn(
                    f"serving policy: {len(errors)} error(s), {len(warnings)} warning(s)", out
                )
                lines = out.splitlines()
                self.assertEqual(sum(line.startswith("warning: ") for line in lines), len(warnings))
                self.assertEqual(sum(line.startswith("error: ") for line in lines), len(errors))

    def test_a_default_model_without_evidence_fails_the_real_review(self) -> None:
        self.load.return_value = ServingPolicy(
            models={"m": ModelPolicy(name="m", status="default")}
        )
        status, out, _ = run("policy", "check")
        self.assertEqual(status, 1)
        self.assertRegex(out, r"error: .*m")

    def test_check_without_live_does_not_look_at_ollama_or_storage(self) -> None:
        pulled = self.patch("crew_chief.serving_policy.pulled_models")
        below = self.patch("crew_chief.cli._below_hot")
        run("policy", "check")
        pulled.assert_not_called()
        below.assert_not_called()

    def test_live_compares_against_the_pulled_models_and_storage_tiers(self) -> None:
        pulled = self.patch("crew_chief.serving_policy.pulled_models", return_value=["qwen3:14b"])
        self.patch("crew_chief.cli._below_hot", return_value={"x": "warm"})
        review = self.patch("crew_chief.serving_policy.review", return_value=([], []))
        run("policy", "check", "--live")
        pulled.assert_called_once_with("http://localhost:11434")
        self.assertEqual(
            review.call_args.kwargs, {"pulled": ["qwen3:14b"], "below_hot": {"x": "warm"}}
        )

    def test_an_unreadable_policy_exits_2(self) -> None:
        self.load.side_effect = PolicyError("serving policy not found")
        for argv in (["policy", "check"], ["policy", "show"]):
            with self.subTest(argv=argv):
                status, _, err = run(*argv)
                self.assertEqual(status, 2)
                self.assertIn("serving policy not found", err)

    def test_an_unreachable_ollama_on_a_live_check_exits_2(self) -> None:
        self.patch(
            "crew_chief.serving_policy.pulled_models",
            side_effect=PolicyError("Ollama is not reachable"),
        )
        status, _, err = run("policy", "check", "--live")
        self.assertEqual(status, 2)
        self.assertIn("not reachable", err)


class BelowHotTests(unittest.TestCase):
    def test_only_models_below_hot_are_reported(self) -> None:
        with (
            mock.patch.object(ms, "load_tiers", return_value={}),
            mock.patch.object(ms, "locate", return_value={"a": "hot", "b": "warm", "c": "cold"}),
        ):
            self.assertEqual(cli._below_hot(), {"b": "warm", "c": "cold"})

    def test_unconfigured_tiers_mean_none(self) -> None:
        with mock.patch.object(ms, "load_tiers", side_effect=ms.StorageError("no tiers")):
            self.assertIsNone(cli._below_hot())


class GgufTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        from crew_chief import gguf_sources as gs

        self.gs = gs
        self.sources = {
            "m1:latest": gs.GgufSource("m1:latest", "org/repo", "m1.gguf", "0" * 64, 10),
            "m2:latest": gs.GgufSource("m2:latest", "org/repo", "m2.gguf", "1" * 64, 20),
        }
        self.patch("crew_chief.gguf_sources.load_sources", return_value=self.sources)
        self.tiers = {"hot": Path("/h"), "warm": Path("/w"), "cold": Path("/c")}
        self.patch("crew_chief.model_storage.load_tiers", return_value=self.tiers)
        self.where = {"m2:latest": "warm"}
        self.patch("crew_chief.model_storage.locate", return_value=self.where)
        self.find = self.patch("crew_chief.gguf_sources.find", return_value=None)
        self.fetch = self.patch("crew_chief.gguf_sources.fetch", return_value=Path("/x/m.gguf"))
        self.dir = self.patch(
            "crew_chief.gguf_sources.gguf_dir", side_effect=lambda t, tiers: Path(f"/g/{t}")
        )

    def test_list_shows_each_model_and_where_it_is(self) -> None:
        self.find.side_effect = lambda source, tiers: (
            Path("/g/m1.gguf") if source.model == "m1:latest" else None
        )
        status, out, _ = run("gguf", "list")
        self.assertEqual(status, 0)
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("m1") and lines[0].endswith("/g/m1.gguf"))
        self.assertTrue(lines[1].startswith("m2") and lines[1].endswith("not downloaded"))
        self.fetch.assert_not_called()

    def test_fetch_downloads_into_the_tier_the_model_lives_on(self) -> None:
        status, out, _ = run("gguf", "fetch")
        self.assertEqual(status, 0)
        self.assertEqual(out.count("verified"), 2)
        dirs = {c.args[0].model: c.args[1] for c in self.fetch.call_args_list}
        self.assertEqual(dirs, {"m1:latest": Path("/g/hot"), "m2:latest": Path("/g/warm")})

    def test_fetch_skips_what_is_already_downloaded(self) -> None:
        self.find.return_value = Path("/g/have.gguf")
        status, out, _ = run("gguf", "fetch")
        self.assertEqual(status, 0)
        self.assertEqual(out, "")
        self.fetch.assert_not_called()

    def test_fetch_can_be_limited_to_named_models(self) -> None:
        run("gguf", "fetch", "m2")
        self.assertEqual([c.args[0].model for c in self.fetch.call_args_list], ["m2:latest"])

    def test_an_unknown_model_exits_2_before_downloading(self) -> None:
        status, _, err = run("gguf", "fetch", "m1", "ghost")
        self.assertEqual(status, 2)
        self.assertIn("not in gguf-sources.toml: ghost:latest", err)
        self.fetch.assert_not_called()

    def test_a_failed_download_is_reported_and_fails_the_run_but_not_the_others(self) -> None:
        def fetch(source, directory):
            if source.model == "m1:latest":
                raise self.gs.SourceError("checksum mismatch")
            return Path("/x/ok.gguf")

        self.fetch.side_effect = fetch
        status, out, err = run("gguf", "fetch")
        self.assertEqual(status, 1)
        self.assertIn("m1:latest: checksum mismatch", err)
        self.assertIn("m2:latest: verified", out)

    def test_an_os_error_during_download_is_also_a_failure(self) -> None:
        self.fetch.side_effect = OSError("disk full")
        status, _, err = run("gguf", "fetch", "m1")
        self.assertEqual(status, 1)
        self.assertIn("disk full", err)

    def test_an_unreadable_sources_file_exits_2(self) -> None:
        self.patch(
            "crew_chief.gguf_sources.load_sources", side_effect=self.gs.SourceError("bad toml")
        )
        status, _, err = run("gguf", "list")
        self.assertEqual(status, 2)
        self.assertIn("Error: bad toml", err)

    def test_without_storage_tiers_everything_is_treated_as_hot(self) -> None:
        self.patch("crew_chief.model_storage.load_tiers", side_effect=ms.StorageError("none"))
        run("gguf", "fetch", "m2")
        self.assertEqual(self.dir.call_args.args, ("hot", None))
        self.assertEqual(self.find.call_args.args[1], None)


TODAY = date.today()


def _add_model(models_dir: Path, name: str) -> None:
    """A minimal Ollama manifest so ``model_storage.locate`` finds the model."""
    blob = models_dir / "blobs" / f"sha256-{name.replace(':', '_')}"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"weights")
    manifest = {
        "config": {"digest": f"sha256:{name.replace(':', '_')}"},
        "layers": [],
    }
    path = ms.manifest_path(models_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


class StorageTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.tiers = {t: root / t for t in ("hot", "warm", "cold")}
        self.policy = ServingPolicy(
            models={
                "live:1b": ModelPolicy(name="live:1b", status="default"),
                "old:1b": ModelPolicy(name="old:1b", status="retired"),
                "dm:1b": ModelPolicy(name="dm:1b", role="system1"),
                "gone:1b": ModelPolicy(name="gone:1b", role="system1", status="retired"),
            }
        )
        self.state: dict[str, dict] = {}
        self.patch("crew_chief.serving_policy.load_policy", return_value=self.policy)
        self.patch("crew_chief.model_storage.load_tiers", return_value=self.tiers)
        self.patch("crew_chief.model_storage.load_state", side_effect=lambda: self.state)
        self.save = self.patch("crew_chief.model_storage.save_state")
        self.execute = self.patch("crew_chief.model_storage.execute", return_value=2 * 2**30)
        self.repair = self.patch("crew_chief.model_storage.repair", return_value=[])
        self.unload = self.patch("crew_chief.model_storage.unload")
        self.run_process = self.patch("subprocess.run", return_value=SimpleNamespace(returncode=0))

    def final_state(self) -> dict[str, dict]:
        """The state the command last saved: it works on its own synced copy."""
        return self.save.call_args.args[0]

    def put(self, tier: str, name: str, **entry) -> None:
        _add_model(self.tiers[tier], name)
        if entry:
            self.state[name] = {"tier": tier, **entry}

    def test_status_describes_each_model_by_tier_and_flags_unlinked_ones(self) -> None:
        self.put("hot", "live:1b")
        self.put("warm", "old:1b", since="2026-01-01", last_benched="2026-02-01")
        self.put("hot", "stray:7b")
        status, out, _ = run("storage", "status")
        self.assertIsNone(status)
        lines = {line.split()[1]: line for line in out.splitlines()}
        self.assertIn("weekly timer", lines["live:1b"])
        self.assertIn("default", lines["live:1b"])
        self.assertIn("unlisted", lines["stray:7b"])
        self.assertIn("retired", lines["old:1b"])
        self.assertIn("bench every 30 d, last 2026-02-01", lines["old:1b"])
        self.assertTrue(lines["old:1b"].endswith("NOT LINKED"))
        self.save.assert_called_once()

    def test_plan_lists_the_rotation_without_changing_anything(self) -> None:
        self.put("hot", "old:1b")
        self.put("warm", "live:1b")
        status, out, _ = run("storage", "plan")
        self.assertIsNone(status)
        self.assertIn("move old:1b: hot -> warm (retired)", out)
        self.assertIn("note: live:1b is default but stored in warm", out)
        self.execute.assert_not_called()
        self.repair.assert_not_called()

    def test_plan_says_when_there_is_nothing_to_do(self) -> None:
        self.put("hot", "live:1b")
        self.assertIn("storage: nothing to rotate", run("storage", "plan")[1])

    def test_apply_repairs_then_carries_out_each_move_and_saves(self) -> None:
        self.put("hot", "old:1b")
        self.repair.return_value = ["old:1b links"]
        status, out, _ = run("storage", "apply")
        self.assertIsNone(status)
        self.assertIn("repaired old:1b links", out)
        self.assertIn("done; 2.0 GiB freed in hot", out)
        action = self.execute.call_args.args[0]
        self.assertEqual((action.kind, action.model, action.target), ("move", "old:1b", "warm"))
        # a model leaving hot is unloaded from Ollama first
        self.execute.call_args.kwargs["before_leaving_hot"]("old:1b")
        self.unload.assert_called_once_with("http://localhost:11434", "old:1b")
        self.assertGreaterEqual(self.save.call_count, 2)

    def test_apply_does_not_delete_unless_asked(self) -> None:
        self.put("cold", "old:1b", since="2000-01-01")
        status, out, _ = run("storage", "apply")
        self.assertIsNone(status)
        self.assertIn("delete old:1b: cold", out)
        self.assertIn("skipped: pass --delete to delete", out)
        self.execute.assert_not_called()
        run("storage", "apply", "--delete")
        self.assertEqual(self.execute.call_args.args[0].kind, "delete")

    def test_a_storage_error_during_apply_saves_state_and_exits_1(self) -> None:
        self.put("hot", "old:1b")
        self.execute.side_effect = ms.StorageError("target is full")
        status, _, err = run("storage", "apply")
        self.assertEqual(status, 1)
        self.assertIn("Error: target is full", err)
        self.save.assert_called()

    def test_restore_of_an_unknown_model_exits_1(self) -> None:
        status, _, err = run("storage", "restore", "ghost:1b")
        self.assertEqual(status, 1)
        self.assertIn("ghost:1b is not in any tier", err)

    def test_restore_of_a_hot_model_does_nothing(self) -> None:
        self.put("hot", "live:1b")
        status, out, _ = run("storage", "restore", "live:1b")
        self.assertIsNone(status)
        self.assertIn("already on hot storage", out)
        self.execute.assert_not_called()

    def test_restore_moves_a_model_back_and_warns_if_still_retired(self) -> None:
        self.put("warm", "old:1b", since="2026-01-01")
        status, out, _ = run("storage", "restore", "old:1b")
        self.assertIsNone(status)
        action = self.execute.call_args.args[0]
        self.assertEqual((action.source, action.target, action.reason), ("warm", "hot", "restore"))
        self.assertIn("old:1b: warm -> hot", out)
        self.assertIn("still retired in the serving policy", out)

    def test_restore_of_a_live_model_has_no_retired_note(self) -> None:
        self.put("warm", "live:1b", since="2026-01-01")
        self.assertNotIn("retired", run("storage", "restore", "live:1b")[1])

    def test_bench_due_dry_run_lists_without_running(self) -> None:
        self.put("warm", "old:1b", since="2026-01-01")
        status, out, _ = run("storage", "bench-due", "--dry-run")
        self.assertIsNone(status)
        self.assertIn("bench old:1b (warm, every 30 d)", out)
        self.run_process.assert_not_called()

    def test_bench_due_with_nothing_due_says_so(self) -> None:
        self.put("hot", "live:1b")
        self.assertIn("no warm or cold model is due", run("storage", "bench-due")[1])

    def test_a_successful_benchmark_is_recorded_and_a_failed_one_retried_later(self) -> None:
        self.put("warm", "old:1b", since="2026-01-01")
        run("storage", "bench-due")
        argv = self.run_process.call_args.args[0]
        self.assertEqual(argv[0], "bash")
        self.assertTrue(argv[1].endswith("scripts/llamacpp_bench.sh"))
        self.assertEqual(argv[2], "old:1b")
        env = self.run_process.call_args.kwargs["env"]
        self.assertEqual(env["CREW_CHIEF_MODELS_DIR"], str(self.tiers["warm"]))
        self.assertEqual(self.final_state()["old:1b"].get("last_benched"), TODAY.isoformat())

        self.run_process.return_value = SimpleNamespace(returncode=1)
        _, _, err = run("storage", "bench-due")
        self.assertIn("benchmark failed for old:1b; will retry next run", err)
        self.assertNotIn("last_benched", self.final_state()["old:1b"])

    def decisions_repo(self):
        repo = Path(self.tmp.name) / "repo"
        suites = repo / "benchmarks" / "decisions"
        suites.mkdir(parents=True)
        for name in ("b.json", "a.json"):
            (suites / name).write_text("{}", encoding="utf-8")
        self.patch("crew_chief.serving_policy.REPO_ROOT", repo)
        return repo

    def test_decision_bench_dry_run_lists_the_runners(self) -> None:
        self.put("hot", "dm:1b")
        status, out, _ = run("storage", "decision-bench", "--dry-run")
        self.assertIsNone(status)
        self.assertEqual(out.strip(), "decision benchmark runners: rules, bayes, systemone:dm:1b")
        self.run_process.assert_not_called()

    def test_decision_bench_runs_every_suite_with_every_runner(self) -> None:
        repo = self.decisions_repo()
        self.put("warm", "dm:1b", since="2026-01-01")
        status, _, _ = run("storage", "decision-bench")
        self.assertIsNone(status)
        suites = [Path(c.args[0][4]).name for c in self.run_process.call_args_list]
        self.assertEqual(suites, ["a.json", "b.json"])
        argv = self.run_process.call_args.args[0]
        self.assertEqual(argv[1:4], ["-m", "crew_chief", "taskbench"])
        runners = [argv[i + 1] for i, a in enumerate(argv) if a == "--runner"]
        self.assertEqual(runners, ["rules", "bayes", "systemone:dm:1b"])
        self.assertEqual(self.run_process.call_args.kwargs["env"]["PYTHONPATH"], str(repo / "src"))
        self.assertEqual(self.final_state()["dm:1b"]["last_decisions"], TODAY.isoformat())

    def test_a_failed_suite_is_reported_and_the_decision_date_is_not_recorded(self) -> None:
        self.decisions_repo()
        self.put("warm", "dm:1b", since="2026-01-01")
        self.run_process.side_effect = [
            SimpleNamespace(returncode=1),
            SimpleNamespace(returncode=0),
        ]
        _, _, err = run("storage", "decision-bench")
        self.assertIn("a.json failed", err)
        self.assertNotIn("b.json failed", err)
        self.assertNotIn("last_decisions", self.final_state()["dm:1b"])

    def test_retired_models_and_other_roles_are_not_decision_runners(self) -> None:
        self.put("hot", "dm:1b")
        self.put("hot", "live:1b")
        self.put("hot", "old:1b")
        self.put("hot", "gone:1b")
        out = run("storage", "decision-bench", "--dry-run")[1]
        self.assertIn("systemone:dm:1b", out)
        self.assertNotIn("live:1b", out)
        self.assertNotIn("old:1b", out)
        self.assertNotIn("gone:1b", out)

    def test_an_untracked_decision_model_has_no_state_to_keep(self) -> None:
        self.decisions_repo()
        # dm is in the policy but on no tier, so there is no state entry to stamp
        status, _, _ = run("storage", "decision-bench")
        self.assertIsNone(status)
        self.assertNotIn("dm:1b", self.final_state())

    def test_unreadable_policy_or_tiers_exit_2_before_anything_runs(self) -> None:
        self.patch("crew_chief.serving_policy.load_policy", side_effect=PolicyError("no policy"))
        status, _, err = run("storage", "status")
        self.assertEqual(status, 2)
        self.assertIn("no policy", err)
        self.patch("crew_chief.serving_policy.load_policy", return_value=self.policy)
        self.patch("crew_chief.model_storage.load_tiers", side_effect=ms.StorageError("no tiers"))
        status, _, err = run("storage", "plan")
        self.assertEqual(status, 2)
        self.assertIn("no tiers", err)
        self.save.assert_not_called()


class AgentTests(CliCase):
    def setUp(self) -> None:
        super().setUp()
        names = {
            "agent": "crew_chief.agent.Agent",
            "dispatcher": "crew_chief.dispatcher.Dispatcher",
            "fallback": "crew_chief.providers.FallbackProvider",
            "anthropic": "crew_chief.providers.anthropic.AnthropicProvider",
            "claude": "crew_chief.providers.cli.ClaudeCliProvider",
            "codex": "crew_chief.providers.cli.CodexCliProvider",
            "ollama": "crew_chief.providers.ollama.OllamaProvider",
            "openai": "crew_chief.providers.openai.OpenAIProvider",
            "shell": "crew_chief.tools.ShellTool",
            "read": "crew_chief.tools.ReadFileTool",
            "write": "crew_chief.tools.WriteFileTool",
        }
        self.m = SimpleNamespace(**{k: self.patch(v) for k, v in names.items()})
        self.m.agent.return_value.run.return_value = "the answer"
        env = mock.patch.dict("os.environ", {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            import os

            os.environ.pop(key, None)

    def test_the_result_is_printed_and_the_agent_is_configured_from_the_flags(self) -> None:
        status, out, _ = run(
            "agent",
            "do it",
            "--provider",
            "ollama",
            "--max-iterations",
            "3",
            "--system",
            "be brief",
        )
        self.assertIsNone(status)
        self.assertEqual(out, "the answer\n")
        self.m.agent.return_value.run.assert_called_once_with("do it")
        kwargs = self.m.agent.call_args.kwargs
        self.assertEqual((kwargs["max_iterations"], kwargs["system_prompt"]), (3, "be brief"))
        self.assertEqual(kwargs["tools"], [])
        self.assertIs(kwargs["provider"], self.m.ollama.return_value)

    def test_the_default_provider_falls_back_through_every_backend_in_order(self) -> None:
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "o"}):
            run("a", "task")
        chain = self.m.fallback.call_args.args[0]
        self.assertEqual(
            chain,
            [
                self.m.ollama.return_value,
                self.m.claude.return_value,
                self.m.codex.return_value,
                self.m.anthropic.return_value,
                self.m.openai.return_value,
            ],
        )
        self.assertEqual(self.m.anthropic.call_args.kwargs["api_key"], "a")
        self.assertEqual(self.m.openai.call_args.kwargs["api_key"], "o")

    def test_the_fallback_chain_tolerates_missing_api_keys(self) -> None:
        status, _, _ = run("agent", "task")
        self.assertIsNone(status)
        self.assertEqual(self.m.anthropic.call_args.kwargs["api_key"], "")

    def test_cli_providers_need_no_key(self) -> None:
        run("agent", "t", "--provider", "claude-cli")
        self.assertIs(self.m.agent.call_args.kwargs["provider"], self.m.claude.return_value)
        run("agent", "t", "--provider", "codex-cli")
        self.assertIs(self.m.agent.call_args.kwargs["provider"], self.m.codex.return_value)

    def test_hosted_providers_refuse_to_start_without_a_key(self) -> None:
        for provider, variable in (
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
        ):
            with self.subTest(provider=provider):
                status, _, err = run("agent", "t", "--provider", provider)
                self.assertEqual(status, 2)
                self.assertIn(f"{variable} environment variable is not set", err)
        self.m.agent.assert_not_called()

    def test_hosted_providers_use_the_key_from_the_environment(self) -> None:
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k1", "OPENAI_API_KEY": "k2"}):
            run("agent", "t", "--provider", "anthropic")
            self.assertEqual(self.m.anthropic.call_args.kwargs["api_key"], "k1")
            run("agent", "t", "--provider", "openai")
            self.assertEqual(self.m.openai.call_args.kwargs["api_key"], "k2")

    def test_tools_are_built_from_their_names(self) -> None:
        run(
            "agent", "t", "--provider", "ollama", "--tools", "shell", "read_file", "write_file",
            "--allowed-paths", "/srv", "--allowed-commands", "ls *",
        )  # fmt: skip
        self.m.dispatcher.assert_called_once_with(
            allowed_commands=["ls *"], timeout_seconds=30, max_output_bytes=4000
        )
        self.m.shell.assert_called_once_with(self.m.dispatcher.return_value)
        self.m.read.assert_called_once_with(allowed_paths=["/srv"])
        self.m.write.assert_called_once_with(allowed_paths=["/srv"])
        self.assertEqual(len(self.m.agent.call_args.kwargs["tools"]), 3)

    def test_no_allowed_paths_means_unrestricted_file_tools(self) -> None:
        run("agent", "t", "--provider", "ollama", "--tools", "read_file", "write_file")
        self.m.read.assert_called_once_with(allowed_paths=None)
        self.m.write.assert_called_once_with(allowed_paths=None)

    def test_the_default_shell_allowlist_is_read_only_commands(self) -> None:
        run("agent", "t", "--provider", "ollama", "--tools", "shell")
        allowed = self.m.dispatcher.call_args.kwargs["allowed_commands"]
        for pattern in ("df*", "uptime", "whoami", "ls *"):
            self.assertIn(pattern, allowed)
        for dangerous in ("rm*", "*", "sudo*", "sh*"):
            self.assertNotIn(dangerous, allowed)

    def test_an_unknown_tool_is_ignored_with_a_warning(self) -> None:
        status, _, err = run("agent", "t", "--provider", "ollama", "--tools", "teleport")
        self.assertIsNone(status)
        self.assertIn("Warning: unknown tool 'teleport'", err)
        self.assertEqual(self.m.agent.call_args.kwargs["tools"], [])

    def test_the_log_level_configures_logging(self) -> None:
        run("agent", "t", "--provider", "ollama", "--log-level", "ERROR")
        self.assertEqual(self.basic_config.call_args.kwargs["level"], cli.logging.ERROR)


if __name__ == "__main__":
    unittest.main()
