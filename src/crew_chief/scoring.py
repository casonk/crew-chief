"""crew_chief.scoring — one number for accuracy and time to inference.

A profile (``config/scoring-profiles.toml``) states how much a use case values
speed. ``score`` combines accuracy with a speed score that is 1 at or under a
target latency, 0 at or over a ceiling and log-linear between, computed on the
mean and on the p90 so a slow tail costs something. Hard gates (minimum accuracy,
maximum p90) rank a model below every model that passes.

The score orders a list; it does not decide. ``rank`` marks every entry within
``tie_margin`` of the best as tied, and ``sensitivity`` shows who leads at other
weights, because the weights are a judgment and the ranking moves with them.

Stdlib only. TOML needs ``tomllib`` (Python 3.11+) or the ``tomli`` back-port.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised only on 3.10
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_PATH = Path(
    os.environ.get("CREW_CHIEF_SCORING_PROFILES", REPO_ROOT / "config" / "scoring-profiles.toml")
)
SENSITIVITY_WEIGHTS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)


class ScoringError(ValueError):
    """The profile file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    accuracy_weight: float
    target_ms: float
    ceiling_ms: float
    tail_weight: float = 0.0
    min_accuracy: float | None = None
    max_p90_ms: float | None = None
    tie_margin: float = 0.02

    @property
    def speed_weight(self) -> float:
        return 1.0 - self.accuracy_weight

    def describe(self) -> str:
        gates = []
        if self.min_accuracy is not None:
            gates.append(f"accuracy >= {self.min_accuracy:g}")
        if self.max_p90_ms is not None:
            gates.append(f"p90 <= {self.max_p90_ms:g} ms")
        return (
            f"{self.accuracy_weight:g} accuracy + {self.speed_weight:g} speed; full speed credit "
            f"at {self.target_ms:g} ms or less, none at {self.ceiling_ms:g} ms or more"
            f"{f', {self.tail_weight:g} of it from p90' if self.tail_weight else ''}; "
            f"gates: {', '.join(gates) or 'none'}; ties within {self.tie_margin:g}"
        )


@dataclass(frozen=True)
class Score:
    value: float | None  # None when gated
    quality: float
    speed: float
    gate: str | None = None


def _profile(name: str, table: dict[str, Any]) -> Profile:
    def number(key: str, default: float | None = None) -> float | None:
        value = table.get(key, default)
        if value is None:
            return None
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ScoringError(f"profile {name!r}: {key} must be a number")
        return float(value)

    profile = Profile(
        name=name,
        description=str(table.get("description", "")),
        accuracy_weight=number("accuracy_weight"),  # type: ignore[arg-type]
        target_ms=number("target_ms"),  # type: ignore[arg-type]
        ceiling_ms=number("ceiling_ms"),  # type: ignore[arg-type]
        tail_weight=number("tail_weight", 0.0),  # type: ignore[arg-type]
        min_accuracy=number("min_accuracy"),
        max_p90_ms=number("max_p90_ms"),
        tie_margin=number("tie_margin", 0.02),  # type: ignore[arg-type]
    )
    for key in ("accuracy_weight", "tail_weight"):
        if not 0 <= getattr(profile, key) <= 1:
            raise ScoringError(f"profile {name!r}: {key} must be between 0 and 1")
    if not 0 < profile.target_ms < profile.ceiling_ms:
        raise ScoringError(f"profile {name!r}: need 0 < target_ms < ceiling_ms")
    if profile.min_accuracy is not None and not 0 <= profile.min_accuracy <= 1:
        raise ScoringError(f"profile {name!r}: min_accuracy must be between 0 and 1")
    if profile.max_p90_ms is not None and profile.max_p90_ms <= 0:
        raise ScoringError(f"profile {name!r}: max_p90_ms must be positive")
    if profile.tie_margin < 0:
        raise ScoringError(f"profile {name!r}: tie_margin cannot be negative")
    return profile


def load_profiles(path: Path = DEFAULT_PROFILES_PATH) -> list[Profile]:
    if tomllib is None:
        raise ScoringError("reading scoring profiles needs Python 3.11+ or `pip install tomli`")
    if not path.is_file():
        raise ScoringError(f"scoring profiles not found: {path}")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ScoringError(f"{path}: {exc}") from exc
    tables = document.get("profiles", {})
    if not tables:
        raise ScoringError(f"{path}: no [profiles.*] tables")
    return [_profile(name, table) for name, table in tables.items()]


def speed_score(ms: float, target_ms: float, ceiling_ms: float) -> float:
    """1 at or under the target, 0 at or over the ceiling, log-linear between."""
    if ms <= target_ms:
        return 1.0
    if ms >= ceiling_ms:
        return 0.0
    return 1.0 - math.log(ms / target_ms) / math.log(ceiling_ms / target_ms)


def score(
    profile: Profile,
    accuracy: float,
    mean_ms: float,
    p90_ms: float,
    *,
    accuracy_weight: float | None = None,
) -> Score:
    """Combine one model's accuracy and latency under a profile.

    ``accuracy_weight`` overrides the profile's weight, for sensitivity sweeps;
    the gates always come from the profile.
    """
    weight = profile.accuracy_weight if accuracy_weight is None else accuracy_weight
    speed = (1 - profile.tail_weight) * speed_score(
        mean_ms, profile.target_ms, profile.ceiling_ms
    ) + profile.tail_weight * speed_score(p90_ms, profile.target_ms, profile.ceiling_ms)
    gate = None
    if profile.min_accuracy is not None and accuracy < profile.min_accuracy:
        gate = f"accuracy {accuracy:.2f} < {profile.min_accuracy:g}"
    elif profile.max_p90_ms is not None and p90_ms > profile.max_p90_ms:
        gate = f"p90 {p90_ms:.0f} ms > {profile.max_p90_ms:g} ms"
    value = None if gate else weight * accuracy + (1 - weight) * speed
    return Score(value, accuracy, speed, gate)


def rank(
    profile: Profile,
    entries: dict[str, tuple[float, float, float]],
    *,
    accuracy_weight: float | None = None,
) -> list[dict[str, Any]]:
    """Entries (name -> accuracy, mean ms, p90 ms) best first; gated ones last.

    ``tied`` is true for every passing entry within ``tie_margin`` of the best.
    """
    scored = {
        name: score(profile, acc, mean, p90, accuracy_weight=accuracy_weight)
        for name, (acc, mean, p90) in entries.items()
    }
    order = sorted(
        scored,
        key=lambda n: (scored[n].value is None, -(scored[n].value or 0.0), n),
    )
    best = scored[order[0]].value if order else None
    return [
        {
            "name": name,
            "score": None if scored[name].value is None else round(scored[name].value, 4),
            "quality": round(scored[name].quality, 4),
            "speed": round(scored[name].speed, 4),
            "gate": scored[name].gate,
            "tied": best is not None
            and scored[name].value is not None
            and scored[name].value >= best - profile.tie_margin,
        }
        for name in order
    ]


def sensitivity(
    profile: Profile,
    entries: dict[str, tuple[float, float, float]],
    weights: tuple[float, ...] = SENSITIVITY_WEIGHTS,
) -> dict[float, list[str]]:
    """For each accuracy weight, the entries tied for the lead."""
    out = {}
    for weight in sorted({*weights, profile.accuracy_weight}):
        ranking = rank(profile, entries, accuracy_weight=weight)
        out[weight] = [row["name"] for row in ranking if row["tied"]]
    return out
