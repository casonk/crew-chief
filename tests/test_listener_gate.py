"""The optional decision-model gate in front of the listener's command extraction."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from crew_chief import listener_gate, taskbench
from crew_chief.config_loader import ConfigError, ListenerConfig, load
from crew_chief.listener import IncomingMessage, _process_message

ROOT = Path(__file__).resolve().parents[1]
POLICY = """
[tasks."message-routing"]
status = "{status}"
runner = "{runner}"
model = "clef-flash"
fallback = ["nimble"]
evidence = ["results/e.md"]
reviewed = "2026-10-29"
"""


def _policy(status="beta", runner="systemone") -> Path:
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "policy.toml"
    path.write_text(POLICY.format(status=status, runner=runner), encoding="utf-8")
    _policy.keep.append(tmp)
    return path


_policy.keep = []


class FakeRunner:
    def __init__(self, probabilities=None, error=None):
        self.probabilities, self.error = probabilities, error

    def answer(self, task, state):
        if self.error:
            raise self.error
        if self.probabilities is None:
            return {"intent": taskbench.Answer(None)}
        best = max(self.probabilities, key=self.probabilities.get)
        return {"intent": taskbench.Answer(best, self.probabilities)}


def gate_with(*runners, threshold=0.8):
    queue = list(runners)
    seen = []

    def make(spec, task):
        seen.append(spec)
        return queue.pop(0)

    gate = listener_gate.Gate(["clef-flash", "nimble"], threshold, make_runner=make)
    gate.seen = seen
    return gate


class IntentQuestionTests(unittest.TestCase):
    def test_the_question_matches_the_benchmark_suite(self):
        suite = json.loads((ROOT / "benchmarks/decisions/message-routing.json").read_text())
        spec = suite["questions"]["intent"]
        self.assertEqual(listener_gate.INTENT.instructions, spec["instructions"])
        self.assertEqual(listener_gate.INTENT.criteria, spec["criteria"])
        self.assertEqual(listener_gate.INTENT.type, spec["type"])


class DecisionTests(unittest.TestCase):
    def test_only_a_confident_notification_or_conversation_is_skipped(self):
        d = listener_gate.Decision
        self.assertTrue(d("notification", 0.9).skip(0.8))
        self.assertTrue(d("conversation", 0.8).skip(0.8))
        self.assertFalse(d("notification", 0.79).skip(0.8))
        self.assertFalse(d("command", 0.99).skip(0.8))
        self.assertFalse(d("question", 0.99).skip(0.8))
        self.assertFalse(d(None, 0.0).skip(0.8))


class GateTests(unittest.TestCase):
    def test_the_first_model_that_answers_decides(self):
        gate = gate_with(FakeRunner({"notification": 0.95, "command": 0.05}))
        skip, decision = gate.should_skip("Your order #123 has shipped")
        self.assertTrue(skip)
        self.assertEqual((decision.intent, decision.model), ("notification", "clef-flash"))
        self.assertEqual(gate.seen, ["systemone:clef-flash"])

    def test_a_failing_model_falls_back_to_the_next(self):
        gate = gate_with(FakeRunner(error=OSError("down")), FakeRunner({"command": 0.9, "question": 0.1}))
        skip, decision = gate.should_skip("restart the media service")
        self.assertFalse(skip)
        self.assertEqual((decision.intent, decision.model), ("command", "nimble"))

    def test_no_answer_lets_the_message_through(self):
        gate = gate_with(FakeRunner(error=OSError("down")), FakeRunner())
        skip, decision = gate.should_skip("anything")
        self.assertFalse(skip)
        self.assertIsNone(decision.intent)


class FromPolicyTests(unittest.TestCase):
    def test_a_reviewed_systemone_task_gives_a_gate_with_its_fallbacks(self):
        gate = listener_gate.Gate.from_policy(0.7, _policy())
        self.assertEqual((gate.models, gate.threshold), (["clef-flash", "nimble"], 0.7))

    def test_no_gate_without_a_reviewed_systemone_task(self):
        self.assertIsNone(listener_gate.Gate.from_policy(0.8, _policy(status="unreviewed")))
        self.assertIsNone(listener_gate.Gate.from_policy(0.8, _policy(runner="chat")))
        self.assertIsNone(listener_gate.Gate.from_policy(0.8, Path("/nonexistent/policy.toml")))

    def test_build_is_off_unless_enabled(self):
        self.assertIsNone(listener_gate.build(False, 0.8))


class ProcessMessageTests(unittest.TestCase):
    def _run(self, text, gate, command="df -h"):
        cfg = ListenerConfig()
        cfg.llm.natural_language = True
        llm = MagicMock()
        llm.model = "m"
        llm.chat.return_value = json.dumps({"command": command})
        dispatcher = MagicMock()
        dispatcher.run.return_value.reply_text.return_value = "ok"
        msg = IncomingMessage(channel="signal", sender="+1", text=text)
        from unittest.mock import patch

        with patch("crew_chief.listener.reply_signal") as reply:
            sent = _process_message(msg, cfg, llm, dispatcher, None, gate)
        return sent, llm, dispatcher, reply

    def test_a_gated_message_never_reaches_the_chat_model_or_dispatcher(self):
        gate = gate_with(FakeRunner({"notification": 0.97, "command": 0.03}))
        sent, llm, dispatcher, reply = self._run("Your statement is ready", gate)
        self.assertFalse(sent)
        llm.chat.assert_not_called()
        dispatcher.run.assert_not_called()
        reply.assert_not_called()

    def test_a_command_message_continues_through_the_normal_flow(self):
        gate = gate_with(FakeRunner({"command": 0.9, "question": 0.1}))
        sent, llm, dispatcher, _ = self._run("how full is the disk", gate)
        self.assertTrue(sent)
        dispatcher.run.assert_called_once_with("df -h")

    def test_an_unsure_gate_does_not_drop_the_message(self):
        gate = gate_with(FakeRunner({"notification": 0.55, "command": 0.45}))
        sent, _, dispatcher, _ = self._run("disk check", gate)
        self.assertTrue(sent)
        dispatcher.run.assert_called_once()

    def test_direct_commands_bypass_the_gate(self):
        gate = gate_with()  # any use of the gate would pop an empty queue
        sent, _, dispatcher, _ = self._run("!df -h", gate)
        self.assertTrue(sent)
        self.assertEqual(gate.seen, [])
        dispatcher.run.assert_called_once()

    def test_without_a_gate_nothing_changes(self):
        sent, _, dispatcher, _ = self._run("disk check", None)
        self.assertTrue(sent)
        dispatcher.run.assert_called_once()


class ConfigTests(unittest.TestCase):
    def _load(self, body):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "listener.toml"
        path.write_text(body, encoding="utf-8")
        return load(path)

    def test_the_gate_is_off_by_default(self):
        cfg = self._load("[llm]\nmodel = 'x'\n")
        self.assertFalse(cfg.llm.decision_gate)
        self.assertEqual(cfg.llm.decision_gate_threshold, 0.8)

    def test_it_can_be_enabled_with_a_threshold(self):
        cfg = self._load("[llm]\ndecision_gate = true\ndecision_gate_threshold = 0.9\n")
        self.assertTrue(cfg.llm.decision_gate)
        self.assertEqual(cfg.llm.decision_gate_threshold, 0.9)

    def test_a_threshold_outside_zero_to_one_is_rejected(self):
        for bad in ("0", "1.5", "-0.2"):
            with self.assertRaises(ConfigError):
                self._load(f"[llm]\ndecision_gate_threshold = {bad}\n")


if __name__ == "__main__":
    unittest.main()
