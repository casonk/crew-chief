"""crew_chief.model_storage — move retired models down storage tiers, then delete them.

Tiers, fastest first (``serving_policy.TIERS``): ``hot`` is the Ollama models
volume (M.2), ``warm`` a SATA SSD, ``cold`` a hard disk. Every tier directory
uses Ollama's own layout (``manifests/registry.ollama.ai/...`` plus
``blobs/sha256-...``), so a model in any tier can be benchmarked in place with
llama.cpp and brought back to Ollama by copying.

Rotation, from ``[rotation]`` in the serving policy:

- a ``retired`` model on hot storage moves to warm;
- after ``demote_after_days`` in warm it moves to cold;
- after ``delete_after_days`` in cold it is deleted (only with ``--delete``);
- each tier is benchmarked every ``bench_every_days``, so the further a model
  falls the less often it costs GPU time.

Which tier holds a model is read from disk. When it got there and when it was
last benchmarked live in a local state file. Tier paths are host-specific and
live in a local config file, never in the tracked policy:

    # ~/.config/crew-chief/storage.toml
    [tiers]
    warm = "/path/to/sata-ssd/crew-chief-models"
    cold = "/path/to/hdd/crew-chief-models"

Stdlib only.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from crew_chief.serving_policy import TIERS, ServingPolicy, canonical, tomllib

REGISTRY = "registry.ollama.ai"
MODELS_VOLUME = os.environ.get("CREW_CHIEF_MODELS_VOLUME", "crew-chief-models")
_XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
_XDG_STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("CREW_CHIEF_STORAGE_CONFIG", _XDG_CONFIG / "crew-chief" / "storage.toml")
)
DEFAULT_STATE_PATH = Path(
    os.environ.get("CREW_CHIEF_STORAGE_STATE", _XDG_STATE / "crew-chief" / "model-storage.json")
)


class StorageError(RuntimeError):
    """Tier configuration is missing or a move cannot be done safely."""


# ---------------------------------------------------------------------------
# Ollama's on-disk layout
# ---------------------------------------------------------------------------


def manifest_path(models_dir: Path, name: str) -> Path:
    repo, tag = canonical(name).rsplit(":", 1)
    if "/" not in repo:
        repo = f"library/{repo}"
    return models_dir / "manifests" / REGISTRY / repo / tag


def blob_names(manifest: Path) -> list[str]:
    """Blob file names a manifest needs: its config and every layer."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    digests = [data["config"]["digest"]] if data.get("config") else []
    digests += [layer["digest"] for layer in data.get("layers", [])]
    return [d.replace(":", "-") for d in digests]


def list_models(models_dir: Path) -> list[str]:
    root = models_dir / "manifests" / REGISTRY
    if not root.is_dir():
        return []
    names = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        repo, tag = str(path.parent.relative_to(root)), path.name
        repo = repo.removeprefix("library/")
        names.append(f"{repo}:{tag}")
    return names


def _referenced(models_dir: Path, skip: str | None = None) -> set[str]:
    wanted = canonical(skip) if skip else None
    blobs: set[str] = set()
    for name in list_models(models_dir):
        if name != wanted:
            blobs.update(blob_names(manifest_path(models_dir, name)))
    return blobs


def _copy(src: Path, dst: Path) -> None:
    """Copy through a temporary name so a partial file never looks complete."""
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".partial")
    shutil.copyfile(src, tmp)
    if tmp.stat().st_size != src.stat().st_size:
        tmp.unlink(missing_ok=True)
        raise StorageError(f"short copy of {src.name}")
    tmp.replace(dst)


def _remove(name: str, models_dir: Path) -> int:
    """Remove a model's manifest and the blobs no other model there uses."""
    manifest = manifest_path(models_dir, name)
    blobs = blob_names(manifest)
    manifest.unlink()
    for parent in manifest.parents:  # tidy empty repo directories
        if parent == models_dir / "manifests" or any(parent.iterdir()):
            break
        parent.rmdir()
    still_used = _referenced(models_dir)
    freed = 0
    for blob in blobs:
        path = models_dir / "blobs" / blob
        if blob not in still_used and path.exists():
            freed += path.stat().st_size
            path.unlink()
    return freed


def transfer(name: str, src: Path, dst: Path) -> int:
    """Move a model between tier directories; return the bytes freed at ``src``.

    Blobs are copied before the manifest, and the source is removed only once
    the destination is complete, so an interrupted move leaves the model whole
    in at least one tier. Blobs another model in ``src`` still uses are copied,
    not moved.
    """
    manifest = manifest_path(src, name)
    if not manifest.is_file():
        raise StorageError(f"{name} is not in {src}")
    for blob in blob_names(manifest):
        _copy(src / "blobs" / blob, dst / "blobs" / blob)
    _copy(manifest, manifest_path(dst, name))
    return _remove(name, src)


def delete(name: str, models_dir: Path) -> int:
    if not manifest_path(models_dir, name).is_file():
        raise StorageError(f"{name} is not in {models_dir}")
    return _remove(name, models_dir)


# ---------------------------------------------------------------------------
# Tier configuration and state
# ---------------------------------------------------------------------------


def hot_dir() -> Path:
    """The Ollama volume's models directory, found through Podman."""
    try:
        mount = subprocess.run(
            ["podman", "volume", "inspect", MODELS_VOLUME, "--format", "{{.Mountpoint}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StorageError(f"cannot find the {MODELS_VOLUME} volume ({exc})") from exc
    return Path(mount) / "models"


def load_tiers(path: Path = DEFAULT_CONFIG_PATH, hot: Callable[[], Path] = hot_dir) -> dict:
    """Map each tier to its directory. ``hot`` defaults to the Ollama volume."""
    if tomllib is None:
        raise StorageError("reading storage.toml needs Python 3.11+ or `pip install tomli`")
    if not path.is_file():
        raise StorageError(f"no storage tiers configured: create {path} (see the module docs)")
    table = tomllib.loads(path.read_text(encoding="utf-8")).get("tiers", {})
    unknown = sorted(set(table) - set(TIERS))
    if unknown:
        raise StorageError(f"{path}: unknown tier(s): {', '.join(unknown)}")
    missing = [t for t in TIERS[1:] if t not in table]
    if missing:
        raise StorageError(f"{path}: [tiers] needs {', '.join(missing)}")
    tiers = {t: Path(table[t]).expanduser() for t in TIERS if t in table}
    tiers.setdefault("hot", hot())
    return {t: tiers[t] for t in TIERS}


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, dict], path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def locate(tiers: dict[str, Path]) -> dict[str, str]:
    """Which tier holds each model, read from disk (the fastest tier wins)."""
    found: dict[str, str] = {}
    for tier in reversed(TIERS):
        for name in list_models(tiers[tier]):
            found[name] = tier
    return found


def sync_state(state: dict[str, dict], where: dict[str, str], today: date) -> dict[str, dict]:
    """Start the clock for models seen in a new tier; drop models that are gone."""
    synced = {}
    for name, tier in where.items():
        entry = dict(state.get(name, {}))
        if entry.get("tier") != tier:
            entry["tier"], entry["since"] = tier, today.isoformat()
        synced[name] = entry
    return synced


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    kind: str  # "move" or "delete"
    model: str
    source: str
    target: str | None
    reason: str


def _days(since: str | None, today: date) -> int:
    return (today - date.fromisoformat(since)).days if since else 0


def plan(
    policy: ServingPolicy, state: dict[str, dict], today: date
) -> tuple[list[Action], list[str]]:
    """Return the moves and deletions due, and notes for a reviewer."""
    actions: list[Action] = []
    notes: list[str] = []
    for name, entry in sorted(state.items()):
        tier = entry["tier"]
        model = policy.get(name)
        status = model.status if model else "unlisted"
        age = _days(entry.get("since"), today)
        rule = policy.rotation[tier]
        if tier == "hot":
            if status == "retired":
                actions.append(Action("move", name, "hot", "warm", "retired"))
            continue
        if status != "retired":
            notes.append(
                f"{name} is {status} but stored in {tier}; "
                f"`crew-chief storage restore {name}` to serve it again"
            )
            continue
        if rule.demote_after_days and age >= rule.demote_after_days:
            lower = TIERS[TIERS.index(tier) + 1]
            reason = f"{age} days in {tier}"
            actions.append(Action("move", name, tier, lower, reason))
        elif rule.delete_after_days and age >= rule.delete_after_days:
            actions.append(Action("delete", name, tier, None, f"{age} days in {tier}"))
    return actions, notes


def due(policy: ServingPolicy, state: dict[str, dict], today: date) -> list[tuple[str, str]]:
    """Models below hot whose benchmark is older than their tier's cadence.

    Hot models are covered by the weekly benchmark timer.
    """
    result = []
    for name, entry in sorted(state.items()):
        tier = entry["tier"]
        if tier == "hot":
            continue
        last = entry.get("last_benched")
        if last is None or _days(last, today) >= policy.rotation[tier].bench_every_days:
            result.append((name, tier))
    return result


def unload(ollama_url: str, name: str) -> None:
    """Ask Ollama to drop a model from memory before its files move (best effort)."""
    body = json.dumps({"model": name, "keep_alive": 0}).encode()
    request = urllib.request.Request(
        f"{ollama_url}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with contextlib.suppress(OSError):
        urllib.request.urlopen(request, timeout=30).close()


def execute(
    action: Action,
    tiers: dict[str, Path],
    state: dict[str, dict],
    today: date,
    before_leaving_hot: Callable[[str], None] = lambda name: None,
) -> int:
    """Carry out one action and record it; return the bytes freed."""
    if action.source == "hot":
        before_leaving_hot(action.model)
    if action.kind == "delete":
        freed = delete(action.model, tiers[action.source])
        state.pop(action.model, None)
        return freed
    freed = transfer(action.model, tiers[action.source], tiers[action.target])
    entry = state.setdefault(action.model, {})
    entry["tier"], entry["since"] = action.target, today.isoformat()
    return freed
