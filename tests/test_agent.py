"""Tests for crew_chief.agent — all offline, provider mocked."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from crew_chief.agent import Agent
from crew_chief.providers.base import ChatResult, ToolUse
from crew_chief.tools import Tool


# ---------------------------------------------------------------------------
# Minimal stub tool
# ---------------------------------------------------------------------------


class EchoTool(Tool):
    name = "echo"
    description = "Returns its input."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, arguments):
        return arguments.get("text", "")


# ---------------------------------------------------------------------------
# Helper to build a mock provider
# ---------------------------------------------------------------------------


def _make_provider(*responses: ChatResult) -> MagicMock:
    """Return a mock provider whose chat() returns *responses* in sequence."""
    provider = MagicMock()
    provider.chat.side_effect = list(responses)
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentRunNoTools(unittest.TestCase):
    def test_returns_content_directly(self):
        result = ChatResult(content="42", stop_reason="end_turn")
        provider = _make_provider(result)
        agent = Agent(provider=provider)
        output = agent.run("What is 6*7?")
        self.assertEqual(output, "42")
        provider.chat.assert_called_once()

    def test_passes_system_prompt(self):
        result = ChatResult(content="done")
        provider = _make_provider(result)
        agent = Agent(provider=provider, system_prompt="Be concise.")
        agent.run("hi")
        _, kwargs = provider.chat.call_args
        self.assertEqual(kwargs.get("system"), "Be concise.")

    def test_uses_default_system_prompt_when_empty(self):
        result = ChatResult(content="ok")
        provider = _make_provider(result)
        agent = Agent(provider=provider, system_prompt="")
        agent.run("hi")
        _, kwargs = provider.chat.call_args
        self.assertIn("automation", kwargs.get("system", "").lower())


class TestAgentRunWithTools(unittest.TestCase):
    def test_single_tool_call_then_done(self):
        tool_use = ToolUse(id="t1", name="echo", arguments={"text": "hello"})
        responses = [
            ChatResult(content="", tool_uses=[tool_use], stop_reason="tool_use"),
            ChatResult(content="The echo said: hello", stop_reason="end_turn"),
        ]
        provider = _make_provider(*responses)
        tool = EchoTool()
        agent = Agent(provider=provider, tools=[tool])

        output = agent.run("Echo hello")
        self.assertEqual(output, "The echo said: hello")
        self.assertEqual(provider.chat.call_count, 2)

    def test_tool_result_appended_to_messages(self):
        """Verify tool results are included in the second call's messages."""
        tool_use = ToolUse(id="t1", name="echo", arguments={"text": "ping"})
        responses = [
            ChatResult(content="", tool_uses=[tool_use], stop_reason="tool_use"),
            ChatResult(content="done"),
        ]
        provider = _make_provider(*responses)
        agent = Agent(provider=provider, tools=[EchoTool()])
        agent.run("test")

        # Second call should have messages including the tool_result turn
        second_call_messages = provider.chat.call_args_list[1][0][0]
        roles = [m["role"] for m in second_call_messages]
        self.assertIn("tool_result", roles)
        # The tool_result entry should contain the echo output
        tr = next(m for m in second_call_messages if m["role"] == "tool_result")
        self.assertEqual(tr["results"][0]["content"], "ping")

    def test_unknown_tool_returns_error_string(self):
        tool_use = ToolUse(id="t1", name="nonexistent", arguments={})
        responses = [
            ChatResult(content="", tool_uses=[tool_use], stop_reason="tool_use"),
            ChatResult(content="ok"),
        ]
        provider = _make_provider(*responses)
        agent = Agent(provider=provider, tools=[])
        agent.run("test")

        second_call_messages = provider.chat.call_args_list[1][0][0]
        tr = next(m for m in second_call_messages if m["role"] == "tool_result")
        self.assertIn("Unknown tool", tr["results"][0]["content"])

    def test_tool_exception_does_not_crash_agent(self):
        class BrokenTool(Tool):
            name = "broken"
            description = "Always raises."
            parameters = {"type": "object", "properties": {}}

            def execute(self, arguments):
                raise ValueError("boom")

        tool_use = ToolUse(id="t1", name="broken", arguments={})
        responses = [
            ChatResult(content="", tool_uses=[tool_use], stop_reason="tool_use"),
            ChatResult(content="handled"),
        ]
        provider = _make_provider(*responses)
        agent = Agent(provider=provider, tools=[BrokenTool()])
        output = agent.run("trigger error")
        self.assertEqual(output, "handled")

    def test_multi_tool_calls_in_one_turn(self):
        tu1 = ToolUse(id="a", name="echo", arguments={"text": "one"})
        tu2 = ToolUse(id="b", name="echo", arguments={"text": "two"})
        responses = [
            ChatResult(content="", tool_uses=[tu1, tu2], stop_reason="tool_use"),
            ChatResult(content="done"),
        ]
        provider = _make_provider(*responses)
        agent = Agent(provider=provider, tools=[EchoTool()])
        agent.run("multi")

        second_messages = provider.chat.call_args_list[1][0][0]
        tr = next(m for m in second_messages if m["role"] == "tool_result")
        self.assertEqual(len(tr["results"]), 2)
        self.assertEqual(tr["results"][0]["content"], "one")
        self.assertEqual(tr["results"][1]["content"], "two")


class TestAgentMaxIterations(unittest.TestCase):
    def test_stops_at_max_iterations(self):
        tool_use = ToolUse(id="t1", name="echo", arguments={"text": "loop"})
        # Always returns tool_use — should never finish naturally
        provider = MagicMock()
        provider.chat.return_value = ChatResult(
            content="partial", tool_uses=[tool_use], stop_reason="tool_use"
        )
        agent = Agent(provider=provider, tools=[EchoTool()], max_iterations=3)
        output = agent.run("infinite loop")
        self.assertEqual(output, "partial")
        self.assertEqual(provider.chat.call_count, 3)

    def test_tool_params_not_sent_when_no_tools(self):
        provider = _make_provider(ChatResult(content="ok"))
        agent = Agent(provider=provider, tools=[])
        agent.run("hi")
        _, kwargs = provider.chat.call_args
        self.assertIsNone(kwargs.get("tools"))


if __name__ == "__main__":
    unittest.main()
