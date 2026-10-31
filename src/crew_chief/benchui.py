"""crew_chief.benchui — a local web interface for the decision-model benchmarks.

``crew-chief benchui`` serves one page, on localhost only, where you can

- tune scoring profiles with sliders and save them, watching the ranking of a
  chosen result move as you drag (the server rescoring raw results, so the page
  never carries a second copy of the scoring maths);
- start ``taskbench`` and ``routebench`` jobs, one at a time because concurrent
  runs on one GPU would corrupt each other's latencies;
- follow running jobs and open the results they wrote.

A request can only name suites from ``benchmarks/decisions`` and runner specs of
a fixed shape; the server builds the command line itself and never runs a shell.
State (saved profiles, job records and logs, private results) lives under
``CREW_CHIEF_BENCH_STATE``. Stdlib only.
"""

from __future__ import annotations

import contextlib
import html
import json
import os
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from crew_chief import scoring, theme, viewer

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITES_DIR = REPO_ROOT / "benchmarks" / "decisions"
DEFAULT_STATE = Path(
    os.environ.get(
        "CREW_CHIEF_BENCH_STATE", Path.home() / ".local" / "state" / "crew-chief" / "bench"
    )
)
DEFAULT_PORT = 8766
SYSTEMONE_MODELS = ("tev1", "clef-flash", "nimble", "clef")
RUNNER = re.compile(r"(rules|jev|(ollama|llamacpp|systemone):[A-Za-z0-9][A-Za-z0-9._:/-]{0,80})")
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}")
RESULT_KINDS = ("taskbench", "routebench")
SERVED_SUFFIXES = {
    ".md": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".html": "text/html; charset=utf-8",
}
MAX_BODY = 64 * 1024
LOG_TAIL = 12_000
TERMINAL = ("done", "failed", "cancelled", "interrupted")


# A strip under the top bar on every report page: a plain way back to the interface
# and to the other report pages. In the page flow, so it never covers content.
HOME_LINK = (
    '<nav aria-label="Bench" style="display:flex;gap:18px;align-items:baseline;flex-wrap:wrap;'
    "padding:8px 16px;background:var(--surface,#1a1d27);color:var(--text,#e2e4f0);"
    'border-bottom:1px solid var(--border,#2e3250);font:14px system-ui,sans-serif">'
    '<a href="/" style="font-weight:600;color:var(--accent,#5b7fff);text-decoration:none">'
    "&larr; Bench home</a>"
    '<a href="/latest.html" style="color:var(--accent,#5b7fff);text-decoration:none">Weekly report</a>'
    '<a href="/test-bench-latest.html" style="color:var(--accent,#5b7fff);text-decoration:none">'
    "Test bench</a>"
    '<a href="/results/" style="color:var(--accent,#5b7fff);text-decoration:none">All files</a></nav>'
)

# The top bar has the theme control, so a served page drops its own copy of it.
PAGE_SWITCHER = re.compile(r"<select[^>]*data-theme-switcher[^>]*>\s*</select>", re.I)


CHROME_TAG = '<script src="/_portfolio/chrome.js" defer></script>'


# A report generated earlier embeds the theme as it was then (fewer themes, no
# rotator or menu), which clashes with the top bar. Swap it for the current one.
STALE_THEME = re.compile(
    r"<style>/\* Generated from themes/themes\.toml.*?</style>\s*<script>.*?</script>", re.S
)
# What may precede injected markup in a page without <head>/<body>: the doctype,
# the <html> tag and any leading <meta>/<title>, so the page keeps standards mode.
PROLOGUE = re.compile(
    r"\s*(?:<!doctype[^>]*>\s*)?(?:<html[^>]*>)?(?:\s*<meta[^>]*>|\s*<title>.*?</title>)*",
    re.I | re.S,
)


def with_home_link(document: bytes) -> bytes:
    """Give a generated report page the portfolio top bar, the current theme and a way back
    to the interface, without editing the file."""
    text = document.decode("utf-8", "replace")
    text = STALE_THEME.sub(lambda _: theme.HEAD, text, count=1)
    text = PAGE_SWITCHER.sub("", text)
    head = re.search(r"</head>", text, re.I)
    body = re.search(r"<body[^>]*>", text, re.I)
    extra = "" if CHROME_TAG in text else CHROME_TAG
    if head and extra:
        text = text[: head.start()] + extra + text[head.start() :]
        extra = ""
        body = re.search(r"<body[^>]*>", text, re.I)
    if body:
        return (text[: body.end()] + HOME_LINK + extra + text[body.end() :]).encode()
    at = PROLOGUE.match(text).end()
    return (text[:at] + extra + HOME_LINK + text[at:]).encode()


FILES_CSS = (
    "body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}"
    "main{max-width:960px;margin:0 auto;padding:16px}h1{font-size:22px;margin:8px 0 4px}"
    ".muted{color:var(--muted);font-size:13px}"
    "ul{list-style:none;margin:12px 0;padding:0;background:var(--surface);"
    "border:1px solid var(--border);border-radius:8px}"
    "li{display:flex;gap:10px;align-items:baseline;padding:6px 12px;border-bottom:1px solid var(--border)}"
    "li:last-child{border-bottom:0}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}"
    ".kind{font-size:11px;color:var(--muted);border:1px solid var(--border);border-radius:4px;padding:0 5px}"
)


def files_page(names: list[str]) -> bytes:
    """The shared results folder as a themed list, with the top bar and a way back."""

    def row(n: str) -> str:
        suffix = Path(n).suffix
        label = html.escape(n)
        href = f"/view/results/{n}" if suffix in (".md", ".json") else f"/{n}"
        raw = (
            f' <a class="muted" href="/{html.escape(n, quote=True)}">raw</a>'
            if href != f"/{n}"
            else ""
        )
        return (
            f'<li><a href="{html.escape(href, quote=True)}">{label}</a>{raw}'
            f'<span class="kind">{html.escape(suffix.lstrip("."))}</span></li>'
        )

    rows = "".join(row(n) for n in names)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>All files</title>{theme.HEAD}<style>{FILES_CSS}</style></head>"
        f'<body><main><h1>All files</h1><div class="muted">{len(names)} files in the shared '
        f"results folder</div><ul>{rows}</ul></main></body></html>"
    )
    return with_home_link(page.encode())


def served(file: Path) -> bytes:
    data = file.read_bytes()
    return with_home_link(data) if file.suffix == ".html" else data


class BenchError(ValueError):
    """A request the interface refuses; the message is shown to the user."""


# -- profiles ----------------------------------------------------------------


class ProfileStore:
    """Saved profiles: a local TOML file seeded from the tracked defaults."""

    def __init__(self, path: Path, defaults: Path = scoring.DEFAULT_PROFILES_PATH):
        self.path = path
        self.defaults = defaults
        self._lock = threading.Lock()

    def _defaults(self) -> list[scoring.Profile]:
        try:
            return scoring.load_profiles(self.defaults)
        except scoring.ScoringError:
            return []

    def _load(self) -> list[scoring.Profile]:
        if not self.path.is_file():
            return self._defaults()
        return scoring.load_profiles(self.path)

    def _write(self, profiles: list[scoring.Profile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(scoring.dump_profiles(profiles), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def list(self) -> list[scoring.Profile]:
        with self._lock:
            return self._load()

    def save(self, name: str, table: dict[str, Any]) -> scoring.Profile:
        try:
            profile = scoring.profile_from_dict(name, table)
        except scoring.ScoringError as exc:
            raise BenchError(str(exc)) from exc
        with self._lock:
            kept = [p for p in self._load() if p.name != name]
            self._write(sorted([*kept, profile], key=lambda p: p.name))
        return profile

    def delete(self, name: str) -> None:
        with self._lock:
            profiles = self._load()
            if name not in {p.name for p in profiles}:
                raise BenchError(f"no profile {name!r}")
            if len(profiles) == 1:
                raise BenchError("keep at least one profile")
            self._write([p for p in profiles if p.name != name])

    def reset(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)

    def get(self, name: str) -> scoring.Profile:
        for p in self.list():
            if p.name == name:
                return p
        raise BenchError(f"no profile {name!r}")

    def known_defaults(self) -> set[str]:
        return {p.name for p in self._defaults()}


# -- results -----------------------------------------------------------------


def result_entries(document: Any) -> tuple[str, dict[str, tuple[float, float, float]]]:
    """A result file's kind and its comparison entries (name -> accuracy, mean ms, p90 ms)."""
    from crew_chief import taskbench as tb

    if isinstance(document, list):
        entries = {}
        for item in document:
            entry = tb.result_entry(item)
            if entry is not None:
                entries[item["runner"]] = entry
        return "taskbench", entries
    if isinstance(document, dict) and "strategies" in document:
        entries = {
            name: (s["accuracy"], s["ms_mean"], s["ms_p90"])
            for name, s in document["strategies"].items()
            if name != "oracle" and s.get("accuracy") is not None
        }
        return "routebench", entries
    raise BenchError("not a taskbench or routebench result")


def rescore(
    entries: dict[str, tuple[float, float, float]], profile: scoring.Profile
) -> dict[str, Any]:
    ref = scoring.reference(entries)
    raw = {name: {"accuracy": a, "mean_ms": m, "p90_ms": p} for name, (a, m, p) in entries.items()}
    return {
        "profile": scoring.profile_to_dict(profile),
        "describe": profile.describe(),
        "reference": None if ref is None else {"mean": ref.mean, "p90": ref.p90},
        "entries": raw,
        "ranking": scoring.rank(profile, entries),
        "sensitivity": {
            f"{w:g}": names for w, names in scoring.sensitivity(profile, entries).items()
        },
    }


# -- jobs --------------------------------------------------------------------


def available_suites(suites_dir: Path = SUITES_DIR) -> list[str]:
    return sorted(p.stem for p in suites_dir.glob("*.json"))


def validate_spec(spec: Any, suites: list[str]) -> dict[str, Any]:
    """The job a request describes, or BenchError. Nothing in it reaches a shell."""
    if not isinstance(spec, dict):
        raise BenchError("job spec must be an object")
    kind = spec.get("kind")
    if kind not in RESULT_KINDS:
        raise BenchError("kind must be taskbench or routebench")
    picked = spec.get("suites")
    if not isinstance(picked, list) or not picked:
        raise BenchError("pick at least one suite")
    unknown = [s for s in picked if s not in suites]
    if unknown:
        raise BenchError(f"unknown suite: {unknown[0]!r}")
    runners = spec.get("runners")
    if not isinstance(runners, list) or not runners or len(runners) > 12:
        raise BenchError("pick between 1 and 12 runners")
    routers = spec.get("routers")
    if routers is None:
        routers = [spec["router"]] if spec.get("router") else ["systemone:clef-flash"]
    if not isinstance(routers, list) or not routers or len(routers) > 8:
        raise BenchError("pick between 1 and 8 routing models")
    for runner in [*runners, *routers]:
        if not isinstance(runner, str) or not RUNNER.fullmatch(runner):
            raise BenchError(f"bad runner spec {runner!r}")
    split = spec.get("split", "dev")
    if split not in ("dev", "heldout", "all"):
        raise BenchError("split must be dev, heldout or all")
    thresholds = spec.get("thresholds") or [0.6, 0.8, 0.95]
    if not (
        isinstance(thresholds, list)
        and len(thresholds) <= 8
        and all(
            isinstance(t, (int, float)) and not isinstance(t, bool) and 0 < t <= 1
            for t in thresholds
        )
    ):
        raise BenchError("thresholds must be numbers in (0, 1]")
    return {
        "kind": kind,
        "suites": list(dict.fromkeys(picked)),
        "runners": list(dict.fromkeys(runners)),
        "routers": list(dict.fromkeys(routers)),
        "split": split,
        "thresholds": [float(t) for t in thresholds],
        "private": bool(spec.get("private")),
    }


def build_steps(
    spec: dict[str, Any], out_dir: Path, profiles_path: Path | None, suites_dir: Path = SUITES_DIR
) -> list[list[str]]:
    """The command lines a job runs, one after the other."""
    base = [sys.executable, "-m", "crew_chief"]
    tail = ["--out", str(out_dir)]
    if profiles_path is not None and profiles_path.is_file():
        tail += ["--profiles", str(profiles_path)]
    paths = [str(suites_dir / f"{s}.json") for s in spec["suites"]]
    if spec["kind"] == "taskbench":
        runner_args = [a for r in spec["runners"] for a in ("--runner", r)]
        return [
            [*base, "taskbench", path, *runner_args, "--split", spec["split"], *tail]
            for path in paths
        ]
    candidates = [a for r in spec["runners"] for a in ("--candidate", r)]
    thresholds = [a for t in spec["thresholds"] for a in ("--threshold", f"{t:g}")]
    # routebench takes one router, so each routing model gets its own run, one after the other.
    return [
        [*base, "routebench", *paths, *candidates, "--router", router, *thresholds, *tail]
        for router in spec["routers"]
    ]


def gpu_used_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        ).stdout.split()
        return max(int(v) for v in out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class JobManager:
    """Runs jobs one at a time and keeps a record and a log for each."""

    def __init__(
        self,
        state: Path,
        results_dirs: dict[str, Path],
        profiles: ProfileStore,
        *,
        build: Callable[..., list[list[str]]] = build_steps,
        probe: Callable[[], int | None] = gpu_used_mib,
        suites: Callable[[], list[str]] = available_suites,
    ):
        self.dir = state / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.results_dirs = results_dirs
        self.profiles = profiles
        self.build, self.probe, self.suites = build, probe, suites
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancel: set[str] = set()
        for record in self.list():
            if record["status"] not in TERMINAL:
                self._update(record["id"], status="interrupted", finished=time.time())
        threading.Thread(target=self._worker, daemon=True, name="bench-jobs").start()

    # records
    def _path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def _read(self, job_id: str) -> dict[str, Any]:
        try:
            return json.loads(self._path(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BenchError(f"no job {job_id!r}") from exc

    def _update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            record = self._read(job_id)
            record.update(fields)
            tmp = self._path(job_id).with_suffix(".tmp")
            tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self._path(job_id))
            return record

    def list(self) -> list[dict[str, Any]]:
        records = []
        for path in self.dir.glob("*.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(records, key=lambda r: r.get("created", 0), reverse=True)

    def get(self, job_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id):
            raise BenchError(f"no job {job_id!r}")
        record = self._read(job_id)
        log = self.dir / f"{job_id}.log"
        try:
            with log.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - LOG_TAIL))
                record["log"] = fh.read().decode("utf-8", "replace")
        except OSError:
            record["log"] = ""
        return record

    # lifecycle
    def submit(self, spec: Any) -> dict[str, Any]:
        spec = validate_spec(spec, self.suites())
        job_id = secrets.token_hex(6)
        label = "private" if spec["private"] else "results"
        out_dir = self.results_dirs[label]
        steps = self.build(spec, out_dir, self.profiles.path)
        record = {
            "id": job_id,
            "kind": spec["kind"],
            "spec": spec,
            "status": "queued",
            "created": time.time(),
            "started": None,
            "finished": None,
            "out": label,
            "steps": steps,
            "step": 0,
            "units_total": (
                len(spec["suites"]) * len(spec["runners"])
                if spec["kind"] == "taskbench"
                else len(spec["runners"]) + 1
            ),
            "units_done": 0,
            "current": "",
            "gpu_used_mib_at_start": None,
            "outputs": [],
            "exit_codes": [],
        }
        with self._lock:
            self._path(job_id).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        self._queue.put(job_id)
        return record

    def cancel(self, job_id: str) -> dict[str, Any]:
        record = self.get(job_id)
        if record["status"] in TERMINAL:
            raise BenchError(f"job already {record['status']}")
        self._cancel.add(job_id)
        proc = self._procs.get(job_id)
        if proc is not None:
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGTERM)
        elif record["status"] == "queued":
            return self._update(job_id, status="cancelled", finished=time.time())
        return record

    def shutdown(self) -> None:
        """Stop the running job, if any, so no benchmark outlives the interface."""
        for job_id, proc in list(self._procs.items()):
            self._cancel.add(job_id)
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGTERM)

    def _worker(self) -> None:
        while True:
            self._run(self._queue.get())

    def _run(self, job_id: str) -> None:
        record = self._read(job_id)
        if record["status"] != "queued":
            return
        self._update(
            job_id,
            status="running",
            started=time.time(),
            gpu_used_mib_at_start=self.probe(),
        )
        log = self.dir / f"{job_id}.log"
        codes: list[int] = []
        with log.open("ab") as fh:
            for index, argv in enumerate(record["steps"]):
                if job_id in self._cancel:
                    break
                self._update(job_id, step=index + 1)
                fh.write(f"$ {' '.join(argv)}\n".encode())
                fh.flush()
                try:
                    proc = subprocess.Popen(
                        argv,
                        stdout=fh,
                        stderr=subprocess.STDOUT,
                        cwd=REPO_ROOT,
                        start_new_session=True,
                    )
                except OSError as exc:
                    fh.write(f"cannot start: {exc}\n".encode())
                    codes.append(127)
                    break
                self._procs[job_id] = proc
                while proc.poll() is None:
                    self._progress(job_id, log)
                    time.sleep(0.5)
                codes.append(proc.returncode)
                self._procs.pop(job_id, None)
                self._progress(job_id, log)
        cancelled = job_id in self._cancel
        self._cancel.discard(job_id)
        status = "cancelled" if cancelled else "done" if codes and not any(codes) else "failed"
        self._update(job_id, status=status, finished=time.time(), exit_codes=codes)
        self._progress(job_id, log)

    def _progress(self, job_id: str, log: Path) -> None:
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        lines = [line for line in text.splitlines() if line.strip()]
        record = self._read(job_id)
        out_dir = self.results_dirs[record["out"]]
        outputs: list[str] = []
        for match in re.finditer(r"^Saved: (\S+?)\.md\b", text, re.M):
            stem = Path(match.group(1)).name
            outputs += [
                f"{stem}{suffix}"
                for suffix in (".json", ".md", ".svg")
                if (out_dir / f"{stem}{suffix}").is_file()
            ]
        self._update(
            job_id,
            units_done=min(
                record["units_total"], sum(1 for line in lines if line.startswith("running "))
            ),
            current=lines[-1][:200] if lines else "",
            outputs=list(dict.fromkeys(outputs)),
        )


# -- the server --------------------------------------------------------------


def list_results(results_dirs: dict[str, Path], jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    produced = {(j["out"], name): j["id"] for j in jobs for name in j.get("outputs", [])}
    rows = []
    for label, directory in results_dirs.items():
        for path in directory.glob("*.json"):
            kind = path.name.split("-", 1)[0]
            if kind not in RESULT_KINDS:
                continue
            rows.append(
                {
                    "ref": f"{label}/{path.name}",
                    "kind": kind,
                    "name": path.stem,
                    "dir": label,
                    "modified": path.stat().st_mtime,
                    "job": produced.get((label, path.name)),
                    "files": [
                        f"{label}/{path.stem}{suffix}"
                        for suffix in (".md", ".svg", ".json")
                        if (directory / f"{path.stem}{suffix}").is_file()
                    ],
                }
            )
    return sorted(rows, key=lambda r: r["modified"], reverse=True)


class BenchApp:
    def __init__(self, state: Path, results_dir: Path):
        self.state = state
        self.public = results_dir
        self.results_dirs = {"results": results_dir, "private": state / "private-results"}
        self.results_dirs["private"].mkdir(parents=True, exist_ok=True)
        self.profiles = ProfileStore(state / "profiles.toml")
        self.jobs = JobManager(state, self.results_dirs, self.profiles)

    def resolve(self, ref: str) -> Path:
        label, _, name = ref.partition("/")
        directory = self.results_dirs.get(label)
        if directory is None or not FILE_NAME.fullmatch(name):
            raise BenchError("no such file")
        if Path(name).suffix not in SERVED_SUFFIXES:
            raise BenchError("no such file")
        path = directory / name
        if not path.is_file():
            raise BenchError("no such file")
        return path

    def models(self) -> dict[str, Any]:
        base = os.environ.get("CREW_CHIEF_URL", "http://localhost:11434").rstrip("/")
        names: list[str] = []
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as resp:
                names = sorted(m["name"] for m in json.load(resp).get("models", []))
        except (OSError, ValueError, KeyError):
            pass
        return {"systemone": list(SYSTEMONE_MODELS), "ollama": names}


class Handler(BaseHTTPRequestHandler):
    app: BenchApp
    allowed_hosts: set[str]
    server_version = "crew-chief-bench"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
        pass

    # plumbing
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in self.allowed_hosts

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return urlparse(origin).netloc == self.headers.get("Host")

    def _body(self) -> Any:
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise BenchError("send JSON")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise BenchError("request too large")
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError as exc:
            raise BenchError("invalid JSON") from exc

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            return self._json({"error": "bad host"}, HTTPStatus.FORBIDDEN)
        if method != "GET" and not self._origin_ok():
            return self._json({"error": "bad origin"}, HTTPStatus.FORBIDDEN)
        path = unquote(urlparse(self.path).path)
        try:
            self._route(method, path)
        except BenchError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # keep the server up; the log has the traceback
            sys.stderr.write(f"benchui: {method} {path}: {exc!r}\n")
            self._json({"error": "internal error"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    # routes
    def _route(self, method: str, path: str) -> None:
        app = self.app
        if method == "GET":
            if path == "/":
                from crew_chief.benchui_page import PAGE

                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if path == "/api/profiles":
                return self._json(
                    {
                        "profiles": [scoring.profile_to_dict(p) for p in app.profiles.list()],
                        "defaults": sorted(app.profiles.known_defaults()),
                    }
                )
            if path == "/api/suites":
                return self._json({"suites": available_suites()})
            if path == "/api/models":
                return self._json(app.models())
            if path == "/api/jobs":
                return self._json({"jobs": app.jobs.list()})
            if path.startswith("/api/jobs/"):
                return self._json(app.jobs.get(path.rsplit("/", 1)[1]))
            if path == "/api/results":
                return self._json({"results": list_results(app.results_dirs, app.jobs.list())})
            if path.startswith("/api/results/"):
                file = app.resolve(path[len("/api/results/") :])
                kind, entries = result_entries(json.loads(file.read_text(encoding="utf-8")))
                return self._json(
                    {
                        "kind": kind,
                        "entries": {
                            n: {"accuracy": a, "mean_ms": m, "p90_ms": p}
                            for n, (a, m, p) in entries.items()
                        },
                    }
                )
            if path == "/results/":
                names = sorted(
                    f.name
                    for f in app.public.iterdir()
                    if f.is_file() and f.suffix in SERVED_SUFFIXES and FILE_NAME.fullmatch(f.name)
                )
                return self._send(200, files_page(names), "text/html; charset=utf-8")
            if path.startswith("/view/"):
                ref = path[len("/view/") :]
                file = app.resolve(ref)
                text = file.read_text(encoding="utf-8", errors="replace")
                page = viewer.render(file.name, text, f"/files/{ref}")
                if page is None:  # only Markdown and JSON have a viewer; the rest is shown as is
                    return self._send(200, served(file), SERVED_SUFFIXES[file.suffix])
                return self._send(200, with_home_link(page.encode()), "text/html; charset=utf-8")
            if path.startswith("/files/"):
                file = app.resolve(path[len("/files/") :])
                return self._send(200, served(file), SERVED_SUFFIXES[file.suffix])
            if path.startswith("/_portfolio/"):
                from crew_chief.portfolio import site

                asset = site.resolve(
                    REPO_ROOT, vendored=Path(__file__).resolve().parent / "portfolio"
                ).response(path)
                if asset is None:
                    raise BenchError("not found")
                return self._send(200, *asset)
            # The shared results folder at the site root, as the static site served it
            # before the interface took over this hostname (latest.html, old report links).
            name = path.lstrip("/")
            if name and "/" not in name:
                file = app.resolve(f"results/{name}")
                return self._send(200, served(file), SERVED_SUFFIXES[file.suffix])
            raise BenchError("not found")
        if method == "POST":
            body = self._body()
            if path == "/api/rescore":
                return self._json(self._rescore(body))
            if path == "/api/profiles":
                if not isinstance(body, dict) or not isinstance(body.get("name"), str):
                    raise BenchError("profile needs a name")
                table = {k: v for k, v in body.items() if k != "name" and v is not None}
                profile = app.profiles.save(body["name"], table)
                return self._json({"saved": scoring.profile_to_dict(profile)})
            if path == "/api/profiles/reset":
                app.profiles.reset()
                return self._json({"reset": True})
            if path == "/api/jobs":
                return self._json(app.jobs.submit(body), HTTPStatus.CREATED)
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                return self._json(app.jobs.cancel(path.split("/")[3]))
            raise BenchError("not found")
        if method == "DELETE" and path.startswith("/api/profiles/"):
            app.profiles.delete(path.rsplit("/", 1)[1])
            return self._json({"deleted": True})
        raise BenchError("not found")

    def _rescore(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("profile"), dict):
            raise BenchError("send a profile and a result")
        table = {k: v for k, v in body["profile"].items() if k != "name" and v is not None}
        try:
            profile = scoring.profile_from_dict(str(body["profile"].get("name") or "draft"), table)
        except scoring.ScoringError as exc:
            raise BenchError(str(exc)) from exc
        file = self.app.resolve(str(body.get("result", "")))
        _, entries = result_entries(json.loads(file.read_text(encoding="utf-8")))
        return rescore(entries, profile)


def make_server(
    state: Path = DEFAULT_STATE,
    results_dir: Path = REPO_ROOT / "results",
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    allow_hosts: tuple[str, ...] = (),
) -> ThreadingHTTPServer:
    """``allow_hosts`` names extra Host headers to accept, for a reverse proxy in front."""
    state.mkdir(parents=True, exist_ok=True)
    handler = type(
        "BoundHandler",
        (Handler,),
        {
            "app": BenchApp(state, results_dir),
            "allowed_hosts": {"127.0.0.1", "localhost", "::1", *allow_hosts},
        },
    )
    return ThreadingHTTPServer((host, port), handler)
