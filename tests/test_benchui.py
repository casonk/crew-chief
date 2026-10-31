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

from crew_chief import benchui, scoring, theme

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


def wait_for(predicate, timeout=30.0):
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


class RoutersTests(unittest.TestCase):
    def route(self, **over):
        spec = {"kind": "routebench", "suites": ["mail-triage"], "runners": ["systemone:tev1"]}
        spec.update(over)
        return spec

    def test_several_routing_models_each_get_their_own_run_in_order(self):
        routers = ["systemone:clef-flash", "systemone:nimble", "systemone:tev1"]
        spec = benchui.validate_spec(self.route(routers=routers), SUITES)
        steps = benchui.build_steps(spec, Path("/out"), None)
        self.assertEqual([s[s.index("--router") + 1] for s in steps], routers)
        self.assertTrue(all(s.count("--candidate") == 1 for s in steps))

    def test_the_single_router_field_and_the_default_still_work(self):
        legacy = benchui.validate_spec(self.route(router="systemone:nimble"), SUITES)
        self.assertEqual(legacy["routers"], ["systemone:nimble"])
        default = benchui.validate_spec(self.route(), SUITES)
        self.assertEqual(default["routers"], ["systemone:clef-flash"])

    def test_duplicates_collapse_and_bad_lists_are_refused(self):
        same = benchui.validate_spec(self.route(routers=["systemone:a", "systemone:a"]), SUITES)
        self.assertEqual(same["routers"], ["systemone:a"])
        for bad in (
            [],
            ["systemone:a b"],
            ["x; rm -rf /"],
            [f"systemone:m{i}" for i in range(9)],
            "systemone:a",
        ):
            with self.assertRaises(benchui.BenchError, msg=str(bad)):
                benchui.validate_spec(self.route(routers=bad), SUITES)

    def test_the_form_offers_a_checkbox_per_routing_model(self):
        from crew_chief.benchui_page import PAGE

        self.assertIn('id="r-routers"', PAGE)
        self.assertIn('name="router"', PAGE)
        self.assertNotIn('id="r-router"', PAGE)


class AppCase(unittest.TestCase):
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


class AppTests(AppCase):
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


class ProxyTests(AppCase):
    """The interface behind the shared Caddy: its hostname, and the old static-site URLs."""

    def setUp(self):
        super().setUp()
        self.server.RequestHandlerClass.allowed_hosts.add("bench.crew-chief.internal")

    def test_proxied_host_and_same_origin_posts_are_accepted(self):
        host = {"Host": "bench.crew-chief.internal"}
        self.assertEqual(self.call("/api/profiles", headers=host)[0], 200)
        same = {**host, "Origin": "https://bench.crew-chief.internal"}
        self.assertEqual(self.call("/api/profiles/reset", "POST", {}, headers=same)[0], 200)
        other = {**host, "Origin": "https://evil.example"}
        self.assertEqual(self.call("/api/profiles/reset", "POST", {}, headers=other)[0], 403)
        self.assertEqual(self.call("/", headers={"Host": "other.internal"})[0], 403)

    def test_a_served_page_has_one_theme_control_and_a_visible_way_back(self):
        (self.root / "results" / "two.html").write_text(
            "<html><head><title>t</title></head><body><nav>"
            '<select data-theme-switcher class="theme-switch"></select></nav><p>x</p></body></html>'
        )
        page = self.call("/two.html")[1].decode()
        self.assertNotRegex(page, r"<select[^>]*data-theme-switcher")
        self.assertIn("<p>x</p>", page)
        for href in ("/", "/latest.html", "/test-bench-latest.html", "/results/"):
            self.assertIn(f'<a href="{href}"', page)
        self.assertIn("Bench home", page)
        self.assertNotIn("position:fixed", page)
        for path in ("/results/", "/view/results/two.html"):
            self.assertIn("Bench home", self.call(path)[1].decode())

    def test_the_interface_page_has_no_theme_selector_of_its_own(self):
        self.assertNotRegex(self.call("/")[1].decode(), r"<select[^>]*data-theme-switcher")

    def _stored_result(self, name="taskbench-demo.json", accuracy=0.9):
        result = [
            {"runner": r, "task": "demo", "items": 4, "errors": 0, "latency_ms_mean": ms,
             "latency_ms_median": ms, "latency_ms_p90": ms, "rows": [],
             "questions": {"q": {"accuracy": accuracy, "n": 4}}}
            for r, ms in (("fast", 80.0), ("slow", 800.0))
        ]  # fmt: skip
        (self.root / "results" / name).write_text(json.dumps(result))

    def test_results_in_the_store_render_on_request_in_every_format(self):
        self._stored_result()
        runs = json.loads(self.call("/api/store/runs")[1])
        run_id = runs["runs"][0]["id"]
        self.assertEqual(runs["runs"][0]["source"], "taskbench-demo.json")
        status, svg = self.call(f"/render/{run_id}/scatter.svg?theme=neon")
        self.assertEqual(status, 200)
        self.assertIn(b"<svg", svg)
        self.assertIn(b"fast", svg)
        self.assertIn(b"fast,", self.call(f"/render/{run_id}/table.csv")[1])
        page = self.call(f"/render/{run_id}/table.html")[1]
        self.assertIn(b"/_portfolio/chrome.js", page)  # the page gets the top bar like any report
        self.assertIn(b"Bench home", page)

    def test_a_bad_render_request_is_refused_with_a_message(self):
        self._stored_result()
        run_id = json.loads(self.call("/api/store/runs")[1])["runs"][0]["id"]
        for path in (
            f"/render/{run_id}/scatter.svg?theme=nope",
            f"/render/{run_id}/scatter.csv",
            f"/render/{run_id}/nothing.svg",
            "/render/999/table.csv",
            "/render/abc",
            f"/render/{run_id}/../x.svg",
        ):
            status, body = self.call(path)
            self.assertEqual(status, 400, path)
            self.assertIn(b"error", body.lower() if body else b"error")

    def test_the_store_follows_the_results_folder(self):
        self.assertEqual(json.loads(self.call("/api/store/runs")[1])["runs"], [])
        self._stored_result("taskbench-a.json")
        self.assertEqual(len(json.loads(self.call("/api/store/runs")[1])["runs"]), 1)
        self._stored_result("taskbench-a.json", accuracy=0.5)  # edited in place
        self._stored_result("taskbench-b.json")
        runs = json.loads(self.call("/api/store/runs")[1])["runs"]
        self.assertEqual(
            sorted(r["source"] for r in runs), ["taskbench-a.json", "taskbench-b.json"]
        )

    def test_the_json_viewer_offers_the_renderings_of_a_stored_result_only(self):
        self._stored_result()
        (self.root / "results" / "other.json").write_text('{"k": 1}')
        page = self.call("/view/results/taskbench-demo.json")[1].decode()
        self.assertIn("/scatter.svg", page)
        self.assertIn("/table.csv", page)
        self.assertNotIn("/scatter.svg", self.call("/view/results/other.json")[1].decode())

    def test_a_stale_embedded_theme_is_replaced_by_the_current_one(self):
        stale = (
            "<style>/* Generated from themes/themes.toml by an older script; do not edit. */"
            ":root{--old:1}</style><script>var OLDTHEME=1</script>"
        )
        (self.root / "results" / "old.html").write_text(
            f"<html><head><title>t</title>{stale}</head><body><p>report</p></body></html>"
        )
        body = self.call("/old.html")[1].decode()
        self.assertNotIn("OLDTHEME", body)
        self.assertNotIn("--old:1", body)
        self.assertIn(theme.JS, body)
        self.assertIn("<p>report</p>", body)
        self.assertEqual(body.count("/_portfolio/chrome.js"), 1)

    def test_a_report_without_head_or_body_keeps_standards_mode(self):
        (self.root / "results" / "bare.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Bare</title><p>x</p>'
        )
        body = self.call("/bare.html")[1].decode()
        self.assertTrue(body.startswith("<!doctype html>"))
        self.assertLess(body.index("<title>Bare</title>"), body.index("/_portfolio/chrome.js"))
        self.assertLess(body.index("/_portfolio/chrome.js"), body.index("<p>x</p>"))

    def test_markdown_and_json_open_in_a_themed_viewer_with_the_top_bar(self):
        (self.root / "results" / "notes.md").write_text(
            "# Notes\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        )
        (self.root / "results" / "data.json").write_text('{"k": [1, 2, 3]}')
        (self.root / "results" / "page.html").write_text("<p>report</p>")
        status, body = self.call("/view/results/notes.md")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn("<h1>Notes</h1>", page)
        self.assertIn("<table>", page)
        self.assertIn("/_portfolio/chrome.js", page)
        self.assertIn("Bench home", page)
        status, body = self.call("/view/results/data.json")
        self.assertIn(b'id="tree"', body)
        self.assertIn(b"/_portfolio/chrome.js", body)
        self.assertIn(b"<p>report</p>", self.call("/view/results/page.html")[1])

    def test_the_viewer_refuses_unknown_files_and_other_folders(self):
        self.assertEqual(self.call("/view/results/missing.md")[0], 400)
        self.assertEqual(self.call("/view/results/../secret.md")[0], 400)
        self.assertEqual(self.call("/view/other/notes.md")[0], 400)

    def test_the_raw_files_are_still_served_unchanged(self):
        (self.root / "results" / "notes.md").write_text("# Notes")
        status, body = self.call("/files/results/notes.md")
        self.assertEqual((status, body), (200, b"# Notes"))
        self.assertEqual(self.call("/notes.md")[1], b"# Notes")

    def test_the_file_list_opens_markdown_and_json_in_the_viewer(self):
        for name in ("notes.md", "data.json", "page.html"):
            (self.root / "results" / name).write_text("{}")
        page = self.call("/results/")[1].decode()
        self.assertIn('href="/view/results/notes.md"', page)
        self.assertIn('href="/view/results/data.json"', page)
        self.assertIn('href="/page.html"', page)
        self.assertIn('href="/notes.md"', page)  # the raw link beside it

    def test_the_file_list_is_themed_and_leads_back_home(self):
        (self.root / "results" / "latest.html").write_text("<p>weekly</p>")
        (self.root / "results" / "data.json").write_text("{}")
        (self.root / "results" / "notes.py").write_text("x")
        status, body = self.call("/results/")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn(theme.JS, page)
        self.assertIn("/_portfolio/chrome.js", page)
        self.assertIn('href="/"', page)
        self.assertIn('href="/latest.html"', page)
        self.assertIn('href="/data.json"', page)
        self.assertNotIn("notes.py", page)

    def test_shared_results_stay_reachable_at_the_site_root(self):
        (self.root / "results" / "latest.html").write_text("<p>weekly</p>")
        (self.root / "results" / "notes.py").write_text("x")
        status, body = self.call("/latest.html")
        self.assertEqual(status, 200)
        self.assertIn(b"<p>weekly</p>", body)
        self.assertEqual(self.call("/notes.py")[0], 400)
        (self.root / "results" / "plain.html").write_text("<h1>no body tag</h1>")
        (self.root / "results" / "full.html").write_text(
            "<html><body class=x><p>hi</p></body></html>"
        )
        for name in ("plain.html", "full.html"):
            body = self.call(f"/{name}")[1]
            self.assertIn(b'href="/"', body)
        self.assertIn(b"<body class=x><nav ", self.call("/full.html")[1])
        self.assertTrue(self.call("/plain.html")[1].endswith(b"<h1>no body tag</h1>"))
        status, body = self.call("/results/")
        self.assertIn(b'href="/latest.html"', body)
        self.assertNotIn(b"notes.py", body)
