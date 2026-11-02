"""The bench interface's edges: job lifecycle, request limits and error routes.

The interface starts benchmark processes, so its guards are the point: a Host or Origin
it does not recognise gets a 403, an oversized or malformed body a 400, a job id that is
not exactly twelve hex digits never reaches the filesystem, and a failing handler never
takes the server down. ``Popen`` and ``os.killpg`` are replaced wherever a test would
otherwise start or signal a real process.
"""

from __future__ import annotations

import json
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from crew_chief import benchui
from tests.test_benchui import DEFAULTS, SUITES, AppCase, fake_build, wait_for


class ResultEntries(unittest.TestCase):
    def test_a_routebench_document_lists_its_strategies_without_the_oracle(self):
        document = {
            "strategies": {
                "single": {"accuracy": 0.9, "ms_mean": 10, "ms_p90": 20},
                "oracle": {"accuracy": 1.0, "ms_mean": 0, "ms_p90": 0},
                "unscored": {"accuracy": None, "ms_mean": 1, "ms_p90": 2},
            }
        }
        kind, entries = benchui.result_entries(document)
        self.assertEqual((kind, entries), ("routebench", {"single": (0.9, 10, 20)}))

    def test_a_document_of_neither_kind_is_refused(self):
        for document in ({}, {"other": 1}, "text", 5, None):
            with self.subTest(document=document), self.assertRaises(benchui.BenchError):
                benchui.result_entries(document)


class SuitesAndSpecs(unittest.TestCase):
    def test_available_suites_are_the_sorted_json_stems(self):
        with TemporaryDirectory() as tmp:
            for name in ("b.json", "a.json", "notes.txt"):
                (Path(tmp) / name).write_text("{}", encoding="utf-8")
            self.assertEqual(benchui.available_suites(Path(tmp)), ["a", "b"])

    def test_a_job_spec_must_be_an_object(self):
        for spec in ("x", None, [], 5):
            with self.subTest(spec=spec), self.assertRaisesRegex(benchui.BenchError, "object"):
                benchui.validate_spec(spec, SUITES)


class GpuProbe(unittest.TestCase):
    def test_the_busiest_gpu_is_reported(self):
        done = mock.Mock(stdout="1000\n2500\n")
        with mock.patch.object(benchui.subprocess, "run", return_value=done):
            self.assertEqual(benchui.gpu_used_mib(), 2500)

    def test_no_nvidia_smi_or_odd_output_is_none(self):
        for outcome in (
            {"side_effect": FileNotFoundError()},
            {"side_effect": subprocess.CalledProcessError(9, "nvidia-smi")},
            {"side_effect": subprocess.TimeoutExpired("nvidia-smi", 3)},
            {"return_value": mock.Mock(stdout="not a number")},
            {"return_value": mock.Mock(stdout="")},
        ):
            with (
                self.subTest(outcome=outcome),
                mock.patch.object(benchui.subprocess, "run", **outcome),
            ):
                self.assertIsNone(benchui.gpu_used_mib())


class ProfileStoreEdges(unittest.TestCase):
    def test_a_missing_defaults_file_means_no_profiles_not_a_crash(self):
        with TemporaryDirectory() as tmp:
            store = benchui.ProfileStore(Path(tmp) / "p.toml", Path(tmp) / "absent.toml")
            self.assertEqual(store.list(), [])

    def test_an_unknown_profile_is_refused_on_delete_and_get(self):
        with TemporaryDirectory() as tmp:
            store = benchui.ProfileStore(Path(tmp) / "p.toml", DEFAULTS)
            for call in (store.delete, store.get):
                with (
                    self.subTest(call=call.__name__),
                    self.assertRaisesRegex(benchui.BenchError, "no profile"),
                ):
                    call("nope")


class JobEdges(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        results = {"results": root / "results", "private": root / "private"}
        for directory in results.values():
            directory.mkdir()
        profiles = benchui.ProfileStore(root / "p.toml", DEFAULTS)
        self.jobs = benchui.JobManager(
            root, results, profiles, build=fake_build, probe=lambda: 1, suites=lambda: SUITES
        )
        self.spec = {"kind": "taskbench", "suites": [SUITES[0]], "runners": ["rules"]}

    def queued_record(self, **fields) -> str:
        """A queued record the worker thread will never pick up."""
        job_id = "abcdef012345"
        record = {
            "id": job_id, "status": "queued", "steps": [], "created": time.time(), "out": "results",
            "units_total": 1, "units_done": 0, "step": 0, "outputs": [], "exit_codes": [], "current": "",
        }  # fmt: skip
        record.update(fields)
        self.jobs._path(job_id).write_text(json.dumps(record), encoding="utf-8")
        return job_id

    def test_job_ids_must_be_exactly_twelve_lowercase_hex_digits(self):
        for bad in (
            "",
            "short",
            "../etc/passwd",
            "ABCDEF012345",
            "abcdef01234",
            "abcdef0123456",
            "abcdef01234g",
        ):
            with self.subTest(job_id=bad), self.assertRaisesRegex(benchui.BenchError, "no job"):
                self.jobs.get(bad)

    def test_a_job_id_cannot_climb_out_of_the_jobs_directory_to_an_existing_file(self):
        outside = self.jobs.dir.parent / "secret.json"
        outside.write_text(
            json.dumps({"id": "x", "status": "done", "token": "hunter2"}), encoding="utf-8"
        )
        for traversal in ("../secret", "..%2Fsecret", "../jobs/../secret"):
            with (
                self.subTest(job_id=traversal),
                self.assertRaisesRegex(benchui.BenchError, "no job"),
            ):
                self.jobs.get(traversal)

    def test_an_unknown_or_corrupt_job_record_is_refused_not_crashed_on(self):
        with self.assertRaisesRegex(benchui.BenchError, "no job"):
            self.jobs.get("0123456789ab")
        (self.jobs.dir / "0123456789ab.json").write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(benchui.BenchError, "no job"):
            self.jobs.get("0123456789ab")

    def test_listing_skips_unreadable_records_and_sorts_newest_first(self):
        (self.jobs.dir / "000000000000.json").write_text("{broken", encoding="utf-8")
        old = self.queued_record(created=1)
        newer = self.jobs.dir / "111111111111.json"
        newer.write_text(
            json.dumps({"id": "111111111111", "created": 2, "status": "done"}), encoding="utf-8"
        )
        self.assertEqual([r["id"] for r in self.jobs.list()], ["111111111111", old])

    def test_a_queued_job_cancels_at_once_and_a_finished_one_cannot_be_cancelled(self):
        job_id = self.queued_record()
        self.assertEqual(self.jobs.cancel(job_id)["status"], "cancelled")
        with self.assertRaisesRegex(benchui.BenchError, "already cancelled"):
            self.jobs.cancel(job_id)

    def test_cancelling_a_running_job_signals_its_process_group_only(self):
        job_id = self.queued_record(status="running")
        proc = mock.Mock(pid=4242)
        self.jobs._procs[job_id] = proc
        with mock.patch.object(benchui.os, "killpg") as killpg:
            record = self.jobs.cancel(job_id)
        killpg.assert_called_once_with(4242, benchui.signal.SIGTERM)
        self.assertEqual(record["status"], "running")
        self.assertIn(job_id, self.jobs._cancel)

    def test_a_process_that_already_exited_does_not_make_cancel_fail(self):
        job_id = self.queued_record(status="running")
        self.jobs._procs[job_id] = mock.Mock(pid=4242)
        with mock.patch.object(benchui.os, "killpg", side_effect=ProcessLookupError()):
            self.assertEqual(self.jobs.cancel(job_id)["id"], job_id)

    def test_shutdown_signals_every_running_job_and_marks_it_cancelled(self):
        self.jobs._procs = {"aaaaaaaaaaaa": mock.Mock(pid=11), "bbbbbbbbbbbb": mock.Mock(pid=22)}
        with mock.patch.object(benchui.os, "killpg") as killpg:
            self.jobs.shutdown()
        self.assertEqual(sorted(c.args[0] for c in killpg.call_args_list), [11, 22])
        self.assertEqual(self.jobs._cancel, {"aaaaaaaaaaaa", "bbbbbbbbbbbb"})

    def test_a_job_that_is_no_longer_queued_is_not_run_again(self):
        job_id = self.queued_record(status="done", steps=[["echo", "x"]])
        with mock.patch.object(benchui.subprocess, "Popen") as popen:
            self.jobs._run(job_id)
        popen.assert_not_called()

    def test_a_step_that_cannot_start_fails_the_job_with_exit_127_and_says_why(self):
        job_id = self.queued_record(steps=[["/definitely/not/here"]])
        with mock.patch.object(benchui.subprocess, "Popen", side_effect=OSError("no such file")):
            self.jobs._run(job_id)
        record = self.jobs.get(job_id)
        self.assertEqual((record["status"], record["exit_codes"]), ("failed", [127]))
        self.assertIn("cannot start: no such file", record["log"])

    def test_a_job_cancelled_before_its_first_step_starts_nothing(self):
        job_id = self.queued_record(steps=[["echo", "x"]])
        self.jobs._cancel.add(job_id)
        with mock.patch.object(benchui.subprocess, "Popen") as popen:
            self.jobs._run(job_id)
        popen.assert_not_called()
        self.assertEqual(self.jobs.get(job_id)["status"], "cancelled")

    def test_a_missing_log_is_an_empty_progress_update_not_an_error(self):
        job_id = self.queued_record(status="running")
        self.jobs._progress(job_id, self.jobs.dir / "absent.log")


class HttpEdges(AppCase):
    def post(self, path, body=None, headers=None):
        return self.call(path, "POST", body if body is not None else {}, headers)

    def test_known_listing_routes_answer(self):
        self.assertEqual(self.call("/api/suites")[0], 200)
        self.assertEqual(json.loads(self.call("/api/jobs")[1])["jobs"], [])
        self.assertEqual(self.call("/api/results")[0], 200)

    def test_unknown_routes_are_a_400_for_every_method(self):
        for method, path in (
            ("GET", "/nope"),
            ("POST", "/nope"),
            ("DELETE", "/nope"),
            ("POST", "/api/jobs/x/zzz"),
        ):
            with self.subTest(method=method, path=path):
                self.assertEqual(self.call(path, method, {} if method == "POST" else None)[0], 400)

    def test_deleting_a_profile_over_http(self):
        self.assertEqual(
            self.post(
                "/api/profiles",
                {"name": "mine", "accuracy_weight": 0.5, "target_ms": 1, "ceiling_ms": 9},
            )[0],
            200,
        )
        status, body = self.call("/api/profiles/mine", "DELETE")
        self.assertEqual((status, json.loads(body)), (200, {"deleted": True}))
        self.assertEqual(self.call("/api/profiles/mine", "DELETE")[0], 400)

    def test_a_profile_without_a_name_is_refused(self):
        for body in ({"accuracy_weight": 0.5}, {"name": 5}, []):
            with self.subTest(body=body):
                self.assertEqual(self.post("/api/profiles", body)[0], 400)

    def test_a_post_needs_a_json_content_type_a_valid_body_and_a_small_one(self):
        import urllib.request

        def raw(data: bytes, ctype: str | None, length: int | None = None):
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/profiles/reset", data=data, method="POST"
            )
            if ctype:
                req.add_header("Content-Type", ctype)
            if length is not None:
                req.add_unredirected_header("Content-Length", str(length))
            try:
                with urllib.request.urlopen(req) as resp:
                    return resp.status
            except Exception as err:
                return getattr(err, "code", None)

        self.assertEqual(raw(b"{}", "text/plain"), 400)
        self.assertEqual(raw(b"{not json", "application/json"), 400)
        self.assertEqual(raw(b"{}", "application/json"), 200)
        self.assertEqual(raw(b"{}", "application/json", benchui.MAX_BODY + 1), 400)

    def test_a_foreign_origin_cannot_post_but_may_read(self):
        evil = {"Origin": "http://evil.example"}
        self.assertEqual(self.post("/api/profiles/reset", headers=evil)[0], 403)
        self.assertEqual(self.call("/api/suites", headers=evil)[0], 200)

    def test_an_unexpected_failure_is_a_500_and_the_server_keeps_serving(self):
        with mock.patch.object(self.app, "models", side_effect=RuntimeError("boom")):
            self.assertEqual(self.call("/api/models")[0], 500)
        self.assertEqual(self.call("/api/suites")[0], 200)

    def test_rescoring_needs_a_profile_and_a_valid_one(self):
        self.assertEqual(self.post("/api/rescore", {"result": "x"})[0], 400)
        self.assertEqual(
            self.post("/api/rescore", {"profile": {"accuracy_weight": 9}, "result": "x"})[0], 400
        )

    def test_a_cancel_over_http_for_an_unknown_job_is_refused(self):
        self.assertEqual(self.post("/api/jobs/0123456789ab/cancel")[0], 400)
        self.assertEqual(self.post("/api/jobs/not-an-id/cancel")[0], 400)

    def test_a_finished_job_cannot_be_cancelled_over_http(self):
        status, body = self.post(
            "/api/jobs", {"kind": "taskbench", "suites": [SUITES[0]], "runners": ["rules"]}
        )
        self.assertEqual(status, 201)
        job_id = json.loads(body)["id"]
        self.assertTrue(
            wait_for(lambda: json.loads(self.call(f"/api/jobs/{job_id}")[1])["status"] == "done")
        )
        self.assertEqual(self.post(f"/api/jobs/{job_id}/cancel")[0], 400)


class Models(unittest.TestCase):
    def test_an_unreachable_ollama_and_an_unreadable_policy_still_answer(self):
        from crew_chief.serving_policy import PolicyError

        with TemporaryDirectory() as tmp:
            app = benchui.BenchApp(Path(tmp) / "state", Path(tmp) / "results")
            with (
                mock.patch.object(benchui.urllib.request, "urlopen", side_effect=OSError("down")),
                mock.patch.object(
                    benchui.serving_policy, "load_policy", side_effect=PolicyError("none")
                ),
            ):
                result = app.models()
        self.assertEqual(result["ollama"], [])
        self.assertTrue(result["systemone"])

    def test_the_installed_models_are_listed_sorted(self):
        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, *args):
                return json.dumps({"models": [{"name": "b:1"}, {"name": "a:1"}]}).encode()

        with TemporaryDirectory() as tmp:
            app = benchui.BenchApp(Path(tmp) / "state", Path(tmp) / "results")
            with mock.patch.object(benchui.urllib.request, "urlopen", return_value=Reply()):
                self.assertEqual(app.models()["ollama"], ["a:1", "b:1"])


if __name__ == "__main__":
    unittest.main()
