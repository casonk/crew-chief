"""Start verbose, get quieter only while the service stays healthy.

A long-running service is hardest to debug right after it starts or changes, and quietest when
nothing is wrong. The policy therefore starts at ``start`` (DEBUG), steps one level down the
ladder after each ``degrade_after`` seconds with no WARNING-or-worse record, and never goes below
``floor``. Any WARNING or ERROR record returns it to ``start`` and restarts the clock, so the
detail is there when the next failure is investigated.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

LADDER = ("DEBUG", "INFO", "WARNING", "ERROR")


class _IssueWatcher(logging.Handler):
    def __init__(self, policy: LogLevelPolicy) -> None:
        super().__init__(level=logging.WARNING)
        self._policy = policy

    def emit(self, record: logging.LogRecord) -> None:
        self._policy.note_issue()


class LogLevelPolicy:
    def __init__(
        self,
        *,
        start: str = "DEBUG",
        floor: str = "INFO",
        degrade_after: float = 86400.0,
        clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
    ) -> None:
        if start not in LADDER or floor not in LADDER:
            raise ValueError(f"levels must be one of {LADDER}")
        # A floor more verbose than the start would mean "never degrade": clamp to the start.
        self.start = start
        self.floor = floor if LADDER.index(floor) >= LADDER.index(start) else start
        self.degrade_after = degrade_after
        self._clock = clock
        self._logger = logger or logging.getLogger()
        self.level = start
        self._since = clock()
        self._watcher = _IssueWatcher(self)
        self._logger.addHandler(self._watcher)
        self._apply()

    def _apply(self) -> None:
        self._logger.setLevel(getattr(logging, self.level))

    def note_issue(self) -> None:
        """A warning or error was logged: go back to full detail and restart the clock."""
        self._since = self._clock()
        if self.level != self.start:
            self.level = self.start
            self._apply()
            self._logger.warning("Log level restored to %s after an issue.", self.start)

    def tick(self) -> str:
        """Step one level down when the service has been clean for ``degrade_after`` seconds."""
        now = self._clock()
        if self.level != self.floor and now - self._since >= self.degrade_after:
            self.level = LADDER[LADDER.index(self.level) + 1]
            self._since = now
            self._apply()
            self._logger.info("No issues for %ds; log level lowered to %s.", self.degrade_after, self.level)
        return self.level
