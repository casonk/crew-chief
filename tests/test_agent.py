"""Tests for crew_chief.agent — all offline, provider mocked."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from crew_chief.agent import Agent, AgentCascade, LowConfidenceError
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


class ShellStubTool(Tool):
    name = "shell"
    description = "Pretends to run a shell command."
    parameters = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }

    def execute(self, arguments):
        return f"ran: {arguments.get('command', '')}"


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
        agent.run("Summarize this.")
        _, kwargs = provider.chat.call_args
        self.assertEqual(kwargs.get("system"), "Be concise.")

    def test_uses_default_system_prompt_when_empty(self):
        result = ChatResult(content="ok")
        provider = _make_provider(result)
        agent = Agent(provider=provider, system_prompt="")
        agent.run("Summarize this.")
        _, kwargs = provider.chat.call_args
        self.assertIn("automation", kwargs.get("system", "").lower())

    def test_simple_greeting_returns_direct_response_without_provider_call(self):
        provider = _make_provider(ChatResult(content="should not be used"))
        agent = Agent(provider=provider)

        output = agent.run("Hello!")

        self.assertIn("Hello! I'm Crew Chief", output)
        self.assertIn("disk space", output)
        self.assertIn("uptime", output)
        self.assertNotIn("type a number", output.lower())
        provider.chat.assert_not_called()

    def test_common_greeting_variants_return_direct_response_without_provider_call(self):
        for prompt in ("Hello there!", "Good morning."):
            with self.subTest(prompt=prompt):
                provider = _make_provider(ChatResult(content="should not be used"))
                agent = Agent(provider=provider)

                output = agent.run(prompt)

                self.assertIn("Hello! I'm Crew Chief", output)
                provider.chat.assert_not_called()

    def test_conversational_pseudo_tool_call_retries_to_plain_text(self):
        provider = _make_provider(
            ChatResult(content='{"name": "greeting", "parameters": {"message": "Hello! I"}}'),
            ChatResult(content="Hello! I'm Crew Chief."),
        )
        agent = Agent(provider=provider, tools=[EchoTool()])
        output = agent.run("Hello! I")

        self.assertEqual(output, "Hello! I'm Crew Chief.")
        self.assertEqual(provider.chat.call_count, 2)
        second_call_messages = provider.chat.call_args_list[1][0][0]
        self.assertEqual(second_call_messages[-1]["role"], "user")
        self.assertIn("plain-text tool/function-call JSON", second_call_messages[-1]["content"])

    def test_answer_containing_json_example_is_not_treated_as_tool_call(self):
        content = 'Use this JSON example:\n{"name": "shell", "parameters": {"command": "uptime"}}'
        provider = _make_provider(ChatResult(content=content))
        agent = Agent(provider=provider, tools=[ShellStubTool()])

        output = agent.run("Show me the JSON shape for a shell request.")

        self.assertEqual(output, content)
        provider.chat.assert_called_once()

    def test_raw_json_tool_example_requested_by_user_is_returned_verbatim(self):
        content = '{"name": "shell", "parameters": {"command": "uptime"}}'
        provider = _make_provider(ChatResult(content=content))
        agent = Agent(provider=provider, tools=[ShellStubTool()])

        output = agent.run("Give me a JSON example of a shell command request.")

        self.assertEqual(output, content)
        provider.chat.assert_called_once()

    def test_meta_preface_plus_trailing_pseudo_tool_json_retries_to_plain_text(self):
        provider = _make_provider(
            ChatResult(
                content=(
                    "Since there's no explicit request for code change or modification, "
                    "I will respond with a simple query to ensure clarity.\n\n"
                    '{"name": "execute", "parameters": {"command": "How can I assist you today?"}}'
                )
            ),
            ChatResult(content="How can I assist you today?"),
        )
        agent = Agent(provider=provider, tools=[EchoTool()])

        output = agent.run("Review this assistant output.")

        self.assertEqual(output, "How can I assist you today?")
        self.assertEqual(provider.chat.call_count, 2)

    def test_conversational_pseudo_tool_call_uses_fallback_after_retry(self):
        provider = _make_provider(
            ChatResult(content='{"name": "greeting", "parameters": {"message": "Hello! I"}}'),
            ChatResult(content='{"name": "greeting", "parameters": {"message": "Hello again"}}'),
        )
        agent = Agent(provider=provider, tools=[EchoTool()])
        output = agent.run("Hello! I")

        self.assertIn("Crew Chief", output)
        self.assertEqual(provider.chat.call_count, 2)

    def test_greeting_prefixed_live_request_does_not_fall_back_to_greeting(self):
        provider = _make_provider(
            ChatResult(content='{"name": "shell", "parameters": {"command": "uptime"}}'),
            ChatResult(content='{"name": "shell", "parameters": {"command": "uptime"}}'),
        )
        agent = Agent(provider=provider, tools=[ShellStubTool()])

        output = agent.run("Hi, what's the uptime?")

        self.assertEqual(
            output,
            "I couldn't verify the current system state because no command was executed. Please ask again or send the exact command you want run.",
        )
        self.assertEqual(provider.chat.call_count, 2)


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
        agent.run("Need a status summary.")
        _, kwargs = provider.chat.call_args
        self.assertIsNone(kwargs.get("tools"))


class TestConfidenceCheck(unittest.TestCase):
    """Agent raises LowConfidenceError when self-assessment is below threshold."""

    def _agent_with_responses(self, main_response: ChatResult, confidence_json: str) -> Agent:
        """Return an agent whose provider returns main_response then a confidence score."""
        provider = MagicMock()
        confidence_result = ChatResult(content=confidence_json)
        provider.chat.side_effect = [main_response, confidence_result]
        return Agent(provider=provider, confidence_threshold=0.7)

    def test_high_confidence_returns_content(self):
        agent = self._agent_with_responses(
            ChatResult(content="disk is 80% full"),
            '{"confidence": 0.9}',
        )
        output = agent.run("how full is the disk?")
        self.assertEqual(output, "disk is 80% full")

    def test_low_confidence_raises_error(self):
        agent = self._agent_with_responses(
            ChatResult(content="I would check the disk space"),
            '{"confidence": 0.4}',
        )
        with self.assertRaises(LowConfidenceError) as ctx:
            agent.run("check disk space")
        self.assertAlmostEqual(ctx.exception.confidence, 0.4)
        self.assertEqual(ctx.exception.content, "I would check the disk space")

    def test_confidence_check_parse_failure_assumes_confident(self):
        """Unparseable confidence reply should not escalate (assume 1.0)."""
        provider = MagicMock()
        provider.chat.side_effect = [
            ChatResult(content="some response"),
            ChatResult(content="not json at all"),
        ]
        agent = Agent(provider=provider, confidence_threshold=0.7)
        output = agent.run("Need a status summary.")
        self.assertEqual(output, "some response")

    def test_confidence_check_exception_assumes_confident(self):
        """If the confidence call raises, do not escalate."""
        provider = MagicMock()
        provider.chat.side_effect = [
            ChatResult(content="response"),
            RuntimeError("network down"),
        ]
        agent = Agent(provider=provider, confidence_threshold=0.7)
        output = agent.run("Need a status summary.")
        self.assertEqual(output, "response")

    def test_zero_threshold_skips_check(self):
        """confidence_threshold=0.0 should make no extra chat() call."""
        provider = _make_provider(ChatResult(content="ok"))
        agent = Agent(provider=provider, confidence_threshold=0.0)
        agent.run("Need a status summary.")
        self.assertEqual(provider.chat.call_count, 1)


class TestAgentCascade(unittest.TestCase):
    """AgentCascade escalates on LowConfidenceError and returns first confident result."""

    def _agent(self, response: str, confidence: float, threshold: float = 0.7) -> Agent:
        """Return an agent that replies with *response* and self-rates *confidence*."""
        provider = MagicMock()
        provider.chat.side_effect = [
            ChatResult(content=response),
            ChatResult(content=f'{{"confidence": {confidence}}}'),
        ]
        return Agent(provider=provider, confidence_threshold=threshold)

    def _failing_agent(self, error: Exception) -> Agent:
        """Return an agent whose provider raises on every call."""
        provider = MagicMock()
        provider.chat.side_effect = error
        return Agent(provider=provider, confidence_threshold=0.7)

    def test_first_agent_confident_no_escalation(self):
        a1 = self._agent("great answer", confidence=0.9)
        a2 = self._agent("fallback answer", confidence=0.95)
        cascade = AgentCascade([a1, a2])
        result = cascade.run("question")
        self.assertEqual(result, "great answer")
        # a2 should never be called
        a2.provider.chat.assert_not_called()

    def test_escalates_on_low_confidence(self):
        a1 = self._agent("vague answer", confidence=0.3)
        a2 = self._agent("precise answer", confidence=0.9)
        cascade = AgentCascade([a1, a2])
        result = cascade.run("question")
        self.assertEqual(result, "precise answer")

    def test_escalates_on_provider_failure(self):
        a1 = self._failing_agent(RuntimeError("ollama down"))
        a2 = self._agent("fallback works", confidence=0.9)
        cascade = AgentCascade([a1, a2])
        result = cascade.run("question")
        self.assertEqual(result, "fallback works")

    def test_all_low_confidence_returns_last_content(self):
        a1 = self._agent("low1", confidence=0.2)
        a2 = self._agent("low2", confidence=0.3)
        cascade = AgentCascade([a1, a2])
        result = cascade.run("question")
        self.assertEqual(result, "low2")

    def test_empty_cascade_raises(self):
        with self.assertRaises(ValueError):
            AgentCascade([])


if __name__ == "__main__":
    unittest.main()
