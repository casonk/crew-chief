"""An optional decision-model gate in front of the listener's command extraction.

A small decision model (``[tasks."message-routing"]`` in the serving policy)
reads the message and says what kind it is. A message it is confident is an
automated notification or small talk skips the slower chat-model step, which
could only have declined it. The gate never widens anything: a message that
passes still goes through the same extraction, allowlist and dispatcher, and
any doubt or error lets the message through unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from crew_chief import serving_policy, taskbench

log = logging.getLogger(__name__)

TASK_NAME = "message-routing"
# Intents the chat model could only decline; "question" is left to it because
# an informational request such as "how full is the disk?" can be a command.
SKIPPED_INTENTS = frozenset({"notification", "conversation"})
DEFAULT_THRESHOLD = 0.8
# Must match the `intent` question in benchmarks/decisions/message-routing.json
# (a test compares them), so the policy's benchmark evidence describes this gate.
INTENT = taskbench.Question(
    qid="intent",
    type="choice",
    instructions="What kind of message is this?",
    criteria={
        "command": "Asks the assistant to run, check, change or fix something on the server or its services",
        "question": "Asks for information or an explanation; no action on any system",
        "conversation": "Greeting, thanks, acknowledgement or small talk",
        "notification": "Automated message not addressed to the assistant: receipts, shipping, alerts, newsletters, reminders",
    },
)


@dataclass(frozen=True)
class Decision:
    intent: str | None
    confidence: float
    model: str = ""

    def skip(self, threshold: float) -> bool:
        return self.intent in SKIPPED_INTENTS and self.confidence >= threshold


class Gate:
    """Classifies messages with the policy's ``message-routing`` decision model."""

    def __init__(self, models: list[str], threshold: float = DEFAULT_THRESHOLD, make_runner=None):
        self.models = models
        self.threshold = threshold
        self._make_runner = make_runner or taskbench.make_runner
        self._task = taskbench.Task(
            name=TASK_NAME, description="", questions={"intent": INTENT}, items=[]
        )

    @classmethod
    def from_policy(
        cls, threshold: float = DEFAULT_THRESHOLD, path: Path | None = None
    ) -> Gate | None:
        """A gate for the policy's reviewed ``systemone`` task, or None when there is none."""
        try:
            policy = serving_policy.load_policy(path) if path else serving_policy.load_policy()
        except serving_policy.PolicyError as exc:
            log.warning("Decision gate off: %s", exc)
            return None
        task = policy.task(TASK_NAME)
        if task is None or task.runner != "systemone" or task.status not in ("default", "beta"):
            log.warning("Decision gate off: no reviewed systemone task %r in the policy", TASK_NAME)
            return None
        return cls(task.chain, threshold)

    def classify(self, text: str) -> Decision:
        """The first working model's answer; an undecided Decision when none answers."""
        for model in self.models:
            try:
                runner = self._make_runner(f"systemone:{model}", self._task)
                answer = runner.answer(self._task, text)["intent"]
            except Exception as exc:
                log.warning("Decision gate: %s failed: %s", model, exc)
                continue
            if answer.value is None or not answer.probabilities:
                continue
            return Decision(answer.value, answer.probabilities.get(answer.value, 0.0), model)
        return Decision(None, 0.0)

    def should_skip(self, text: str) -> tuple[bool, Decision]:
        decision = self.classify(text)
        return decision.skip(self.threshold), decision


def build(enabled: bool, threshold: float) -> Gate | None:
    """The gate the listener should use, or None when it is off or unavailable."""
    return Gate.from_policy(threshold) if enabled else None


def describe(decision: Decision) -> str:
    return f"{decision.intent} {decision.confidence:.0%} by {decision.model}"


__all__ = ["Decision", "Gate", "SKIPPED_INTENTS", "build", "describe"]
