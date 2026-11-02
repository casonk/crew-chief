"""When the agent turns a model's malformed output into a shell command.

A model that echoes the tool schema, or writes a tool call as JSON text, would otherwise
get no result. The agent repairs the narrow, recognisable shapes into a real ``shell``
call, and that call is executed. So the guards matter more than the repair: only a
configured ``shell`` tool is ever targeted, only the exact schema-echo shape is accepted,
and a prompt that is asking for an *example* of a tool call never causes one to run.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from crew_chief import agent as agent_module
from crew_chief.agent import Agent, AgentCascade, LowConfidenceError
from crew_chief.providers.base import ChatResult, ToolUse
from crew_chief.tools import Tool

STUB = {"command": {"type": "string", "description": "the command to run"}}


class RecordingShell(Tool):
    name = "shell"
    description = "records commands"
    parameters = {"type": "object", "properties": {"command": {"type": "string"}}}

    def __init__(self):
        self.commands: list[str] = []

    def execute(self, arguments):
        self.commands.append(arguments.get("command", ""))
        return f"ran: {arguments.get('command', '')}"


def provider(*results: ChatResult) -> MagicMock:
    mock = MagicMock()
    mock.chat.side_effect = list(results)
    return mock


def text(content: str) -> ChatResult:
    return ChatResult(content=content, stop_reason="end_turn", model="m")


class RepairPseudoToolCall(unittest.TestCase):
    def test_only_a_configured_shell_tool_can_be_the_target(self):
        pseudo = {"name": "df -h", "arguments": STUB}
        self.assertIsNone(agent_module._repair_pseudo_tool_call(pseudo, {"echo": object()}, "r"))
        self.assertIsNone(agent_module._repair_pseudo_tool_call(None, {"shell": object()}, "r"))

    def test_a_schema_echo_becomes_a_shell_call_with_the_given_id(self):
        repaired = agent_module._repair_pseudo_tool_call(
            {"name": "df -h", "arguments": STUB}, {"shell": object()}, "repair-7"
        )
        self.assertEqual(
            (repaired.id, repaired.name, repaired.arguments),
            ("repair-7", "shell", {"command": "df -h"}),
        )

    def test_anything_else_is_not_repaired(self):
        for pseudo in (
            {"name": "df -h", "arguments": {"command": "rm -rf /"}},
            {"name": "df -h", "arguments": {}},
            {"name": "df -h", "arguments": {**STUB, "extra": 1}},
        ):
            with self.subTest(pseudo=pseudo):
                self.assertIsNone(
                    agent_module._repair_pseudo_tool_call(pseudo, {"shell": object()}, "r")
                )


class RepairToolUses(unittest.TestCase):
    def test_a_known_tool_is_left_alone(self):
        use = ToolUse(id="1", name="echo", arguments={"text": "x"})
        self.assertEqual(agent_module._repair_tool_uses([use], {"echo": 1, "shell": 1}), [use])

    def test_without_a_shell_tool_nothing_is_rewritten(self):
        use = ToolUse(id="1", name="df -h", arguments=STUB)
        self.assertEqual(agent_module._repair_tool_uses([use], {"echo": 1}), [use])

    def test_a_schema_echo_under_an_unknown_name_becomes_a_shell_call_keeping_its_id(self):
        use = ToolUse(id="call-3", name="uptime", arguments=STUB)
        [fixed] = agent_module._repair_tool_uses([use], {"shell": 1})
        self.assertEqual(
            (fixed.id, fixed.name, fixed.arguments), ("call-3", "shell", {"command": "uptime"})
        )

    def test_an_unknown_tool_with_real_arguments_is_not_turned_into_a_command(self):
        use = ToolUse(id="1", name="rm -rf /", arguments={"command": "anything"})
        self.assertEqual(agent_module._repair_tool_uses([use], {"shell": 1}), [use])


class ParsePseudoToolCall(unittest.TestCase):
    def test_a_bare_or_fenced_json_object_is_parsed(self):
        for content in (
            '{"name": "t", "parameters": {"a": 1}}',
            '```json\n{"name": "t", "arguments": {"a": 1}}\n```',
            '```\n{"name": "t", "parameters": {"a": 1}}\n```',
        ):
            with self.subTest(content=content):
                self.assertEqual(
                    agent_module._parse_pseudo_tool_call(content),
                    {"name": "t", "arguments": {"a": 1}},
                )

    def test_text_that_is_not_such_an_object_is_not(self):
        for content in (
            "",
            "  ",
            "plain text",
            "{broken",
            '["a"]',
            '{"name": 5, "parameters": {}}',
            '{"name": "t", "parameters": []}',
            '{"name": "t"}',
        ):
            with self.subTest(content=content):
                self.assertIsNone(agent_module._parse_pseudo_tool_call(content))

    def test_payload_shape(self):
        self.assertIsNone(agent_module._parse_pseudo_tool_payload("x"))
        self.assertEqual(
            agent_module._parse_pseudo_tool_payload(
                {"name": "t", "parameters": {}, "arguments": {"a": 1}}
            ),
            {"name": "t", "arguments": {}},
        )


class SplitTrailingJson(unittest.TestCase):
    def test_empty_and_json_free_text_have_no_tail(self):
        self.assertEqual(agent_module._split_trailing_json_object(""), ("", None))
        self.assertEqual(agent_module._split_trailing_json_object("no braces"), ("", None))

    def test_a_fenced_tail_keeps_its_prefix(self):
        self.assertEqual(
            agent_module._split_trailing_json_object('I will run it:\n```json\n{"a": 1}\n```'),
            ("I will run it:", {"a": 1}),
        )

    def test_a_fenced_tail_that_is_not_json_is_none(self):
        self.assertEqual(
            agent_module._split_trailing_json_object("x\n```json\n{not json}\n```"), ("", None)
        )

    def test_an_unfenced_object_must_end_the_text(self):
        self.assertEqual(
            agent_module._split_trailing_json_object('Run: {"a": 1}'), ("Run:", {"a": 1})
        )
        self.assertEqual(
            agent_module._split_trailing_json_object('{"a": 1} and then more'), ("", None)
        )

    def test_the_outermost_trailing_object_wins(self):
        prefix, parsed = agent_module._split_trailing_json_object('before {"a": {"b": 1}}')
        self.assertEqual((prefix, parsed), ("before", {"a": {"b": 1}}))


class FindPseudoToolCall(unittest.TestCase):
    CALL = '{"name": "uptime", "parameters": {"command": {"type": "string", "description": "d"}}}'

    def test_a_call_with_no_explanation_is_found(self):
        self.assertEqual(
            agent_module._find_pseudo_tool_call("how long up", self.CALL)["name"], "uptime"
        )

    def test_a_prompt_asking_for_an_example_never_produces_a_call(self):
        for prompt in (
            "show me an example JSON for a shell tool call",
            "what does the function call payload look like",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(agent_module._find_pseudo_tool_call(prompt, self.CALL))

    def test_a_reply_that_introduces_the_json_as_an_example_is_not_a_call(self):
        reply = "Here is an example of the format:\n" + self.CALL
        self.assertIsNone(agent_module._find_pseudo_tool_call("how long up", reply))

    def test_a_reply_that_just_introduces_the_call_is_found(self):
        self.assertIsNotNone(
            agent_module._find_pseudo_tool_call("how long up", "Running it now:\n" + self.CALL)
        )

    def test_text_with_no_json_is_not_a_call(self):
        self.assertIsNone(agent_module._find_pseudo_tool_call("hi", "I do not know"))


class PromptClassification(unittest.TestCase):
    def test_live_requests(self):
        for prompt in (
            "!uptime",
            "  What is the Uptime",
            "show memory",
            "Run df -h",
            "is nginx running?",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(agent_module._looks_like_live_request(prompt))
        self.assertFalse(agent_module._looks_like_live_request("tell me a story"))

    def test_conversational_prompts_exclude_live_requests(self):
        self.assertTrue(agent_module._is_conversational_prompt("hello, how are you"))
        self.assertFalse(agent_module._is_conversational_prompt("hello, show memory"))
        self.assertFalse(agent_module._is_conversational_prompt("tell me a story"))

    def test_the_fallback_matches_the_kind_of_prompt(self):
        live = agent_module._fallback_for_prompt("run uptime")
        chat = agent_module._fallback_for_prompt("hello there friend")
        other = agent_module._fallback_for_prompt("compose a poem")
        self.assertEqual(len({live, chat, other}), 3)
        self.assertEqual(chat, agent_module._DEFAULT_GREETING_RESPONSE)

    def test_simple_greetings_only(self):
        for prompt in ("hi", "Hello there!", "good morning.", "  hey  "):
            self.assertTrue(agent_module._is_simple_greeting(prompt), prompt)
        for prompt in ("hi can you check disk", "hello world program", "morning"):
            self.assertFalse(agent_module._is_simple_greeting(prompt), prompt)


class AgentLoopRepairs(unittest.TestCase):
    def test_a_schema_echo_is_executed_as_a_shell_command_and_the_answer_returned(self):
        shell = RecordingShell()
        echo = (
            '{"name": "uptime", "parameters": {"command": {"type": "string", "description": "d"}}}'
        )
        agent = Agent(provider(text(echo), text("up 3 days")), tools=[shell])
        self.assertEqual(agent.run("how long has it been up"), "up 3 days")
        self.assertEqual(shell.commands, ["uptime"])

    def test_without_a_shell_tool_the_echo_is_never_executed_and_the_model_is_retried_once(self):
        echo = (
            '{"name": "uptime", "parameters": {"command": {"type": "string", "description": "d"}}}'
        )
        retry = provider(text(echo), text(echo))
        agent = Agent(retry, tools=[])
        answer = agent.run("how long has it been up")
        self.assertEqual(retry.chat.call_count, 2)
        self.assertEqual(answer, agent_module._fallback_for_prompt("how long has it been up"))

    def test_a_pseudo_call_that_is_not_a_schema_echo_gets_one_retry_then_the_fallback(self):
        shell = RecordingShell()
        call = '{"name": "shell", "parameters": {"command": "rm -rf /"}}'
        agent = Agent(provider(text(call), text(call)), tools=[shell])
        answer = agent.run("clean up")
        self.assertEqual(shell.commands, [])
        self.assertEqual(answer, agent_module._fallback_for_prompt("clean up"))

    def test_a_retry_that_succeeds_ends_normally(self):
        agent = Agent(
            provider(text('{"name": "x", "parameters": {"a": 1}}'), text("a real answer")),
            tools=[RecordingShell()],
        )
        self.assertEqual(agent.run("clean up"), "a real answer")

    def test_a_malformed_call_under_an_unknown_name_is_repaired_in_the_tool_use_list(self):
        shell = RecordingShell()
        bad = ChatResult(
            content="", stop_reason="tool_use", model="m",
            tool_uses=[ToolUse(id="1", name="df -h", arguments=STUB)],
        )  # fmt: skip
        agent = Agent(provider(bad, text("disk is fine")), tools=[shell])
        self.assertEqual(agent.run("check the disk"), "disk is fine")
        self.assertEqual(shell.commands, ["df -h"])

    def test_an_unknown_tool_with_real_arguments_is_reported_to_the_model_not_run(self):
        shell = RecordingShell()
        unknown = ChatResult(
            content="", stop_reason="tool_use", model="m",
            tool_uses=[ToolUse(id="1", name="launch_missiles", arguments={"target": "x"})],
        )  # fmt: skip
        llm = provider(unknown, text("done"))
        Agent(llm, tools=[shell]).run("do it")
        self.assertEqual(shell.commands, [])
        self.assertIn("Unknown tool", str(llm.chat.call_args_list[1].args[0][-1]))

    def test_a_tool_that_raises_is_reported_to_the_model_as_text(self):
        class Boom(RecordingShell):
            name = "boom"

            def execute(self, arguments):
                raise RuntimeError("kaput")

        call = ChatResult(
            content="", stop_reason="tool_use", model="m", tool_uses=[ToolUse("1", "boom", {})]
        )
        llm = provider(call, text("recovered"))
        self.assertEqual(Agent(llm, tools=[Boom()]).run("go"), "recovered")
        self.assertIn("Tool execution error: kaput", str(llm.chat.call_args_list[1].args[0][-1]))

    def test_a_tool_use_stop_with_no_calls_is_never_treated_as_a_pseudo_call(self):
        shell = RecordingShell()
        echo = (
            '{"name": "uptime", "parameters": {"command": {"type": "string", "description": "d"}}}'
        )
        odd = ChatResult(content=echo, stop_reason="tool_use", model="m", tool_uses=[])
        self.assertEqual(Agent(provider(odd), tools=[shell]).run("how long up"), echo)
        self.assertEqual(shell.commands, [])

    def test_the_confidence_threshold_is_inclusive(self):
        def run(score):
            llm = provider(text("answer"), text(f'{{"confidence": {score}}}'))
            return Agent(llm, confidence_threshold=0.8).run("task")

        self.assertEqual(run(0.8), "answer")
        self.assertEqual(run(1.0), "answer")
        for score in (0.79, 0.5, 0.0):
            with self.subTest(score=score), self.assertRaises(LowConfidenceError) as raised:
                run(score)
            self.assertEqual(raised.exception.content, "answer")

    def test_hitting_the_iteration_cap_returns_the_last_content(self):
        loop = ChatResult(
            content="partial",
            stop_reason="tool_use",
            model="m",
            tool_uses=[ToolUse("1", "shell", {"command": "date"})],
        )
        shell = RecordingShell()
        agent = Agent(provider(loop, loop, loop), tools=[shell], max_iterations=3)
        self.assertEqual(agent.run("loop forever"), "partial")
        self.assertEqual(len(shell.commands), 3)


class CascadeBehaviour(unittest.TestCase):
    def agent(self, *results, threshold=0.0):
        return Agent(provider(*results), confidence_threshold=threshold)

    def test_it_needs_at_least_one_agent(self):
        with self.assertRaises(ValueError):
            AgentCascade([])

    def test_a_failing_agent_hands_over_and_the_winner_names_its_model(self):
        broken = Agent(MagicMock(chat=MagicMock(side_effect=RuntimeError("down"))))
        good = self.agent(ChatResult(content="ok", model="big", stop_reason="end_turn"))
        cascade = AgentCascade([broken, good])
        self.assertEqual(cascade.run("task"), "ok")
        self.assertEqual(cascade.last_used_model, "big")

    def test_low_confidence_escalates_and_exhaustion_returns_the_last_response(self):
        low = lambda: self.agent(  # noqa: E731
            ChatResult(content="meh", model="m1", stop_reason="end_turn"),
            ChatResult(content='{"confidence": 0.1}', model="m1", stop_reason="end_turn"),
            threshold=0.8,
        )
        cascade = AgentCascade([low(), low()])
        self.assertEqual(cascade.run("task"), "meh")
        self.assertEqual(cascade.last_used_model, "m1")

    def test_a_low_confidence_error_carries_the_content_and_score(self):
        error = LowConfidenceError("low", content="c", confidence=0.2)
        self.assertEqual((error.content, error.confidence), ("c", 0.2))


if __name__ == "__main__":
    unittest.main()
