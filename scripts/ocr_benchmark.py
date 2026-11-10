#!/usr/bin/env python3
"""Benchmark OCR engines and vision models on reviewed synthetic documents.

The benchmark deliberately starts from pixels.  Text-only extraction and
receipt classification suites cannot measure OCR quality because recognition
has already happened before those tasks begin.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import pathlib
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

DEFAULT_OLLAMA_URL = os.environ.get("CREW_CHIEF_URL", "http://localhost:11434")
DEFAULT_PROMPT = (
    "Transcribe every visible character in this document exactly. "
    "Preserve reading order and line breaks. Return only the transcription, "
    "with no explanation or Markdown fences."
)
FONT_CANDIDATES = {
    "mono": (
        "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf",
    ),
    "sans": (
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf",
    ),
    "cjk": (
        "/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ),
}


class BenchmarkError(RuntimeError):
    """Raised when a suite or runner cannot be executed."""


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "ocr"


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    """Normalize harmless presentation differences without fixing OCR errors."""
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("’", "'").replace("`", "'")
    return re.sub(r"\s+", " ", value).strip().casefold()


def edit_distance(left: list[str] | str, right: list[str] | str) -> int:
    """Return Levenshtein distance using memory proportional to one row."""
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, left_item in enumerate(left, 1):
        current = [row]
        for column, right_item in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def score_text(expected: str, actual: str, fields: dict[str, str]) -> dict[str, Any]:
    expected_norm = normalize_text(expected)
    actual_norm = normalize_text(actual)
    char_error_rate = edit_distance(expected_norm, actual_norm) / max(1, len(expected_norm))
    expected_words = expected_norm.split()
    actual_words = actual_norm.split()
    word_error_rate = edit_distance(expected_words, actual_words) / max(1, len(expected_words))
    field_matches = {
        name: normalize_text(str(value)) in actual_norm for name, value in fields.items()
    }
    field_accuracy = sum(field_matches.values()) / max(1, len(field_matches))
    return {
        "character_error_rate": char_error_rate,
        "character_accuracy": max(0.0, 1.0 - char_error_rate),
        "word_error_rate": word_error_rate,
        "word_accuracy": max(0.0, 1.0 - word_error_rate),
        "field_accuracy": field_accuracy,
        "field_matches": field_matches,
        "passed": char_error_rate <= 0.20 and all(field_matches.values()),
    }


def load_suite(path: pathlib.Path) -> dict[str, Any]:
    try:
        suite = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot load OCR suite {path}: {exc}") from exc
    if not isinstance(suite, dict) or not isinstance(suite.get("cases"), list):
        raise BenchmarkError("OCR suite must be an object with a cases list")
    if not suite.get("name") or not suite["cases"]:
        raise BenchmarkError("OCR suite needs a name and at least one case")
    seen: set[str] = set()
    for case in suite["cases"]:
        if not isinstance(case, dict) or not case.get("id") or not case.get("text"):
            raise BenchmarkError("every OCR case needs non-empty id and text fields")
        if case["id"] in seen:
            raise BenchmarkError(f"duplicate OCR case id: {case['id']}")
        seen.add(case["id"])
        if not isinstance(case.get("fields", {}), dict):
            raise BenchmarkError(f"OCR case {case['id']} fields must be an object")
        if not isinstance(case.get("render", {}), dict):
            raise BenchmarkError(f"OCR case {case['id']} render must be an object")
    return suite


def _font_path(kind: str) -> pathlib.Path:
    candidates = FONT_CANDIDATES.get(kind)
    if not candidates:
        raise BenchmarkError(f"unknown synthetic font kind: {kind}")
    for candidate in candidates:
        path = pathlib.Path(candidate)
        if path.is_file():
            return path
    raise BenchmarkError(f"no installed font found for synthetic font kind: {kind}")


def render_case(case: dict[str, Any], destination: pathlib.Path) -> None:
    """Render one deterministic document image from its reviewed text fixture."""
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
    except ImportError as exc:
        raise BenchmarkError(
            "synthetic OCR fixtures require Pillow (install the benchmark/dev dependency)"
        ) from exc

    spec = case.get("render", {})
    font = ImageFont.truetype(
        str(_font_path(str(spec.get("font", "mono")))), int(spec.get("font_size", 28))
    )
    padding = int(spec.get("padding", 42))
    spacing = int(spec.get("spacing", 10))
    probe = Image.new("L", (1, 1), 255)
    draw = ImageDraw.Draw(probe)
    bounds = draw.multiline_textbbox((0, 0), case["text"], font=font, spacing=spacing)
    width = max(320, bounds[2] - bounds[0] + padding * 2)
    height = max(180, bounds[3] - bounds[1] + padding * 2)
    background = int(spec.get("background", 255))
    foreground = int(spec.get("foreground", 15))
    image = Image.new("L", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.multiline_text(
        (padding, padding), case["text"], fill=foreground, font=font, spacing=spacing
    )

    contrast = float(spec.get("contrast", 1.0))
    if contrast != 1.0:
        image = ImageEnhance.Contrast(image).enhance(contrast)
    blur = float(spec.get("blur", 0.0))
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    noise = float(spec.get("noise", 0.0))
    if noise:
        pixels = image.load()
        rng = random.Random(str(case["id"]))
        count = math.floor(width * height * noise)
        for _ in range(count):
            x = rng.randrange(width)
            y = rng.randrange(height)
            pixels[x, y] = rng.choice((0, 255))
    rotation = float(spec.get("rotation", 0.0))
    if rotation:
        image = image.rotate(rotation, expand=True, fillcolor=background)
    scale = float(spec.get("scale", 1.0))
    if scale != 1.0:
        scaled = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(scaled)
    image.save(destination, format="PNG", optimize=True)


def renderer_metadata(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Record enough renderer provenance to explain changed pixel hashes."""
    try:
        import PIL
    except ImportError as exc:
        raise BenchmarkError("synthetic OCR fixtures require Pillow") from exc
    kinds = {str(case.get("render", {}).get("font", "mono")) for case in cases}
    fonts = {}
    for kind in sorted(kinds):
        path = _font_path(kind)
        fonts[kind] = {"path": str(path), "sha256": _sha256(path)}
    return {"pillow_version": PIL.__version__, "fonts": fonts}


def _run_tesseract(image: pathlib.Path, timeout: float, psm: int) -> str:
    completed = subprocess.run(
        ["tesseract", str(image), "stdout", "--psm", str(psm)],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode:
        raise BenchmarkError(completed.stderr.strip() or f"tesseract exited {completed.returncode}")
    return completed.stdout


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BenchmarkError(str(exc)) from exc


def _run_ollama(
    image: pathlib.Path,
    model: str,
    prompt: str,
    base_url: str,
    timeout: float,
) -> str:
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    body = _post_json(
        f"{base_url.rstrip('/')}/api/chat",
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": [encoded]}],
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout,
    )
    return str(body.get("message", {}).get("content") or "")


def run_case(
    case: dict[str, Any],
    runner: str,
    image: pathlib.Path,
    *,
    prompt: str,
    ollama_url: str,
    timeout: float,
    tesseract_psm: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    error: str | None = None
    output = ""
    try:
        if runner == "tesseract":
            output = _run_tesseract(image, timeout, tesseract_psm)
        elif runner.startswith("ollama:") and runner.removeprefix("ollama:"):
            output = _run_ollama(
                image,
                runner.removeprefix("ollama:"),
                prompt,
                ollama_url,
                timeout,
            )
        else:
            raise BenchmarkError(f"unknown OCR runner: {runner}")
    except (BenchmarkError, OSError, subprocess.TimeoutExpired) as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = (time.perf_counter() - started) * 1000
    score = score_text(case["text"], output, case.get("fields", {}))
    if error:
        score["passed"] = False
    return {
        "case": case["id"],
        "runner": runner,
        "image_sha256": _sha256(image),
        "elapsed_ms": elapsed_ms,
        "expected": case["text"],
        "fields": case.get("fields", {}),
        "render": case.get("render", {}),
        "output": output,
        "error": error,
        **score,
    }


def summarize(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for runner in dict.fromkeys(result["runner"] for result in results):
        rows = [result for result in results if result["runner"] == runner]
        summaries.append(
            {
                "runner": runner,
                "cases": len(rows),
                "passed": sum(bool(row["passed"]) for row in rows),
                "errors": sum(bool(row["error"]) for row in rows),
                "character_accuracy": statistics.fmean(row["character_accuracy"] for row in rows),
                "word_accuracy": statistics.fmean(row["word_accuracy"] for row in rows),
                "field_accuracy": statistics.fmean(row["field_accuracy"] for row in rows),
                "median_ms": statistics.median(row["elapsed_ms"] for row in rows),
            }
        )
    return summaries


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# OCR benchmark: {report['suite']['name']}",
        "",
        f"Created: `{report['created_at']}`  ",
        f"Suite: `{report['suite']['path']}` (`{report['suite']['sha256'][:12]}`)",
        "",
        "This benchmark starts from rendered pixels. Character/word accuracy use normalized "
        "Levenshtein distance; field accuracy requires each reviewed value to appear in the output.",
        "",
        "| Runner | Passed | Errors | Character | Word | Fields | Median ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["summary"]:
        lines.append(
            f"| {row['runner']} | {row['passed']}/{row['cases']} | {row['errors']} | "
            f"{row['character_accuracy']:.1%} | {row['word_accuracy']:.1%} | "
            f"{row['field_accuracy']:.1%} | {row['median_ms']:.0f} |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Case | Runner | Pass | CER | WER | Fields | ms | Error |",
            "|---|---|:---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in report["results"]:
        error = (row["error"] or "").replace("|", "\\|")
        lines.append(
            f"| {row['case']} | {row['runner']} | {'yes' if row['passed'] else 'no'} | "
            f"{row['character_error_rate']:.3f} | {row['word_error_rate']:.3f} | "
            f"{row['field_accuracy']:.1%} | {row['elapsed_ms']:.0f} | {error} |"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=pathlib.Path, required=True)
    parser.add_argument(
        "--runner",
        action="append",
        required=True,
        help="Repeat for tesseract or ollama:<model>.",
    )
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("results"))
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--tesseract-psm", type=int, default=6)
    parser.add_argument("--keep-images", type=pathlib.Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    suite_path = args.suite.resolve()
    try:
        suite = load_suite(suite_path)
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    if args.keep_images:
        args.keep_images.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="crew-chief-ocr-bench-") as temporary:
        image_dir = pathlib.Path(temporary)
        results: list[dict[str, Any]] = []
        for case in suite["cases"]:
            image = image_dir / f"{_slug(case['id'])}.png"
            try:
                render_case(case, image)
            except BenchmarkError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            if args.keep_images:
                (args.keep_images / image.name).write_bytes(image.read_bytes())
            for runner in args.runner:
                print(f"[{runner}] {case['id']}", flush=True)
                result = run_case(
                    case,
                    runner,
                    image,
                    prompt=str(suite.get("prompt") or DEFAULT_PROMPT),
                    ollama_url=args.ollama_url,
                    timeout=args.timeout,
                    tesseract_psm=args.tesseract_psm,
                )
                results.append(result)
                status = "pass" if result["passed"] else "fail"
                print(
                    f"  {status}: CER={result['character_error_rate']:.3f} "
                    f"fields={result['field_accuracy']:.0%} {result['elapsed_ms']:.0f}ms",
                    flush=True,
                )

    created = datetime.now(timezone.utc)
    report = {
        "schema_version": 1,
        "created_at": created.isoformat(),
        "suite": {
            "name": suite["name"],
            "path": str(args.suite),
            "sha256": _sha256(suite_path),
            "case_count": len(suite["cases"]),
        },
        "protocol": {
            "prompt": str(suite.get("prompt") or DEFAULT_PROMPT),
            "timeout_seconds": args.timeout,
            "tesseract_psm": args.tesseract_psm,
            "renderer": renderer_metadata(suite["cases"]),
        },
        "summary": summarize(results),
        "results": results,
    }
    stamp = created.astimezone().strftime("%Y%m%d-%H%M%S")
    base = args.out / f"ocr-bench-{_slug(suite['name'])}-{stamp}"
    json_path = base.with_suffix(".json")
    markdown_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Saved: {markdown_path} and {json_path}")
    return 1 if all(row["error"] for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
