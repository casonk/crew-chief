#!/usr/bin/env python3
"""Re-render saved benchmark reports so they carry the current portfolio theme.

A report is a static file that embeds the theme as it was when the benchmark ran,
so an old one ignores later theme changes. Each report is rebuilt from the JSON
beside it by the generator that made it (``report.py`` for ``bench-*``,
``test_benchmark.render_html`` for ``test-bench-*``); nothing is re-measured.

    python3 scripts/rerender_reports.py --check     # list reports that are out of date
    python3 scripts/rerender_reports.py             # rebuild them
    python3 scripts/rerender_reports.py results/bench-20260621.json   # just these
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crew_chief import theme  # noqa: E402

EMBEDDED = re.compile(r"<style>(/\* Generated from themes/themes\.toml.*?)</style>", re.S)


def is_current(page: pathlib.Path) -> bool:
    match = EMBEDDED.search(page.read_text(encoding="utf-8", errors="replace"))
    return bool(match) and match.group(1) == theme.CSS


def reports(results: pathlib.Path) -> list[pathlib.Path]:
    """The JSON files whose HTML report is a regular file (not a ``*-latest`` link)."""
    found = []
    for data in sorted(results.glob("*bench-*.json")):
        page = data.with_suffix(".html")
        if page.is_file() and not page.is_symlink() and "latest" not in data.name:
            found.append(data)
    return found


def _test_benchmark():
    spec = importlib.util.spec_from_file_location("test_benchmark", ROOT / "scripts/test_benchmark.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_benchmark"] = module
    spec.loader.exec_module(module)
    return module


def render(data: pathlib.Path) -> None:
    page = data.with_suffix(".html")
    if data.name.startswith("test-bench-"):
        page.write_text(_test_benchmark().render_html(json.loads(data.read_text())))
    else:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/report.py"), str(data), "--out", str(page)],
            check=True,
            capture_output=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("json", nargs="*", type=pathlib.Path, help="result files (default: all in results/)")
    parser.add_argument("--results", type=pathlib.Path, default=ROOT / "results")
    parser.add_argument("--check", action="store_true", help="only list out-of-date reports; exit 1 if any")
    args = parser.parse_args()
    todo = [p for p in (args.json or reports(args.results)) if not is_current(p.with_suffix(".html"))]
    for data in todo:
        print(("stale   " if args.check else "render  ") + str(data.with_suffix(".html")))
        if not args.check:
            render(data)
    if not todo:
        print("all reports carry the current theme")
    return 1 if (args.check and todo) else 0


if __name__ == "__main__":
    raise SystemExit(main())
