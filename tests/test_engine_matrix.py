"""Tests for scripts/engine_matrix.py's contention marking — offline."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "engine_matrix.py"
SPEC = importlib.util.spec_from_file_location("engine_matrix", SCRIPT)
matrix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(matrix)


class ContentionTests(unittest.TestCase):
    def test_runs_overlapping_contended_samples_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = pathlib.Path(tmp) / "lease.jsonl"
            records = [
                {"t": 105.0, "busy": [{"name": "ffmpeg", "pid": 1, "sm": 0, "enc": 30, "dec": 9}]},
                {"t": 400.0, "busy": [{"name": "/opt/x/upscale", "pid": 2, "sm": 50, "enc": 0, "dec": 0}]},
                {"summary": {"samples": 50, "contended": 2}},
            ]
            log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
            rows = [
                {"windows": [(100.0, 110.0), (110.0, 120.0), (120.0, 130.0)]},
                {"windows": [(200.0, 210.0)]},
                {"windows": [(398.0, 401.0)]},
                {"error": "failed to load"},
            ]
            matrix.mark_contention(rows, str(log))
        self.assertEqual(rows[0]["contended_runs"], 1)
        self.assertEqual(rows[0]["contended_by"], ["ffmpeg"])
        self.assertEqual(rows[1]["contended_runs"], 0)
        self.assertEqual(rows[2]["contended_by"], ["upscale"])
        self.assertEqual(rows[3]["contended_runs"], 0)

    def test_without_a_log_nothing_is_marked(self):
        rows = [{"windows": [(1.0, 2.0)]}]
        matrix.mark_contention(rows, None)
        self.assertNotIn("contended_runs", rows[0])


if __name__ == "__main__":
    unittest.main()
