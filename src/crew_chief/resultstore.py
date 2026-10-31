"""crew_chief.resultstore — one SQLite file that holds the benchmark results as rows.

The JSON files in ``results/`` stay the record of a run; this store is a derived, rebuildable
copy in long format (one row per run, performer, task and question) so any view, chart or export is
a query away instead of a custom parser. It is stdlib only (``sqlite3``) and importing is idempotent:
a file is read again only when its content hash changed.

    runs      one row per imported result file
    measures  accuracy, macro F1 and latency per performer, task and question
    answers   one row per item and question for taskbench runs (value, expected, confidence, ms)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crew_chief import taskbench

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, source TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, task TEXT NOT NULL,
  created TEXT NOT NULL, sha256 TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS measures (
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE, performer TEXT NOT NULL,
  task TEXT NOT NULL, question TEXT NOT NULL, n INTEGER, accuracy REAL, macro_f1 REAL,
  ms_mean REAL, ms_median REAL, ms_p90 REAL);
CREATE INDEX IF NOT EXISTS measures_run ON measures(run_id, performer);
CREATE TABLE IF NOT EXISTS answers (
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE, performer TEXT NOT NULL,
  task TEXT NOT NULL, item INTEGER NOT NULL, question TEXT NOT NULL, value TEXT, expected TEXT,
  confidence REAL, ms REAL);
CREATE INDEX IF NOT EXISTS answers_run ON answers(run_id, performer, question);
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _kind(data: Any) -> str | None:
    if isinstance(data, list) and data and all(isinstance(r, dict) and "runner" in r for r in data):
        return "taskbench"
    if isinstance(data, dict) and isinstance(data.get("strategies"), dict):
        return "routebench"
    return None


def _macro_f1(confusion: dict[str, Any] | None) -> float | None:
    try:
        return taskbench.macro_f1(confusion) if confusion else None
    except (KeyError, TypeError):  # an older result without per-label statistics
        return None


def _taskbench(conn: sqlite3.Connection, run_id: int, data: list[dict[str, Any]]) -> None:
    for result in data:
        task, runner = result.get("task", ""), result["runner"]
        for qid, q in result.get("questions", {}).items():
            conf = q.get("confusion")
            conn.execute(
                "INSERT INTO measures VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, runner, task, qid, q.get("n"), q.get("accuracy"),
                    _macro_f1(conf),
                    result.get("latency_ms_mean"), result.get("latency_ms_median"),
                    result.get("latency_ms_p90"),
                ),
            )  # fmt: skip
        for row in result.get("rows", []):
            for qid, a in row.get("answers", {}).items():
                probs = a.get("p") or {}
                top = probs.get(a.get("value")) if probs else None
                conn.execute(
                    "INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?)",
                    (run_id, runner, task, row["item"], qid, a.get("value"), a.get("expected"),
                     top, row.get("ms")),
                )  # fmt: skip


def _routebench(conn: sqlite3.Connection, run_id: int, data: dict[str, Any]) -> None:
    for name, s in data["strategies"].items():
        conn.execute(
            "INSERT INTO measures VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, name, "", "", s.get("n"), s.get("accuracy"), s.get("macro_f1"),
             s.get("ms_mean"), s.get("ms_median"), s.get("ms_p90")),
        )  # fmt: skip
        for task, t in (s.get("per_task") or {}).items():
            conn.execute(
                "INSERT INTO measures VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, name, task, "", t.get("n"), t.get("accuracy"), t.get("macro_f1"),
                 t.get("ms_mean"), None, None),
            )  # fmt: skip


def import_file(conn: sqlite3.Connection, path: Path) -> str:
    """Import one result file: ``new``, ``updated``, ``same`` or ``skipped`` (not a benchmark result)."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    row = conn.execute("SELECT id, sha256 FROM runs WHERE source = ?", (path.name,)).fetchone()
    if row and row["sha256"] == digest:
        return "same"  # unchanged: not even parsed
    try:
        data = json.loads(raw)
    except ValueError:
        return "skipped"
    kind = _kind(data)
    if kind is None:
        return "skipped"
    if row:
        conn.execute("DELETE FROM runs WHERE id = ?", (row["id"],))
    tasks = (
        sorted({r.get("task", "") for r in data}) if kind == "taskbench" else data.get("tasks", [])
    )
    created = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    meta = (
        {} if kind == "taskbench" else {"router": data.get("router"), "pareto": data.get("pareto")}
    )
    cur = conn.execute(
        "INSERT INTO runs (source, kind, task, created, sha256, meta) VALUES (?,?,?,?,?,?)",
        (path.name, kind, ",".join(tasks), created, digest, json.dumps(meta)),
    )
    (_taskbench if kind == "taskbench" else _routebench)(conn, cur.lastrowid, data)
    conn.commit()
    return "updated" if row else "new"


def signature(directory: Path) -> tuple[tuple[str, int, int], ...]:
    """A cheap fingerprint of a results folder (names, sizes, mtimes) to know when to import again."""
    return tuple(
        (p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(directory.glob("*.json"))
    )


def import_dir(conn: sqlite3.Connection, directory: Path) -> dict[str, int]:
    """Import every result file in *directory*; returns how many were new, updated, same or skipped."""
    counts = {"new": 0, "updated": 0, "same": 0, "skipped": 0}
    for path in sorted(directory.glob("*.json")):
        counts[import_file(conn, path)] += 1
    return counts


def runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, source, kind, task, created FROM runs ORDER BY created DESC, id DESC"
    )
    return [dict(r) for r in cur]


def run_for_source(conn: sqlite3.Connection, source: str) -> int | None:
    row = conn.execute("SELECT id FROM runs WHERE source = ?", (source,)).fetchone()
    return row["id"] if row else None


def performers(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    """One row per performer: accuracy weighted by items, mean macro F1 and latency.

    A routebench run has overall rows (no task); a taskbench run is aggregated over its tasks
    and questions.
    """
    overall = conn.execute(
        "SELECT 1 FROM measures WHERE run_id = ? AND task = '' LIMIT 1", (run_id,)
    )
    scope = "task = ''" if overall.fetchone() else "1 = 1"  # a constant, never user input
    cur = conn.execute(
        f"""SELECT performer, SUM(n) AS n, SUM(accuracy * n) / SUM(n) AS accuracy,
                   AVG(macro_f1) AS macro_f1, AVG(ms_mean) AS ms_mean,
                   AVG(ms_median) AS ms_median, AVG(ms_p90) AS ms_p90
            FROM measures WHERE run_id = ? AND {scope}
            GROUP BY performer ORDER BY accuracy DESC, ms_mean""",
        (run_id,),
    )
    return [dict(r) for r in cur]


def tasks(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    """Per task and performer accuracy and latency, for the breakdown tables."""
    cur = conn.execute(
        """SELECT task, performer, SUM(n) AS n, SUM(accuracy * n) / SUM(n) AS accuracy,
                  AVG(macro_f1) AS macro_f1, AVG(ms_mean) AS ms_mean
           FROM measures WHERE run_id = ? AND task != ''
           GROUP BY task, performer ORDER BY task, accuracy DESC""",
        (run_id,),
    )
    return [dict(r) for r in cur]
