"""Tests for crew_chief.benchui: profile storage, job validation, the job runner and the HTTP API."""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from crew_chief import benchui, scoring

DEFAULTS = Path(__file__).resolve().parents[1] / "config" / "scoring-profiles.toml"
SUITES = ["clockwork-grocery-type", "mail-triage"]

RESULT = [
    {
        "runner": "fast",
        "questions": {"q": {"accuracy": 0.90}},
        "latency_ms_mean": 80.0,
        "latency_ms_p90": 100.0,
    },
    {
        "runner": "slow",
        "questions": {"q": {"accuracy": 0.95}},
        "latency_ms_mean": 800.0,
        "latency_ms_p90": 1000.0,
    },
]


def fake_build(spec, out_dir, profiles_path, suites_dir=None):
    """A job that finishes at once and writes a result file the way the CLI would."""
    code = (
        "import json, pathlib, sys\n"
        f"out = pathlib.Path({str(out_dir)!r})\n"
        "print('running fast on 2 items')\n"
        f"(out / 'taskbench-demo-1.json').write_text({json.dumps(json.dumps(RESULT))})\n"
        "(out / 'taskbench-demo-1.md').write_text('# demo')\n"
        "print(f'Saved: {out}/taskbench-demo-1.md and .json')\n"
    )
    return [[sys.executable, "-c", code]]


def wait_for(predicate, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class ProfileStoreTests(unittest.TestCase):
    def test_seeds_from_defaults_saves_and_deletes_without_touching_them(self):
        with TemporaryDirectory() as tmp:
            store = benchui.ProfileStore(Path(tmp) / "profiles.toml", DEFAULTS)
            self.assertEqual({p.name for p in store.list()}, {"interactive", "batch"})
            store.save("mine", {"accuracy_weight": 0.75, "target_ms": 50, "ceiling_ms": 800})
            names = {p.name for p in store.list()}
            self.assertEqual(names, {"interactive", "batch", "mine"})
            mine = store.get("mine")
            self.assertEqual(mine.accuracy_weight, 0.75)
            self.assertEqual(mine.speed_weight, 0.25)
            store.delete("mine")
            self.assertNotIn("mine", {p.name for p in store.list()})
            self.assertIn("accuracy_weight", DEFAULTS.read_text())

    def test_round_trips_through_toml_including_gates_and_description(self):
        with TemporaryDirectory() as tmp:
            store = benchui.ProfileStore(Path(tmp) / "p.toml", DEFAULTS)
            store.save(
                "gated",
                {
                    "description": 'quote " and \\ slash',
                    "accuracy_weight": 0.6,
                    "relative_weight": 0.4,
                    "target_ms": 20,
                    "ceiling_ms": 200,
                    "min_accuracy": 0.9,
                    "max_p90_ms": 500,
                },
            )
            got = benchui.ProfileStore(Path(tmp) / "p.toml", DEFAULTS).get("gated")
            self.assertEqual(got.description, 'quote " and \\ slash')
            self.assertEqual(
                (got.min_accuracy, got.max_p90_ms, got.relative_weight), (0.9, 500, 0.4)
            )

    def test_rejects_bad_names_and_values(self):
        with TemporaryDirectory() as tmp:
            store = benchui.ProfileStore(Path(tmp) / "p.toml", DEFAULTS)
            for name, table in (
                ("../x", {"accuracy_weight": 0.5, "target_ms": 1, "ceiling_ms": 2}),
                ("ok", {"accuracy_weight": 1.5, "target_ms": 1, "ceiling_ms": 2}),
                ("ok", {"accuracy_weight": 0.5, "target_ms": 9, "ceiling_ms": 2}),
            ):
                with self.assertRaises(benchui.BenchError):
                    store.save(name, table)

    def test_cannot_delete_the_last_profile_and_reset_restores_defaults(self):
        with TemporaryDirectory() as tmp:
            store = benchui.ProfileStore(Path(tmp) / "p.toml", DEFAULTS)
            store.delete("batch")
            with self.assertRaises(benchui.BenchError):
                store.delete("interactive")
            store.reset()
            self.assertEqual({p.name for p in store.list()}, {"interactive", "batch"})


class RelativeSpeedTests(unittest.TestCase):
    def test_relative_curve_pins_fastest_to_one_and_slowest_to_zero(self):
        self.assertEqual(scoring.relative_speed(50, 50, 500), 1.0)
        self.assertEqual(scoring.relative_speed(500, 50, 500), 0.0)
        self.assertAlmostEqual(scoring.relative_speed(158.11388, 50, 500), 0.5, places=4)
        self.assertEqual(scoring.relative_speed(70, 70, 70), 1.0)

    def test_relative_weight_separates_models_the_absolute_curve_calls_equal(self):
        profile = scoring.Profile("p", "", 0.5, 100, 1000, relative_weight=1.0)
        entries = {"a": (0.9, 20, 25), "b": (0.9, 80, 90)}  # both under the 100 ms target
        ranking = scoring.rank(profile, entries)
        self.assertEqual([r["name"] for r in ranking], ["a", "b"])
        self.assertGreater(ranking[0]["speed"], ranking[1]["speed"])
        absolute = scoring.Profile("p", "", 0.5, 100, 1000, relative_weight=0.0)
        self.assertEqual({r["speed"] for r in scoring.rank(absolute, entries)}, {1.0})

    def test_blend_and_reference_ignore_zero_latency_baselines(self):
        profile = scoring.Profile("p", "", 0.5, 100, 1000, relative_weight=0.5)
        entries = {"rules": (0.7, 0.0, 0.0), "m1": (0.9, 200, 200), "m2": (0.9, 400, 400)}
        ref = scoring.reference(entries)
        self.assertEqual(ref.mean, (200, 400))
        got = scoring.score(profile, 0.9, 200, 200, ref=ref)
        absolute = scoring.speed_score(200, 100, 1000)
        self.assertAlmostEqual(got.speed, 0.5 * absolute + 0.5 * 1.0)
        self.assertEqual(scoring.score(profile, 0.7, 0, 0, ref=ref).speed, 1.0)

    def test_gates_stay_absolute(self):
        profile = scoring.Profile("p", "", 0.5, 100, 1000, relative_weight=1.0, min_accuracy=0.8)
        entries = {"fast": (0.5, 10, 10), "ok": (0.9, 500, 500)}
        ranking = scoring.rank(profile, entries)
        self.assertEqual(ranking[-1]["name"], "fast")
        self.assertIsNotNone(ranking[-1]["gate"])

    def test_dump_and_load_round_trip(self):
        original = scoring.load_profiles(DEFAULTS)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.toml"
            path.write_text(scoring.dump_profiles(original), encoding="utf-8")
            self.assertEqual(scoring.load_profiles(path), original)

    def test_taskbench_report_measures_speed_against_its_own_runners(self):
        from crew_chief import taskbench as tb

        ref = scoring.reference(
            {r["runner"]: tb.result_entry(r) for r in RESULT if tb.result_entry(r)}
        )
        profile = scoring.Profile("p", "", 0.5, 100, 1000, relative_weight=1.0)
        self.assertEqual(tb.result_score(RESULT[0], profile, ref), "0.950")  # 0.5*0.9 + 0.5*1.0
        self.assertEqual(tb.result_score(RESULT[1], profile, ref), "0.475")  # 0.5*0.95 + 0


class SpecTests(unittest.TestCase):
    def good(self, **over):
        spec = {"kind": "taskbench", "suites": ["mail-triage"], "runners": ["rules"]}
        spec.update(over)
        return spec

    def test_accepts_a_valid_spec_with_defaults(self):
        got = benchui.validate_spec(self.good(), SUITES)
        self.assertEqual((got["split"], got["private"]), ("dev", False))
        self.assertEqual(got["thresholds"], [0.6, 0.8, 0.95])

    def test_rejects_unknown_suites_paths_and_shell_shaped_runners(self):
        for bad in (
            self.good(suites=["../../etc/passwd"]),
            self.good(suites=[]),
            self.good(kind="rm"),
            self.good(runners=["ollama:x; rm -rf /"]),
            self.good(runners=["ollama:$(id)"]),
            self.good(runners=["--out=/etc"]),
            self.good(runners=[]),
            self.good(split="everything"),
            self.good(thresholds=[2.0]),
            self.good(router="systemone:a b"),
        ):
            with self.assertRaises(benchui.BenchError, msg=str(bad)):
                benchui.validate_spec(bad, SUITES)

    def test_build_steps_pass_arguments_as_a_list_and_use_saved_profiles(self):
        with TemporaryDirectory() as tmp:
            profiles = Path(tmp) / "p.toml"
            profiles.write_text("x")
            spec = benchui.validate_spec(
                self.good(suites=SUITES, runners=["rules", "ollama:q:7b"]), SUITES
            )
            steps = benchui.build_steps(spec, Path(tmp), profiles)
            self.assertEqual(len(steps), 2)  # one taskbench run per suite
            self.assertIn("--profiles", steps[0])
            self.assertEqual(steps[0].count("--runner"), 2)
            route = benchui.validate_spec(
                {"kind": "routebench", "suites": SUITES, "runners": ["systemone:tev1"]}, SUITES
            )
            (step,) = benchui.build_steps(route, Path(tmp), None)
            self.assertNotIn("--profiles", step)
            self.assertEqual(step.count("--threshold"), 3)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "results").mkdir()
        server = benchui.make_server(root / "state", root / "results", "127.0.0.1", 0)
        self.app = server.RequestHandlerClass.app
        self.app.profiles.defaults = DEFAULTS
        self.app.jobs.build = fake_build
        self.app.jobs.probe = lambda: 7
        self.app.jobs.suites = lambda: SUITES
        self.server = server
        self.port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.root = root

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, path, method="GET", body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method
        )
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def test_page_and_profiles(self):
        status, body = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Crew Chief bench", body)
        status, body = self.call("/api/profiles")
        self.assertEqual(
            {p["name"] for p in json.loads(body)["profiles"]}, {"interactive", "batch"}
        )

    def test_save_profile_then_rescore_a_result_under_it(self):
        (self.root / "results" / "taskbench-demo-1.json").write_text(json.dumps(RESULT))
        draft = {
            "name": "mine",
            "accuracy_weight": 0.5,
            "relative_weight": 1.0,
            "target_ms": 100,
            "ceiling_ms": 1000,
        }
        status, _ = self.call("/api/profiles", "POST", draft)
        self.assertEqual(status, 200)
        status, body = self.call(
            "/api/rescore", "POST", {"result": "results/taskbench-demo-1.json", "profile": draft}
        )
        out = json.loads(body)
        self.assertEqual(out["ranking"][0]["name"], "fast")
        self.assertEqual(out["ranking"][0]["score"], 0.95)
        self.assertEqual(out["reference"]["mean"], [80.0, 800.0])
        status, body = self.call(
            "/api/rescore", "POST", {"result": "results/x.json", "profile": draft}
        )
        self.assertEqual(status, 400)

    def test_invalid_profile_is_a_400_with_a_message(self):
        status, body = self.call("/api/profiles", "POST", {"name": "bad", "accuracy_weight": 3})
        self.assertEqual(status, 400)
        self.assertIn("accuracy_weight", json.loads(body)["error"])

    def test_job_runs_to_completion_and_links_its_result(self):
        status, body = self.call(
            "/api/jobs",
            "POST",
            {"kind": "taskbench", "suites": ["mail-triage"], "runners": ["rules"]},
        )
        self.assertEqual(status, 201)
        job_id = json.loads(body)["id"]

        def finished():
            return json.loads(self.call(f"/api/jobs/{job_id}")[1])["status"] in benchui.TERMINAL

        self.assertTrue(wait_for(finished))
        job = json.loads(self.call(f"/api/jobs/{job_id}")[1])
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["gpu_used_mib_at_start"], 7)
        self.assertEqual(job["units_done"], 1)
        self.assertIn("taskbench-demo-1.json", job["outputs"])
        self.assertIn("running fast", job["log"])
        results = json.loads(self.call("/api/results")[1])["results"]
        self.assertEqual(results[0]["job"], job_id)
        status, body = self.call("/api/results/results/taskbench-demo-1.json")
        self.assertEqual(json.loads(body)["entries"]["slow"]["accuracy"], 0.95)

    def test_failed_job_is_marked_failed_and_cancel_stops_a_running_one(self):
        self.app.jobs.build = lambda *a, **k: [[sys.executable, "-c", "import sys; sys.exit(3)"]]
        spec = {"kind": "taskbench", "suites": ["mail-triage"], "runners": ["rules"]}
        job_id = json.loads(self.call("/api/jobs", "POST", spec)[1])["id"]
        self.assertTrue(
            wait_for(lambda: json.loads(self.call(f"/api/jobs/{job_id}")[1])["status"] == "failed")
        )
        self.app.jobs.build = lambda *a, **k: [
            [
                sys.executable,
                "-c",
                "import time; print('running x on 1 items', flush=True); time.sleep(60)",
            ]
        ]
        job_id = json.loads(self.call("/api/jobs", "POST", spec)[1])["id"]
        self.assertTrue(
            wait_for(lambda: json.loads(self.call(f"/api/jobs/{job_id}")[1])["status"] == "running")
        )
        self.call(f"/api/jobs/{job_id}/cancel", "POST", {})
        self.assertTrue(
            wait_for(
                lambda: json.loads(self.call(f"/api/jobs/{job_id}")[1])["status"] == "cancelled"
            )
        )

    def test_private_jobs_write_outside_the_shared_results_folder(self):
        spec = {
            "kind": "taskbench",
            "suites": ["mail-triage"],
            "runners": ["rules"],
            "private": True,
        }
        job_id = json.loads(self.call("/api/jobs", "POST", spec)[1])["id"]
        self.assertTrue(
            wait_for(lambda: json.loads(self.call(f"/api/jobs/{job_id}")[1])["status"] == "done")
        )
        self.assertEqual(list((self.root / "results").iterdir()), [])
        results = json.loads(self.call("/api/results")[1])["results"]
        self.assertEqual(results[0]["ref"], "private/taskbench-demo-1.json")

    def test_rejects_bad_job_bad_host_bad_origin_and_traversal(self):
        status, _ = self.call(
            "/api/jobs", "POST", {"kind": "taskbench", "suites": ["x"], "runners": ["rules"]}
        )
        self.assertEqual(status, 400)
        status, _ = self.call("/api/jobs", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.call(
            "/api/profiles/reset", "POST", {}, headers={"Origin": "http://evil.example"}
        )
        self.assertEqual(status, 403)
        for path in (
            "/files/results/..%2f..%2fetc%2fpasswd",
            "/files/results/a.py",
            "/files/other/a.md",
        ):
            status, _ = self.call(path)
            self.assertEqual(status, 400, path)

    def test_post_needs_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/profiles/reset", data=b"{}", method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_restart_marks_unfinished_jobs_interrupted(self):
        jobs = self.app.jobs
        record = {"id": "0123456789ab", "status": "running", "created": 1, "out": "results"}
        (jobs.dir / "0123456789ab.json").write_text(json.dumps(record))
        again = benchui.JobManager(self.root / "state", self.app.results_dirs, self.app.profiles)
        self.assertEqual(again.get("0123456789ab")["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
