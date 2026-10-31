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
import math
import sqlite3
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crew_chief import taskbench

SCHEMA_VERSION = (
    2  # 2 added measures.tps and measures.extra; the store is derived, so a bump rebuilds it
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, source TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, task TEXT NOT NULL,
  created TEXT NOT NULL, sha256 TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS measures (
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE, performer TEXT NOT NULL,
  task TEXT NOT NULL, question TEXT NOT NULL, n INTEGER, accuracy REAL, macro_f1 REAL,
  ms_mean REAL, ms_median REAL, ms_p90 REAL, tps REAL, extra TEXT NOT NULL DEFAULT '{}');
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
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        for table in ("answers", "measures", "runs"):  # derived data: rebuilt from results/
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.executescript(SCHEMA)
    return conn


def _kind(data: Any) -> str | None:
    if isinstance(data, list) and data and all(isinstance(r, dict) and "runner" in r for r in data):
        return "taskbench"
    if (
        isinstance(data, list)
        and data
        and all(isinstance(r, dict) and "prompt_name" in r and "tokens_per_sec" in r for r in data)
    ):
        return "speedbench"  # inference speed: tokens per second and time to first token
    if isinstance(data, dict):
        if isinstance(data.get("strategies"), dict):
            return "routebench"
        results = data.get("results")
        if "schema_version" in data and isinstance(results, list) and results:
            if all(isinstance(r, dict) and "status" in r and "model" in r for r in results):
                return "testbench"
        if isinstance(data.get("rows"), list) and isinstance(data.get("meta"), dict):
            return "enginebench"  # engine matrix and serving-feature runs
    return None


MEASURE_COLUMNS = (
    "n", "accuracy", "macro_f1", "ms_mean", "ms_median", "ms_p90", "tps", "extra",
)  # fmt: skip


def _measure(
    conn: sqlite3.Connection,
    run_id: int,
    performer: str,
    task: str = "",
    question: str = "",
    **v: Any,
) -> None:
    """One ``measures`` row; any column not given is NULL (``extra`` is stored as JSON)."""
    if "extra" in v:
        v["extra"] = json.dumps(v["extra"], sort_keys=True)
    unknown = set(v) - set(MEASURE_COLUMNS)
    if unknown:
        raise ValueError(f"unknown measure column(s): {', '.join(sorted(unknown))}")
    cols = ["run_id", "performer", "task", "question", *v]
    conn.execute(
        f"INSERT INTO measures ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [run_id, performer, task, question, *v.values()],
    )


def _macro_f1(confusion: dict[str, Any] | None) -> float | None:
    try:
        return taskbench.macro_f1(confusion) if confusion else None
    except (KeyError, TypeError):  # an older result without per-label statistics
        return None


def _taskbench(conn: sqlite3.Connection, run_id: int, data: list[dict[str, Any]]) -> None:
    for result in data:
        task, runner = result.get("task", ""), result["runner"]
        for qid, q in result.get("questions", {}).items():
            _measure(
                conn, run_id, runner, task, qid,
                n=q.get("n"), accuracy=q.get("accuracy"), macro_f1=_macro_f1(q.get("confusion")),
                ms_mean=result.get("latency_ms_mean"), ms_median=result.get("latency_ms_median"),
                ms_p90=result.get("latency_ms_p90"),
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
        _measure(
            conn, run_id, name, n=s.get("n"), accuracy=s.get("accuracy"), macro_f1=s.get("macro_f1"),
            ms_mean=s.get("ms_mean"), ms_median=s.get("ms_median"), ms_p90=s.get("ms_p90"),
        )  # fmt: skip
        for task, t in (s.get("per_task") or {}).items():
            _measure(
                conn, run_id, name, task, n=t.get("n"), accuracy=t.get("accuracy"),
                macro_f1=t.get("macro_f1"), ms_mean=t.get("ms_mean"),
            )  # fmt: skip


def _percentile90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]


def _testbench(conn: sqlite3.Connection, run_id: int, data: dict[str, Any]) -> None:
    """Each trial is one answer (its status against ``passed``); a model's pass rate on a task is the
    accuracy and its agent seconds the latency."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trial in data["results"]:
        groups.setdefault((trial["model"], str(trial.get("task", ""))), []).append(trial)
    item = 0
    for (model, task), trials in groups.items():
        seconds = [1000.0 * float(t.get("agent_seconds") or 0.0) for t in trials]
        passed = sum(t["status"] == "passed" for t in trials)
        _measure(
            conn, run_id, model, task, "outcome", n=len(trials), accuracy=passed / len(trials),
            ms_mean=statistics.fmean(seconds), ms_median=statistics.median(seconds),
            ms_p90=_percentile90(seconds),
            extra={"statuses": dict(sorted(Counter(t["status"] for t in trials).items()))},
        )  # fmt: skip
        for t, ms in zip(trials, seconds, strict=True):
            conn.execute(
                "INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, model, task, item, "outcome", t["status"], "passed", None, ms),
            )
            item += 1


def _speedbench(conn: sqlite3.Connection, run_id: int, data: list[dict[str, Any]]) -> None:
    """Inference speed: one row per model and prompt; tokens per second and time to first token."""
    for r in data:
        failed = bool(r.get("error"))
        _measure(
            conn, run_id, r["model"], str(r.get("prompt_name", "")), n=1,
            ms_mean=None if failed else r.get("ttft_ms"),
            tps=None if failed else r.get("tokens_per_sec"),
            extra={k: r.get(k) for k in ("total_tokens", "total_time_ms", "vram_delta_mb", "error") if r.get(k) is not None},
        )  # fmt: skip


def _enginebench(conn: sqlite3.Connection, run_id: int, data: dict[str, Any]) -> None:
    """Engine-matrix and serving-feature rows: generation speed for a model under one configuration."""
    runs = (data.get("settings") or {}).get("runs")
    for row in data["rows"]:
        label = (
            f"{row.get('model', '')} · {row['config']}"
            if row.get("config")
            else str(row.get("model", ""))
        )
        extra = {
            k: v for k, v in row.items()
            if k not in ("model", "config", "gen_tps", "windows") and isinstance(v, (int, float, str))
        }  # fmt: skip
        _measure(
            conn,
            run_id,
            label,
            str(row.get("experiment", "")),
            n=runs,
            tps=row.get("gen_tps"),
            extra=extra,
        )


IMPORTERS = {
    "taskbench": _taskbench,
    "routebench": _routebench,
    "testbench": _testbench,
    "speedbench": _speedbench,
    "enginebench": _enginebench,
}


def _task_names(kind: str, data: Any) -> list[str]:
    if kind == "taskbench":
        return sorted({r.get("task", "") for r in data})
    if kind == "routebench":
        return list(data.get("tasks", []))
    if kind == "testbench":
        return sorted({str(r.get("task", "")) for r in data["results"]})
    return []


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
    tasks = _task_names(kind, data)
    created = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    meta = (
        {"router": data.get("router"), "pareto": data.get("pareto")} if kind == "routebench" else {}
    )
    cur = conn.execute(
        "INSERT INTO runs (source, kind, task, created, sha256, meta) VALUES (?,?,?,?,?,?)",
        (path.name, kind, ",".join(tasks), created, digest, json.dumps(meta)),
    )
    IMPORTERS[kind](conn, cur.lastrowid, data)
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
                   AVG(ms_median) AS ms_median, AVG(ms_p90) AS ms_p90, AVG(tps) AS tps
            FROM measures WHERE run_id = ? AND {scope}
            GROUP BY performer ORDER BY accuracy DESC, tps DESC, ms_mean""",
        (run_id,),
    )
    return [dict(r) for r in cur]


def tasks(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    """Per task and performer accuracy and latency, for the breakdown tables."""
    cur = conn.execute(
        """SELECT task, performer, SUM(n) AS n, SUM(accuracy * n) / SUM(n) AS accuracy,
                  AVG(macro_f1) AS macro_f1, AVG(ms_mean) AS ms_mean, AVG(tps) AS tps
           FROM measures WHERE run_id = ? AND task != ''
           GROUP BY task, performer ORDER BY task, accuracy DESC""",
        (run_id,),
    )
    return [dict(r) for r in cur]
