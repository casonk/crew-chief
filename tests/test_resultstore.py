"""The result store and the renderers on top of it."""

from __future__ import annotations

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
            "kind": {"accuracy": accuracy, "invalid": 0, "n": 4, "brier": None, "confusion": CONF}
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
