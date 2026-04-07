"""Tests for crew_chief.tools — mostly offline; ShellTool uses real subprocess for echo."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from crew_chief.dispatcher import Dispatcher
from crew_chief.tools import ReadFileTool, ShellTool, Tool, WriteFileTool


# ---------------------------------------------------------------------------
# Tool base
# ---------------------------------------------------------------------------


class TestToolBase(unittest.TestCase):
    def test_to_param_fields(self):
        class MyTool(Tool):
            name = "my_tool"
            description = "Does something."
            parameters = {"type": "object", "properties": {}}

            def execute(self, arguments):
                return "ok"

        param = MyTool().to_param()
        self.assertEqual(param.name, "my_tool")
        self.assertEqual(param.description, "Does something.")
        self.assertEqual(param.parameters, {"type": "object", "properties": {}})

    def test_execute_raises_not_implemented(self):
        t = Tool()
        with self.assertRaises(NotImplementedError):
            t.execute({})


# ---------------------------------------------------------------------------
# ShellTool
# ---------------------------------------------------------------------------


class TestShellTool(unittest.TestCase):
    def setUp(self):
        self.dispatcher = Dispatcher(
            allowed_commands=["echo *", "true", "false"],
            timeout_seconds=5,
            max_output_bytes=1000,
        )
        self.tool = ShellTool(self.dispatcher)

    def test_allowed_command_runs(self):
        output = self.tool.execute({"command": "echo hello"})
        self.assertIn("hello", output)

    def test_denied_command_returns_not_permitted(self):
        output = self.tool.execute({"command": "rm -rf /"})
        self.assertIn("not permitted", output)

    def test_empty_command_returns_error(self):
        output = self.tool.execute({"command": ""})
        self.assertIn("Error", output)

    def test_missing_command_key(self):
        output = self.tool.execute({})
        self.assertIn("Error", output)

    def test_name_and_description(self):
        self.assertEqual(self.tool.name, "shell")
        self.assertIn("shell", self.tool.description.lower())


# ---------------------------------------------------------------------------
# ReadFileTool
# ---------------------------------------------------------------------------


class TestReadFileTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        self.tmp.write("hello world\n")
        self.tmp.close()
        self.path = self.tmp.name

    def tearDown(self):
        Path(self.path).unlink(missing_ok=True)

    def test_reads_existing_file(self):
        tool = ReadFileTool()
        output = tool.execute({"path": self.path})
        self.assertIn("hello world", output)

    def test_missing_file_returns_error(self):
        tool = ReadFileTool()
        output = tool.execute({"path": "/nonexistent/path/xyz.txt"})
        self.assertIn("not found", output.lower())

    def test_path_restriction_denied(self):
        tool = ReadFileTool(allowed_paths=["/allowed/"])
        output = tool.execute({"path": self.path})
        self.assertIn("Access denied", output)

    def test_path_restriction_allowed(self):
        tool = ReadFileTool(allowed_paths=[str(Path(self.path).parent) + "/"])
        output = tool.execute({"path": self.path})
        self.assertIn("hello world", output)

    def test_no_path_returns_error(self):
        tool = ReadFileTool()
        output = tool.execute({})
        self.assertIn("Error", output)


# ---------------------------------------------------------------------------
# WriteFileTool
# ---------------------------------------------------------------------------


class TestWriteFileTool(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_writes_new_file(self):
        tool = WriteFileTool()
        path = str(Path(self.tmpdir) / "out.txt")
        output = tool.execute({"path": path, "content": "test content"})
        self.assertIn("Wrote", output)
        self.assertEqual(Path(path).read_text(), "test content")

    def test_overwrites_existing_file(self):
        path = str(Path(self.tmpdir) / "existing.txt")
        Path(path).write_text("old content")
        tool = WriteFileTool()
        tool.execute({"path": path, "content": "new content"})
        self.assertEqual(Path(path).read_text(), "new content")

    def test_creates_parent_directories(self):
        tool = WriteFileTool()
        path = str(Path(self.tmpdir) / "a" / "b" / "file.txt")
        tool.execute({"path": path, "content": "deep"})
        self.assertEqual(Path(path).read_text(), "deep")

    def test_path_restriction_denied(self):
        tool = WriteFileTool(allowed_paths=["/safe/"])
        output = tool.execute({"path": str(Path(self.tmpdir) / "x.txt"), "content": "x"})
        self.assertIn("Access denied", output)

    def test_no_path_returns_error(self):
        tool = WriteFileTool()
        output = tool.execute({"content": "oops"})
        self.assertIn("Error", output)

    def test_character_count_in_reply(self):
        tool = WriteFileTool()
        path = str(Path(self.tmpdir) / "cnt.txt")
        output = tool.execute({"path": path, "content": "abc"})
        self.assertIn("3", output)


if __name__ == "__main__":
    unittest.main()
