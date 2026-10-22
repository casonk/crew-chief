"""crew_chief.serving_policy — which backend serves each local model, and how.

The policy lives in ``config/serving-policy.toml`` (tracked). Each entry is a
reviewed decision: backend, context window, KV-cache type, flash attention,
the GPU memory the configuration needs, a status, and the benchmark evidence
behind it. Changes go through a pull request that adds or cites evidence;
traction-control's portfolio audit runs ``crew-chief policy check`` to catch
drift between the policy and what is actually pulled and served.

Stdlib only. TOML needs ``tomllib`` (Python 3.11+) or the ``tomli`` back-port.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised only on 3.10
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = Path(
    os.environ.get("CREW_CHIEF_SERVING_POLICY", REPO_ROOT / "config" / "serving-policy.toml")
)

BACKENDS = ("ollama", "llamacpp")
STATUSES = ("default", "beta", "unreviewed", "retired")
KV_TYPES = ("f16", "q8_0", "q4_0")
# Evidence older than this is reported as stale by `policy check`.
EVIDENCE_MAX_AGE_DAYS = 120
# Storage tiers, fastest first: hot is the Ollama volume (M.2), warm a SATA SSD,
# cold a hard disk. Retired models move down them and are benchmarked less often.
TIERS = ("hot", "warm", "cold")


def canonical(name: str) -> str:
    """Ollama's full model name: an untagged name means ``:latest``."""
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


class PolicyError(ValueError):
    """The policy file is missing, unreadable, or structurally invalid."""


@dataclass(frozen=True)
class ModelPolicy:
    name: str
    status: str = "unreviewed"
    backend: str = "ollama"
    context: int | None = None
    kv_cache: str = "f16"
    flash_attention: bool = True
    gpu_mib: int | None = None
    evidence: tuple[str, ...] = ()
    reviewed: str = ""
    note: str = ""


@dataclass(frozen=True)
class TierRule:
    """How often a tier's models are benchmarked, and how long they stay in it."""

    bench_every_days: int
    demote_after_days: int | None = None  # then move to the next tier down
    delete_after_days: int | None = None  # bottom tier only: then delete


DEFAULT_ROTATION = {
    "hot": TierRule(bench_every_days=7),
    "warm": TierRule(bench_every_days=30, demote_after_days=90),
    "cold": TierRule(bench_every_days=90, delete_after_days=180),
}


@dataclass(frozen=True)
class ServingPolicy:
    models: dict[str, ModelPolicy]
    backend_urls: dict[str, str] = field(default_factory=dict)
    rotation: dict[str, TierRule] = field(default_factory=lambda: dict(DEFAULT_ROTATION))

    def get(self, model: str) -> ModelPolicy | None:
        wanted = canonical(model)
        for name, entry in self.models.items():
            if canonical(name) == wanted:
                return entry
        return None

    def url_for(self, backend: str) -> str:
        defaults = {"ollama": "http://localhost:11434", "llamacpp": "http://localhost:8081"}
        return self.backend_urls.get(backend, defaults[backend]).rstrip("/")


def _entry(name: str, table: dict) -> ModelPolicy:
    where = f'[models."{name}"]'
    known = set(ModelPolicy.__dataclass_fields__) - {"name"}
    unknown = sorted(set(table) - known)
    if unknown:
        raise PolicyError(f"{where}: unknown key(s): {', '.join(unknown)}")
    status = table.get("status", "unreviewed")
    backend = table.get("backend", "ollama")
    kv = table.get("kv_cache", "f16")
    if status not in STATUSES:
        raise PolicyError(f"{where}: status must be one of {', '.join(STATUSES)}")
    if backend not in BACKENDS:
        raise PolicyError(f"{where}: backend must be one of {', '.join(BACKENDS)}")
    if kv not in KV_TYPES:
        raise PolicyError(f"{where}: kv_cache must be one of {', '.join(KV_TYPES)}")
    for key in ("context", "gpu_mib"):
        value = table.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise PolicyError(f"{where}: {key} must be a whole number")
    evidence = table.get("evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        raise PolicyError(f"{where}: evidence must be a list of repo-relative paths")
    return ModelPolicy(
        name=name,
        status=status,
        backend=backend,
        context=table.get("context"),
        kv_cache=kv,
        flash_attention=bool(table.get("flash_attention", True)),
        gpu_mib=table.get("gpu_mib"),
        evidence=tuple(evidence),
        reviewed=str(table.get("reviewed", "")),
        note=str(table.get("note", "")),
    )


def _rotation(document: dict) -> dict[str, TierRule]:
    table = document.get("rotation", {})
    unknown = sorted(set(table) - set(TIERS))
    if unknown:
        raise PolicyError(f"[rotation]: unknown tier(s): {', '.join(unknown)}")
    rules = dict(DEFAULT_ROTATION)
    known = set(TierRule.__dataclass_fields__)
    for tier, values in table.items():
        where = f"[rotation.{tier}]"
        extra = sorted(set(values) - known)
        if extra:
            raise PolicyError(f"{where}: unknown key(s): {', '.join(extra)}")
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PolicyError(f"{where}: {key} must be a positive whole number of days")
        merged = {**DEFAULT_ROTATION[tier].__dict__, **values}
        rules[tier] = TierRule(**merged)
    if rules["cold"].demote_after_days is not None:
        raise PolicyError("[rotation.cold]: the bottom tier has delete_after_days, not demote")
    for tier in TIERS[:-1]:
        if rules[tier].delete_after_days is not None:
            raise PolicyError(f"[rotation.{tier}]: only the bottom tier deletes")
    return rules


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> ServingPolicy:
    if tomllib is None:
        raise PolicyError("reading the serving policy needs Python 3.11+ or `pip install tomli`")
    if not path.is_file():
        raise PolicyError(f"serving policy not found: {path}")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"{path}: {exc}") from exc
    models = {name: _entry(name, table) for name, table in document.get("models", {}).items()}
    urls = {k: str(v) for k, v in document.get("backends", {}).items() if k in BACKENDS}
    return ServingPolicy(models=models, backend_urls=urls, rotation=_rotation(document))


def review(
    policy: ServingPolicy,
    repo_root: Path = REPO_ROOT,
    pulled: list[str] | None = None,
    today: date | None = None,
    below_hot: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the policy, and for drift when ``pulled`` is given.

    ``below_hot`` maps models whose files live on warm or cold storage (Ollama
    lists them through stubs) to their tier. Errors break the governance
    contract; warnings need a reviewer's eye.
    """
    errors: list[str] = []
    warnings: list[str] = []
    today = today or date.today()
    for model in policy.models.values():
        label = f"{model.name} ({model.status})"
        if model.status in ("default", "beta"):
            if not model.evidence:
                errors.append(f"{label}: no benchmark evidence cited")
            if not model.reviewed:
                errors.append(f"{label}: no reviewed date")
        if (
            model.backend == "llamacpp"
            and model.status != "retired"
            and (model.context is None or model.gpu_mib is None)
        ):
            errors.append(f"{label}: llamacpp entries need context and gpu_mib")
        for item in model.evidence:
            if not (repo_root / item).is_file():
                errors.append(f"{label}: evidence file missing: {item}")
        if model.reviewed and model.status in ("default", "beta"):
            try:
                age = (today - date.fromisoformat(model.reviewed)).days
            except ValueError:
                errors.append(f"{label}: reviewed must be YYYY-MM-DD")
            else:
                if age > EVIDENCE_MAX_AGE_DAYS:
                    warnings.append(f"{label}: reviewed {age} days ago; re-benchmark")

    if pulled is not None:
        have = {canonical(name) for name in pulled}
        listed = {canonical(name) for name in policy.models}
        for name in sorted(set(pulled)):
            if canonical(name) not in listed:
                errors.append(f"{name}: pulled in Ollama but missing from the serving policy")
        for model in policy.models.values():
            is_pulled = canonical(model.name) in have
            if model.status != "retired" and not is_pulled:
                warnings.append(f"{model.name}: in the policy but not pulled")
            tier = (below_hot or {}).get(canonical(model.name))
            if model.status == "retired" and is_pulled and tier is None:
                warnings.append(
                    f"{model.name}: retired but still on hot storage; run `crew-chief storage apply`"
                )
            if model.status != "retired" and tier is not None:
                warnings.append(
                    f"{model.name}: {model.status} but stored in {tier}; "
                    f"run `crew-chief storage restore {model.name}`"
                )
    return errors, warnings


def pulled_models(ollama_url: str, timeout: int = 10) -> list[str]:
    try:
        with urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=timeout) as resp:
            return [m["name"] for m in json.loads(resp.read().decode()).get("models", [])]
    except (urllib.error.URLError, OSError) as exc:
        raise PolicyError(f"Ollama is not reachable at {ollama_url} ({exc})") from exc


def describe(model: ModelPolicy) -> str:
    parts = [f"{model.name}: {model.status}, {model.backend}"]
    if model.context:
        parts.append(f"context {model.context}")
    parts.append(f"kv {model.kv_cache}")
    if model.gpu_mib:
        parts.append(f"{model.gpu_mib} MiB")
    text = ", ".join(parts)
    return text + (f" — {model.note}" if model.note else "")
