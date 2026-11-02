"""The file tools stay inside their allowed directories, whatever path the model writes.

The path comes from a language model, so it is untrusted input: ``..`` segments,
symlinks, sibling directories that share a prefix and odd bytes must not reach outside
the configured directories, for reading or for writing.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from crew_chief.tools import ReadFileTool, WriteFileTool


class Confinement(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.allowed = self.root / "data"
        self.allowed.mkdir()
        (self.allowed / "inside.txt").write_text("INSIDE", encoding="utf-8")
        self.outside = self.root / "outside.txt"
        self.outside.write_text("OUTSIDE", encoding="utf-8")
        self.sibling = self.root / "data-other"
        self.sibling.mkdir()
        (self.sibling / "secret.txt").write_text("SECRET", encoding="utf-8")
        self.reader = ReadFileTool(allowed_paths=[str(self.allowed)])
        self.writer = WriteFileTool(allowed_paths=[str(self.allowed)])

    def read(self, path) -> str:
        return self.reader.execute({"path": str(path)})

    def write(self, path, content: str = "x") -> str:
        return self.writer.execute({"path": str(path), "content": content})

    def test_a_file_inside_is_readable_and_writable(self) -> None:
        self.assertEqual(self.read(self.allowed / "inside.txt"), "INSIDE")
        self.assertIn("Wrote 1", self.write(self.allowed / "new" / "deep.txt"))
        self.assertTrue((self.allowed / "new" / "deep.txt").is_file())

    def test_the_allowed_directory_itself_is_inside(self) -> None:
        self.assertNotIn("Access denied", self.read(self.allowed))

    def test_dot_dot_cannot_climb_out_to_read(self) -> None:
        for path in (
            f"{self.allowed}/../outside.txt",
            f"{self.allowed}/sub/../../outside.txt",
            f"{self.allowed}/./../outside.txt",
        ):
            with self.subTest(path=path):
                self.assertIn("Access denied", self.read(path))

    def test_dot_dot_cannot_climb_out_to_write(self) -> None:
        planted = self.root / "planted.txt"
        out = self.write(f"{self.allowed}/../planted.txt")
        self.assertIn("Access denied", out)
        self.assertFalse(planted.exists())

    def test_a_dot_dot_that_stays_inside_is_fine(self) -> None:
        (self.allowed / "sub").mkdir()
        self.assertEqual(self.read(f"{self.allowed}/sub/../inside.txt"), "INSIDE")

    def test_a_sibling_sharing_the_prefix_is_outside(self) -> None:
        self.assertIn("Access denied", self.read(self.sibling / "secret.txt"))
        out = self.write(self.sibling / "planted.txt")
        self.assertIn("Access denied", out)
        self.assertFalse((self.sibling / "planted.txt").exists())

    def test_a_symlink_pointing_out_is_followed_and_refused(self) -> None:
        link = self.allowed / "escape"
        link.symlink_to(self.root)
        self.assertIn("Access denied", self.read(link / "outside.txt"))
        self.assertIn("Access denied", self.write(link / "planted.txt"))
        self.assertFalse((self.root / "planted.txt").exists())
        file_link = self.allowed / "peek.txt"
        file_link.symlink_to(self.outside)
        self.assertIn("Access denied", self.read(file_link))

    def test_a_symlink_that_stays_inside_is_fine(self) -> None:
        link = self.allowed / "alias.txt"
        link.symlink_to(self.allowed / "inside.txt")
        self.assertEqual(self.read(link), "INSIDE")

    def test_a_trailing_slash_on_the_configured_directory_makes_no_difference(self) -> None:
        reader = ReadFileTool(allowed_paths=[str(self.allowed) + "/"])
        self.assertEqual(reader.execute({"path": str(self.allowed / "inside.txt")}), "INSIDE")
        self.assertIn("Access denied", reader.execute({"path": str(self.outside)}))

    def test_any_of_several_directories_admits_a_path(self) -> None:
        reader = ReadFileTool(allowed_paths=[str(self.allowed), str(self.sibling)])
        self.assertEqual(reader.execute({"path": str(self.sibling / "secret.txt")}), "SECRET")
        self.assertIn("Access denied", reader.execute({"path": str(self.outside)}))

    def test_an_embedded_nul_is_refused_not_a_crash(self) -> None:
        self.assertIn("Access denied", self.read(f"{self.allowed}/inside.txt\x00../outside.txt"))
        self.assertIn("Access denied", self.write(f"{self.allowed}/a\x00b"))

    def test_without_a_restriction_paths_are_not_confined_but_bad_ones_do_not_crash(self) -> None:
        free = ReadFileTool()
        self.assertEqual(free.execute({"path": str(self.outside)}), "OUTSIDE")
        self.assertIn("Error reading", free.execute({"path": "/tmp/a\x00b"}))
        self.assertIn(
            "Error writing", WriteFileTool().execute({"path": "/tmp/a\x00b", "content": "x"})
        )

    def test_a_denied_read_or_write_says_which_path(self) -> None:
        self.assertIn(repr(str(self.outside)), self.read(self.outside))

    def test_a_relative_path_is_judged_where_it_lands(self) -> None:
        previous = Path.cwd()
        os.chdir(self.allowed)
        try:
            self.assertEqual(self.read("inside.txt"), "INSIDE")
            self.assertIn("Access denied", self.read("../outside.txt"))
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
