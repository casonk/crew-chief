"""The result store and the renderers on top of it."""

from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from crew_chief import render, resultstore

CONF = {
    "labels": ["a", "b"],
    "counts": {"a": {"a": 2, "b": 0}, "b": {"a": 1, "b": 1}},
    "invalid": 0,
    "per_label": {
        "a": {"support": 2, "precision": 0.667, "recall": 1.0, "f1": 0.8},
        "b": {"support": 2, "precision": 1.0, "recall": 0.5, "f1": 0.667},
    },
}


def taskbench_result(runner="fast", accuracy=0.8, ms=100.0, task="mail"):
    return {
        "runner": runner,
        "task": task,
        "items": 4,
        "errors": 0,
        "latency_ms_mean": ms,
        "latency_ms_median": ms,
        "latency_ms_p90": ms * 1.5,
        "questions": {
            "kind": {
                "accuracy": accuracy,
                "invalid": 0,
                "n": 4,
                "brier": None,
                "confusion": copy.deepcopy(CONF),
            }
        },
        "rows": [
            {
                "item": i,
                "ms": ms,
                "answers": {
                    "kind": {"value": "a", "expected": "a" if i else "b", "p": {"a": 0.9, "b": 0.1}}
                },
            }
            for i in range(4)
        ],
    }


ROUTEBENCH = {
    "router": "systemone:x",
    "tasks": ["t1"],
    "pareto": ["single:a"],
    "strategies": {
        "single:a": {
            "n": 10,
            "accuracy": 0.9,
            "macro_f1": 0.88,
            "ms_mean": 50.0,
            "ms_median": 49.0,
            "ms_p90": 70.0,
            "per_task": {"t1": {"n": 10, "accuracy": 0.9, "macro_f1": 0.88, "ms_mean": 50.0}},
        },
        "single:b": {
            "n": 10,
            "accuracy": 0.95,
            "macro_f1": 0.9,
            "ms_mean": 400.0,
            "ms_median": 390.0,
            "ms_p90": 500.0,
            "per_task": {"t1": {"n": 10, "accuracy": 0.95, "macro_f1": 0.9, "ms_mean": 400.0}},
        },
    },
}


TESTBENCH = {
    "schema_version": 2,
    "created_at": "2026-10-22T00:00:00+00:00",
    "results": [
        {"model": "a", "task": "t1", "status": "passed", "agent_seconds": 10.0, "trial": 1},
        {"model": "a", "task": "t1", "status": "failed", "agent_seconds": 30.0, "trial": 2},
        {"model": "a", "task": "t2", "status": "timeout", "agent_seconds": 120.0, "trial": 1},
        {"model": "b", "task": "t1", "status": "passed", "agent_seconds": 5.0, "trial": 1},
    ],
}
SPEED = [
    {
        "model": "fast",
        "prompt_name": "p1",
        "ttft_ms": 20.0,
        "tokens_per_sec": 200.0,
        "total_tokens": 9,
        "error": None,
    },
    {
        "model": "fast",
        "prompt_name": "p2",
        "ttft_ms": 40.0,
        "tokens_per_sec": 180.0,
        "total_tokens": 9,
        "error": None,
    },
    {
        "model": "slow",
        "prompt_name": "p1",
        "ttft_ms": 900.0,
        "tokens_per_sec": 30.0,
        "total_tokens": 9,
        "error": None,
    },
    {"model": "gone", "prompt_name": "p1", "ttft_ms": 0, "tokens_per_sec": 0, "error": "timeout"},
]
ENGINE = {
    "meta": {"gpu": "x"},
    "settings": {"runs": 3},
    "rows": [
        {"model": "m", "config": "ollama", "gen_tps": 100.0, "gpu_mib": 3000, "windows": [[1, 2]]},
        {"model": "m", "config": "llama.cpp", "gen_tps": 150.0, "gpu_mib": 3100},
    ],
}


class StoreCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.conn = resultstore.connect()
        self.addCleanup(self.conn.close)

    def write(self, name, data):
        path = self.dir / name
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        return path


class ImportTests(StoreCase):
    def test_a_taskbench_result_becomes_measure_and_answer_rows(self):
        self.write(
            "taskbench-mail.json", [taskbench_result("fast"), taskbench_result("slow", 0.9, 400.0)]
        )
        self.assertEqual(resultstore.import_dir(self.conn, self.dir)["new"], 1)
        run_id = resultstore.run_for_source(self.conn, "taskbench-mail.json")
        perf = {p["performer"]: p for p in resultstore.performers(self.conn, run_id)}
        self.assertEqual(perf["slow"]["accuracy"], 0.9)
        self.assertEqual(perf["fast"]["ms_mean"], 100.0)
        self.assertAlmostEqual(perf["fast"]["macro_f1"], 0.733, places=2)
        answers = self.conn.execute(
            "SELECT COUNT(*) FROM answers WHERE performer = 'fast'"
        ).fetchone()[0]
        self.assertEqual(answers, 4)

    def test_an_older_result_without_per_label_statistics_still_imports(self):
        old = taskbench_result()
        del old["questions"]["kind"]["confusion"]["per_label"]
        self.write("taskbench-old.json", [old])
        resultstore.import_dir(self.conn, self.dir)
        run_id = resultstore.run_for_source(self.conn, "taskbench-old.json")
        perf = resultstore.performers(self.conn, run_id)
        self.assertEqual((perf[0]["accuracy"], perf[0]["macro_f1"]), (0.8, None))

    def test_a_routebench_result_has_overall_and_per_task_rows(self):
        self.write("routebench-1.json", ROUTEBENCH)
        resultstore.import_dir(self.conn, self.dir)
        run_id = resultstore.run_for_source(self.conn, "routebench-1.json")
        self.assertEqual(
            [p["performer"] for p in resultstore.performers(self.conn, run_id)],
            ["single:b", "single:a"],
        )
        self.assertEqual(len(resultstore.tasks(self.conn, run_id)), 2)

    def test_importing_twice_changes_nothing_and_an_edited_file_replaces_its_rows(self):
        path = self.write("taskbench-mail.json", [taskbench_result(accuracy=0.5)])
        self.assertEqual(resultstore.import_dir(self.conn, self.dir)["new"], 1)
        self.assertEqual(resultstore.import_dir(self.conn, self.dir)["same"], 1)
        path.write_text(json.dumps([taskbench_result(accuracy=0.75)]))
        self.assertEqual(resultstore.import_dir(self.conn, self.dir)["updated"], 1)
        run_id = resultstore.run_for_source(self.conn, "taskbench-mail.json")
        self.assertEqual(resultstore.performers(self.conn, run_id)[0]["accuracy"], 0.75)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0], 4
        )  # no duplicates

    def test_files_that_are_not_benchmark_results_are_skipped(self):
        self.write("notes.json", {"hello": "world"})
        self.write("broken.json", "{ not json")
        self.write("other-list.json", [{"model": "x"}])
        self.assertEqual(
            resultstore.import_dir(self.conn, self.dir),
            {"new": 0, "updated": 0, "same": 0, "skipped": 3},
        )

    def test_an_unchanged_file_is_not_parsed_again(self):
        path = self.write("taskbench-mail.json", [taskbench_result()])
        resultstore.import_dir(self.conn, self.dir)
        original = json.loads
        json.loads = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("parsed an unchanged file")
        )
        try:
            self.assertEqual(resultstore.import_file(self.conn, path), "same")
        finally:
            json.loads = original

    def test_the_signature_changes_when_a_file_is_added_or_edited(self):
        before = resultstore.signature(self.dir)
        self.write("a.json", {"x": 1})
        added = resultstore.signature(self.dir)
        self.assertNotEqual(before, added)
        self.write("a.json", {"x": 2, "y": 3})
        self.assertNotEqual(added, resultstore.signature(self.dir))

    def test_the_schema_is_plain_sql_in_one_file(self):
        path = self.dir / "store.sqlite"
        conn = resultstore.connect(path)
        conn.close()
        names = {
            r[0]
            for r in sqlite3.connect(path).execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue({"runs", "measures", "answers"} <= names)


class MoreKindsTests(StoreCase):
    def imported(self, name, data):
        self.write(name, data)
        resultstore.import_dir(self.conn, self.dir)
        return resultstore.run_for_source(self.conn, name)

    def test_a_test_bench_result_gives_pass_rates_trial_answers_and_agent_time(self):
        run = self.imported("test-bench-x.json", TESTBENCH)
        perf = {p["performer"]: p for p in resultstore.performers(self.conn, run)}
        self.assertAlmostEqual(perf["a"]["accuracy"], 1 / 3)  # 1 pass in 3 trials
        self.assertEqual(perf["b"]["accuracy"], 1.0)
        self.assertEqual(perf["b"]["ms_mean"], 5000.0)  # agent seconds as milliseconds
        outcomes = self.conn.execute(
            "SELECT value FROM answers WHERE performer = 'a' ORDER BY item"
        ).fetchall()
        self.assertEqual([o[0] for o in outcomes], ["passed", "failed", "timeout"])
        self.assertEqual(self.conn.execute("SELECT kind FROM runs").fetchone()[0], "testbench")

    def test_a_speed_run_keeps_tokens_per_second_and_ttft_and_leaves_out_failed_prompts(self):
        run = self.imported("bench-1.json", SPEED)
        perf = {p["performer"]: p for p in resultstore.performers(self.conn, run)}
        self.assertEqual(perf["fast"]["tps"], 190.0)  # mean of 200 and 180
        self.assertEqual(perf["fast"]["ms_mean"], 30.0)
        self.assertIsNone(perf["gone"]["tps"])  # the errored prompt has no speed
        self.assertIsNone(perf["fast"]["accuracy"])
        self.assertEqual(
            [p["performer"] for p in resultstore.performers(self.conn, run)][:2], ["fast", "slow"]
        )
        by_prompt = {
            (t["task"], t["performer"]): t["tps"] for t in resultstore.tasks(self.conn, run)
        }
        self.assertEqual(by_prompt[("p1", "slow")], 30.0)

    def test_an_engine_run_labels_each_row_by_model_and_configuration(self):
        run = self.imported("engine-matrix-1.json", ENGINE)
        perf = {p["performer"]: p["tps"] for p in resultstore.performers(self.conn, run)}
        self.assertEqual(perf, {"m · ollama": 100.0, "m · llama.cpp": 150.0})
        extra = self.conn.execute(
            "SELECT extra FROM measures WHERE performer = 'm · ollama'"
        ).fetchone()[0]
        self.assertEqual(
            json.loads(extra), {"gpu_mib": 3000}
        )  # other fields are kept, windows dropped

    def test_every_kind_is_detected_and_unrelated_json_is_still_skipped(self):
        self.write("a.json", TESTBENCH)
        self.write("b.json", SPEED)
        self.write("c.json", ENGINE)
        self.write("d.json", {"results": [{"x": 1}]})  # looks similar but is not a benchmark
        self.write("e.json", {"rows": [1], "other": 2})
        counts = resultstore.import_dir(self.conn, self.dir)
        self.assertEqual((counts["new"], counts["skipped"]), (3, 2))

    def test_an_older_store_is_rebuilt_when_the_schema_changes(self):
        path = self.dir / "store.sqlite"
        old = sqlite3.connect(path)
        old.executescript(
            "CREATE TABLE runs (id INTEGER PRIMARY KEY, source TEXT); INSERT INTO runs VALUES (1, 'x');"
        )
        old.close()  # user_version 0: the first schema
        conn = resultstore.connect(path)
        self.addCleanup(conn.close)
        self.assertEqual(
            conn.execute("PRAGMA user_version").fetchone()[0], resultstore.SCHEMA_VERSION
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(measures)")}
        self.assertTrue({"tps", "extra"} <= columns)
        resultstore.connect(path).close()  # a current store is left alone


class RenderTests(StoreCase):
    def setUp(self):
        super().setUp()
        self.write("routebench-1.json", ROUTEBENCH)
        self.write(
            "taskbench-mail.json", [taskbench_result("fast"), taskbench_result("slow", 0.9, 400.0)]
        )
        resultstore.import_dir(self.conn, self.dir)
        self.route = resultstore.run_for_source(self.conn, "routebench-1.json")
        self.task = resultstore.run_for_source(self.conn, "taskbench-mail.json")

    def get(self, run, chart, fmt, theme=None):
        body, ctype = render.render(self.conn, run, chart, fmt, theme)
        return body.decode(), ctype

    def test_svgs_are_well_formed_and_carry_every_performer(self):
        for chart in ("scatter", "bars"):
            text, ctype = self.get(self.route, chart, "svg")
            self.assertEqual(ctype, "image/svg+xml")
            ET.fromstring(text)  # raises if it is not well-formed XML
            self.assertIn("single:a", text)
            self.assertIn("single:b", text)

    def test_a_named_theme_is_embedded_and_a_standalone_svg_defaults_to_light_and_dark(self):
        neon = self.get(self.route, "scatter", "svg", "neon")[0]
        self.assertIn(render.theme_tokens()["neon"]["bg"], neon)
        auto = self.get(self.route, "scatter", "svg")[0]
        self.assertIn("prefers-color-scheme: light", auto)
        with self.assertRaises(render.RenderError):
            self.get(self.route, "scatter", "svg", "no-such-theme")

    def test_an_inline_svg_has_no_style_of_its_own_so_it_follows_the_page(self):
        inline = render.scatter_svg(resultstore.performers(self.conn, self.route), standalone=False)
        self.assertNotIn("<style>", inline)

    def test_performer_names_are_escaped(self):
        rows = [
            {
                "performer": "<script>x</script>",
                "n": 1,
                "accuracy": 0.5,
                "macro_f1": None,
                "ms_mean": 10.0,
                "ms_median": 10.0,
                "ms_p90": 10.0,
            }
        ]
        for draw in (render.scatter_svg, render.bars_svg):
            svg = draw(rows)
            self.assertNotIn("<script>", svg)
            ET.fromstring(svg)

    def test_the_pareto_front_is_the_performers_nothing_beats_on_both_axes(self):
        rows = [
            {"performer": "fast", "accuracy": 0.8, "ms_mean": 10.0},
            {"performer": "good", "accuracy": 0.9, "ms_mean": 100.0},
            {"performer": "worse", "accuracy": 0.7, "ms_mean": 200.0},
        ]
        self.assertEqual(render.pareto(rows), {"fast", "good"})

    def test_tables_come_out_as_csv_json_and_markdown_with_the_same_numbers(self):
        csv_text, ctype = self.get(self.task, "table", "csv")
        self.assertTrue(ctype.startswith("text/csv"))
        lines = csv_text.splitlines()
        self.assertEqual(lines[0], "performer,n,accuracy,macro_f1,ms_mean,ms_median,ms_p90")
        self.assertIn("slow,4,0.900", lines[1])
        self.assertIn("400.0", lines[1])  # latency to one decimal
        rows = json.loads(self.get(self.task, "table", "json")[0])
        self.assertEqual(rows[0]["performer"], "slow")
        md = self.get(self.task, "table", "md")[0]
        self.assertTrue(md.startswith("| performer |"))
        self.assertIn("| slow | 4 | 0.900 |", md)

    def test_the_html_page_has_both_charts_and_the_tables_and_a_single_title(self):
        page, ctype = self.get(self.route, "table", "html")
        self.assertTrue(ctype.startswith("text/html"))
        self.assertEqual(page.count("<svg"), 2)
        self.assertEqual(page.count("<h1>"), 1)  # the bar's title, not repeated in the body
        self.assertIn("<table>", page)
        self.assertIn("Performers", page)
        self.assertIn("By task", page)

    def test_tabs_given_to_the_page_land_in_its_bar(self):
        body, _ = render.render(
            self.conn, self.route, "table", "html", None, '<span class="fmt">T</span>'
        )
        self.assertIn('<span class="fmt">T</span>', body.decode())

    def test_a_speed_run_draws_tokens_per_second_and_drops_the_empty_accuracy_columns(self):
        self.write("bench-1.json", SPEED)
        resultstore.import_dir(self.conn, self.dir)
        run = resultstore.run_for_source(self.conn, "bench-1.json")
        scatter = self.get(run, "scatter", "svg")[0]
        ET.fromstring(scatter)
        self.assertIn("tokens / second", scatter)
        self.assertIn("fast", scatter)
        bars = self.get(run, "bars", "svg")[0]
        ET.fromstring(bars)
        self.assertIn("tok/s", bars)
        header = self.get(run, "table", "csv")[0].splitlines()[0]
        self.assertEqual(header, "performer,n,tps,ms_mean")  # no accuracy, macro_f1, median, p90

    def test_a_run_with_speed_but_no_latency_still_has_bars_and_tables(self):
        self.write("engine-matrix-1.json", ENGINE)
        resultstore.import_dir(self.conn, self.dir)
        run = resultstore.run_for_source(self.conn, "engine-matrix-1.json")
        with self.assertRaises(render.RenderError):
            self.get(run, "scatter", "svg")
        self.assertIn("150.0 tok/s", self.get(run, "bars", "svg")[0])
        self.assertIn("m · llama.cpp", self.get(run, "table", "md")[0])

    def test_the_pareto_front_works_on_speed_too(self):
        rows = [
            {"performer": "fast", "tps": 200.0, "ms_mean": 20.0},
            {"performer": "slowfirst", "tps": 300.0, "ms_mean": 900.0},
            {"performer": "worse", "tps": 100.0, "ms_mean": 500.0},
        ]
        self.assertEqual(render.pareto(rows, "tps"), {"fast", "slowfirst"})
        self.assertEqual(render.metric_of(rows), "tps")
        self.assertEqual(render.nice_step(1000), 200)

    def test_a_request_for_something_that_cannot_be_drawn_is_an_error(self):
        for chart, fmt in (("scatter", "csv"), ("nope", "svg"), ("table", "svg")):
            with self.assertRaises(render.RenderError, msg=f"{chart}.{fmt}"):
                self.get(self.route, chart, fmt)
        with self.assertRaises(render.RenderError):
            self.get(9999, "table", "csv")

    def test_a_run_with_no_latency_cannot_be_plotted_but_its_table_renders(self):
        self.conn.execute("UPDATE measures SET ms_mean = NULL WHERE run_id = ?", (self.task,))
        with self.assertRaises(render.RenderError):
            self.get(self.task, "scatter", "svg")
        self.assertIn("performer", self.get(self.task, "table", "csv")[0])

    def test_rendering_is_fast_enough_to_do_on_every_request(self):
        import time

        start = time.perf_counter()
        for _ in range(50):
            render.render(self.conn, self.task, "scatter", "svg", "neon")
            render.render(self.conn, self.task, "table", "csv")
        self.assertLess(
            (time.perf_counter() - start) / 100, 0.02
        )  # under 20 ms each, in practice < 1


if __name__ == "__main__":
    unittest.main()
