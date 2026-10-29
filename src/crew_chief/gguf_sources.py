"""crew_chief.gguf_sources — llama.cpp-native GGUF copies of the Ollama models.

``config/gguf-sources.toml`` (tracked) names, for each model, a Hugging Face
file with the same weights and quantization as Ollama's copy, plus its SHA-256.
``fetch`` downloads missing files, resuming partial ones, and keeps a file only
if its hash matches.

Files live beside the storage tier that holds the model: a model on hot
storage gets ``~/.local/share/crew-chief/gguf`` (``CREW_CHIEF_GGUF_DIR``), one
rotated to warm or cold gets ``<tier>/gguf``. Stdlib only.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from crew_chief.serving_policy import REPO_ROOT, canonical, tomllib

DEFAULT_SOURCES_PATH = REPO_ROOT / "config" / "gguf-sources.toml"
HOT_GGUF_DIR = Path(
    os.environ.get("CREW_CHIEF_GGUF_DIR", Path.home() / ".local" / "share" / "crew-chief" / "gguf")
)
CHUNK = 8 * 2**20


class SourceError(RuntimeError):
    """The sources file is invalid or a download failed verification."""


@dataclass(frozen=True)
class GgufSource:
    model: str
    repo: str
    file: str
    sha256: str
    bytes: int
    draft: bool = False

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.file}"


def load_sources(path: Path = DEFAULT_SOURCES_PATH) -> dict[str, GgufSource]:
    if tomllib is None:
        raise SourceError("reading gguf-sources.toml needs Python 3.11+ or `pip install tomli`")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SourceError(f"{path}: {exc}") from exc
    sources = {}
    for model, table in document.get("models", {}).items():
        missing = {"repo", "file", "sha256", "bytes"} - set(table)
        if missing:
            raise SourceError(f'[models."{model}"]: missing {", ".join(sorted(missing))}')
        if "/" in table["file"] or len(table["sha256"]) != 64:
            raise SourceError(f'[models."{model}"]: file must be a bare name, sha256 64 hex digits')
        sources[canonical(model)] = GgufSource(
            canonical(model),
            table["repo"],
            table["file"],
            table["sha256"].lower(),
            table["bytes"],
            bool(table.get("draft", False)),
        )
    return sources


def gguf_dir(tier: str, tiers: dict[str, Path] | None) -> Path:
    if tier == "hot" or not tiers:
        return HOT_GGUF_DIR
    return tiers[tier] / "gguf"


def find(source: GgufSource, tiers: dict[str, Path] | None) -> Path | None:
    """The downloaded file in any tier's GGUF directory, if present."""
    dirs = [HOT_GGUF_DIR] + ([tiers[t] / "gguf" for t in tiers if t != "hot"] if tiers else [])
    for directory in dirs:
        path = directory / source.file
        if path.is_file() and path.stat().st_size == source.bytes:
            return path
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(
    source: GgufSource,
    directory: Path,
    log: Callable[[str], None] = print,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> Path:
    """Download ``source`` into ``directory`` (resuming), verify, and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / source.file
    partial = final.with_name(final.name + ".partial")
    have = partial.stat().st_size if partial.exists() else 0
    if have < source.bytes:
        request = urllib.request.Request(source.url)
        if have:
            request.add_header("Range", f"bytes={have}-")
        log(f"downloading {source.file} ({source.bytes / 2**30:.1f} GiB) from {source.repo}")
        with opener(request, timeout=60) as response:
            # A server that ignores Range sends the whole file again.
            mode = "ab" if have and getattr(response, "status", 200) == 206 else "wb"
            with open(partial, mode) as handle:
                while chunk := response.read(CHUNK):
                    handle.write(chunk)
    if partial.stat().st_size != source.bytes:
        raise SourceError(f"{source.file}: got {partial.stat().st_size} bytes, want {source.bytes}")
    if _sha256(partial) != source.sha256:
        partial.unlink()
        raise SourceError(f"{source.file}: SHA-256 mismatch; download discarded")
    partial.replace(final)
    return final
