"""Tests for crew_chief.gguf_sources — offline, with a fake HTTP opener."""

from __future__ import annotations

import hashlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from crew_chief import gguf_sources as gs

DATA = b"GGUF" + bytes(range(256)) * 40


def _source(data: bytes = DATA, sha: str | None = None) -> gs.GgufSource:
    return gs.GgufSource(
        "m:latest",
        "org/m-GGUF",
        "m-Q4_K_M.gguf",
        sha or hashlib.sha256(data).hexdigest(),
        len(data),
    )


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, status: int):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Opener:
    """Serves DATA, honouring Range unless told not to."""

    def __init__(self, honour_range: bool = True):
        self.honour_range = honour_range
        self.ranges: list[str | None] = []

    def __call__(self, request, timeout=None):
        rng = request.get_header("Range")
        self.ranges.append(rng)
        if rng and self.honour_range:
            start = int(rng.split("=")[1].rstrip("-"))
            return FakeResponse(DATA[start:], 206)
        return FakeResponse(DATA, 200)


class SourcesFileTests(unittest.TestCase):
    def _load(self, body: str):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.toml"
            path.write_text(body, encoding="utf-8")
            return gs.load_sources(path)

    def test_tracked_sources_are_valid(self):
        sources = gs.load_sources()
        self.assertIn("qwen3:14b", sources)
        self.assertTrue(all(s.file.endswith(".gguf") for s in sources.values()))

    def test_names_are_canonical_and_fields_required(self):
        body = '[models."m"]\nrepo = "o/r"\nfile = "f.gguf"\nsha256 = "%s"\nbytes = 3\n' % (
            "a" * 64
        )
        self.assertIn("m:latest", self._load(body))
        with self.assertRaises(gs.SourceError):
            self._load('[models."m"]\nrepo = "o/r"\n')
        with self.assertRaises(gs.SourceError):
            self._load(body.replace('"f.gguf"', '"../f.gguf"'))


class FetchTests(unittest.TestCase):
    def test_downloads_and_verifies(self):
        with TemporaryDirectory() as tmp:
            path = gs.fetch(_source(), Path(tmp), log=lambda _m: None, opener=Opener())
            self.assertEqual(path.read_bytes(), DATA)
            self.assertFalse(path.with_name(path.name + ".partial").exists())

    def test_resumes_a_partial_download(self):
        with TemporaryDirectory() as tmp:
            partial = Path(tmp) / "m-Q4_K_M.gguf.partial"
            partial.write_bytes(DATA[:1000])
            opener = Opener()
            path = gs.fetch(_source(), Path(tmp), log=lambda _m: None, opener=opener)
            self.assertEqual(opener.ranges, ["bytes=1000-"])
            self.assertEqual(path.read_bytes(), DATA)

    def test_restarts_when_the_server_ignores_range(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "m-Q4_K_M.gguf.partial").write_bytes(DATA[:1000])
            opener = Opener(honour_range=False)
            path = gs.fetch(_source(), Path(tmp), log=lambda _m: None, opener=opener)
            self.assertEqual(path.read_bytes(), DATA)

    def test_hash_mismatch_discards_the_file(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(gs.SourceError):
                gs.fetch(_source(sha="0" * 64), Path(tmp), log=lambda _m: None, opener=Opener())
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_find_checks_every_tier_and_the_size(self):
        with TemporaryDirectory() as tmp:
            warm = Path(tmp) / "warm"
            (warm / "gguf").mkdir(parents=True)
            source = _source()
            tiers = {"hot": Path(tmp) / "hot", "warm": warm, "cold": Path(tmp) / "cold"}
            self.assertIsNone(gs.find(source, tiers))
            (warm / "gguf" / source.file).write_bytes(DATA[:10])
            self.assertIsNone(gs.find(source, tiers))
            (warm / "gguf" / source.file).write_bytes(DATA)
            self.assertEqual(gs.find(source, tiers), warm / "gguf" / source.file)
            self.assertEqual(gs.gguf_dir("warm", tiers), warm / "gguf")


if __name__ == "__main__":
    unittest.main()
