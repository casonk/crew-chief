"""Tests for scripts/serving_features.py's offline parts."""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("serving_features", SCRIPTS / "serving_features.py")
features = importlib.util.module_from_spec(SPEC)
sys.modules["serving_features"] = features
SPEC.loader.exec_module(features)


class PrefixTests(unittest.TestCase):
    def test_prefix_sections_are_distinct_and_sized(self):
        prefix = features.agent_prefix(1560)
        self.assertEqual(prefix.count("Section "), 3)
        self.assertIn("Section 3.", prefix)

    def test_nonce_changes_first_line(self):
        self.assertNotEqual(features.nonce(0, "x"), features.nonce(1, "x"))


class RenderTests(unittest.TestCase):
    def test_render_skips_experiments_without_rows_and_shows_errors(self):
        args = argparse.Namespace(
            model="m", ctx=8192, gen=128, runs=3, prefix=6000, draft="d", spec_model="s"
        )
        rows = [
            {"experiment": "kv", "config": "kv f16", "gpu_mib": 1, "gen_tps": 2.0},
            {"experiment": "spec", "config": "draft", "prompt": "prose", "error": "boom"},
        ]
        text = features.render(rows, args, "stamp", {"gpu": "gpu", "llamacpp": "v"})
        self.assertIn("## KV-cache type", text)
        self.assertNotIn("## Parallel slots", text)
        self.assertIn("error: boom", text)


if __name__ == "__main__":
    unittest.main()
