"""Ollama provider's network edges, and the file tools' error messages and factory.

Nothing here opens a socket: ``urlopen`` is replaced where the provider imports it.
What is pinned is how a failure is classified (a service that is not running is
*unavailable*, so a fallback chain moves on quietly; anything else is raised), and that
a tool reports a problem to the model as text instead of raising inside the agent loop.
"""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from crew_chief import tools
from crew_chief.providers.base import ProviderUnavailableError
from crew_chief.providers.ollama import OllamaProvider, _parse_chat_response

URLOPEN = "crew_chief.providers.ollama.urllib.request.urlopen"


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def body(payload) -> Response:
    return Response(json.dumps(payload).encode())


class ParseChatResponse(unittest.TestCase):
    def test_tool_call_arguments_may_arrive_as_a_json_string(self):
        result = _parse_chat_response(
            {"message": {"tool_calls": [{"function": {"name": "t", "arguments": '{"a": 1}'}}]}}
        )
        self.assertEqual(result.tool_uses[0].arguments, {"a": 1})
        self.assertEqual(result.stop_reason, "tool_use")

    def test_arguments_that_are_not_an_object_become_empty(self):
        for arguments in ("not json", '["a"]', 5, None):
            with self.subTest(arguments=arguments):
                result = _parse_chat_response(
                    {
                        "message": {
                            "tool_calls": [{"function": {"name": "t", "arguments": arguments}}]
                        }
                    }
                )
                self.assertEqual(result.tool_uses[0].arguments, {})

    def test_a_missing_message_is_an_empty_end_of_turn(self):
        result = _parse_chat_response({})
        self.assertEqual(
            (result.content, result.tool_uses, result.stop_reason), ("", [], "end_turn")
        )


class OllamaNetwork(unittest.TestCase):
    def test_health_is_true_only_for_a_200_and_false_for_any_failure(self):
        ok = Response(b"")
        with mock.patch(URLOPEN, return_value=ok):
            self.assertTrue(OllamaProvider(base_url="http://h:1/").health())
        bad = Response(b"")
        bad.status = 503
        with mock.patch(URLOPEN, return_value=bad):
            self.assertFalse(OllamaProvider().health())
        for error in (urllib.error.URLError("down"), TimeoutError(), OSError()):
            with self.subTest(error=type(error).__name__), mock.patch(URLOPEN, side_effect=error):
                self.assertFalse(OllamaProvider().health())

    def test_the_health_check_asks_the_root_with_a_short_timeout(self):
        with mock.patch(URLOPEN, return_value=Response(b"")) as urlopen:
            OllamaProvider(base_url="http://h:1/", timeout=99).health()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://h:1/")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)

    def test_list_models_returns_names_and_tolerates_none(self):
        with mock.patch(
            URLOPEN, return_value=body({"models": [{"name": "a:1"}, {"name": "b"}]})
        ) as urlopen:
            self.assertEqual(OllamaProvider(timeout=7).list_models(), ["a:1", "b"])
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith("/api/tags"))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 7)
        with mock.patch(URLOPEN, return_value=body({})):
            self.assertEqual(OllamaProvider().list_models(), [])

    def test_a_service_that_is_not_running_is_unavailable_so_a_chain_moves_on(self):
        for reason in (
            "[Errno 111] Connection refused",
            "No route to host",
            "Name or service not known",
        ):
            error = urllib.error.URLError(reason)
            with self.subTest(reason=reason), mock.patch(URLOPEN, side_effect=error):
                with self.assertRaises(ProviderUnavailableError) as raised:
                    OllamaProvider(base_url="http://h:1").generate("hi")
            self.assertIn("http://h:1", str(raised.exception))

    def test_any_other_network_error_is_raised_as_it_is(self):
        error = urllib.error.URLError("certificate verify failed")
        with (
            mock.patch(URLOPEN, side_effect=error),
            self.assertRaises(urllib.error.URLError) as raised,
        ):
            OllamaProvider().generate("hi")
        self.assertNotIsInstance(raised.exception, ProviderUnavailableError)

    def test_a_http_error_status_is_raised_not_hidden(self):
        error = urllib.error.HTTPError("http://h", 500, "boom", {}, None)  # type: ignore[arg-type]
        with mock.patch(URLOPEN, side_effect=error), self.assertRaises(urllib.error.HTTPError):
            OllamaProvider().chat([{"role": "user", "content": "hi"}])

    def test_the_request_is_a_json_post_to_the_endpoint(self):
        with mock.patch(URLOPEN, return_value=body({"response": "x"})) as urlopen:
            OllamaProvider(base_url="http://h:1/", model="m").generate("hi")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            (request.get_method(), request.full_url), ("POST", "http://h:1/api/generate")
        )
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"model": "m", "prompt": "hi", "stream": False})

    def test_a_reply_with_no_response_field_is_an_empty_string(self):
        with mock.patch(URLOPEN, return_value=body({})):
            self.assertEqual(OllamaProvider().generate("hi"), "")


class FileToolMessages(unittest.TestCase):
    def test_read_reports_each_failure_as_text(self):
        tool = tools.ReadFileTool()
        with TemporaryDirectory() as directory:
            target = str(Path(directory) / "f.txt")
            for error, expected in (
                (FileNotFoundError(), "File not found"),
                (PermissionError(), "Permission denied"),
                (OSError("disk error"), "Error reading"),
            ):
                with (
                    self.subTest(error=type(error).__name__),
                    mock.patch.object(Path, "read_text", side_effect=error),
                ):
                    self.assertIn(expected, tool.execute({"path": target}))

    def test_write_reports_each_failure_as_text(self):
        tool = tools.WriteFileTool()
        with TemporaryDirectory() as directory:
            target = str(Path(directory) / "f.txt")
            for error, expected in (
                (PermissionError(), "Permission denied"),
                (OSError("disk full"), "Error writing"),
            ):
                with (
                    self.subTest(error=type(error).__name__),
                    mock.patch.object(Path, "write_text", side_effect=error),
                ):
                    self.assertIn(expected, tool.execute({"path": target, "content": "x"}))

    def test_a_missing_path_is_reported_before_anything_is_touched(self):
        self.assertEqual(tools.ReadFileTool().execute({}), "Error: no path provided.")
        self.assertEqual(
            tools.WriteFileTool().execute({"content": "x"}), "Error: no path provided."
        )
        self.assertEqual(tools.ReadFileTool().execute({"path": "   "}), "Error: no path provided.")


class BuildTools(unittest.TestCase):
    def cfg(self, names, paths=()):
        return SimpleNamespace(
            agent=SimpleNamespace(tools=list(names), allowed_paths=list(paths)),
            dispatch=SimpleNamespace(
                allowed_commands=["uptime"], timeout_seconds=9, output_max_bytes=123
            ),
        )

    def test_each_configured_name_builds_its_tool_in_order(self):
        built = tools.build_tools(self.cfg(["write_file", "shell", "read_file"]))
        self.assertEqual([t.name for t in built], ["write_file", "shell", "read_file"])

    def test_the_shell_tool_gets_the_dispatch_settings(self):
        with mock.patch("crew_chief.dispatcher.Dispatcher") as dispatcher:
            tools.build_tools(self.cfg(["shell"]))
        dispatcher.assert_called_once_with(
            allowed_commands=["uptime"], timeout_seconds=9, max_output_bytes=123
        )

    def test_file_tools_are_confined_to_the_configured_directories(self):
        built = tools.build_tools(self.cfg(["read_file", "write_file"], ["/srv/data"]))
        self.assertTrue(all(t.allowed_paths == ["/srv/data"] for t in built))
        unrestricted = tools.build_tools(self.cfg(["read_file"]))
        self.assertEqual(unrestricted[0].allowed_paths, [])

    def test_an_unknown_name_is_skipped_with_a_warning_not_an_error(self):
        with self.assertLogs("crew_chief.tools", level="WARNING") as logs:
            built = tools.build_tools(self.cfg(["teleport", "read_file"]))
        self.assertEqual([t.name for t in built], ["read_file"])
        self.assertIn("teleport", logs.output[0])

    def test_no_names_means_no_tools(self):
        self.assertEqual(tools.build_tools(self.cfg([])), [])


if __name__ == "__main__":
    unittest.main()
