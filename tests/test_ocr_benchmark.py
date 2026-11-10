"""Offline tests for the pixel-first OCR benchmark."""

from __future__ import annotations

import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ocr_benchmark.py"
SPEC = importlib.util.spec_from_file_location("ocr_benchmark", SCRIPT)
assert SPEC and SPEC.loader
ocr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ocr)


def test_reviewed_synthetic_suite_has_pixel_cases_and_fields():
    suite = ocr.load_suite(SCRIPT.parents[1] / "benchmarks" / "ocr" / "synthetic-receipts.json")

    assert len(suite["cases"]) == 6
    assert {case["id"] for case in suite["cases"]} == {
        "clean-grocery-total",
        "rotated-restaurant-tip",
        "faded-fuel-decimals",
        "dense-service-invoice",
        "japanese-cash-tender",
        "email-order-screenshot",
    }
    assert all(case["fields"] and case["render"] for case in suite["cases"])


def test_score_text_tolerates_spacing_and_case_but_not_digit_errors():
    expected = "NORTHSTAR MARKET\nTOTAL 13.75\nVISA 5653"

    exact = ocr.score_text(
        expected,
        "northstar   market\nTotal 13.75\nvisa 5653",
        {"total": "13.75", "card": "5653"},
    )
    wrong = ocr.score_text(
        expected,
        "NORTHSTAR MARKET\nTOTAL 18.75\nVISA 5853",
        {"total": "13.75", "card": "5653"},
    )

    assert exact["passed"] is True
    assert exact["character_error_rate"] == 0
    assert exact["field_accuracy"] == 1
    assert wrong["passed"] is False
    assert wrong["field_accuracy"] == 0


def test_run_case_scores_runner_output_without_live_ocr(monkeypatch, tmp_path):
    case = {
        "id": "one",
        "text": "TOTAL 12.34",
        "fields": {"total": "12.34"},
        "render": {"font": "mono"},
    }
    image = tmp_path / "one.png"
    image.write_bytes(b"not read by the fake runner")
    monkeypatch.setattr(ocr, "_run_tesseract", lambda *args: "TOTAL 12.34\n")

    result = ocr.run_case(
        case,
        "tesseract",
        image,
        prompt="transcribe",
        ollama_url="http://unused",
        timeout=1,
        tesseract_psm=6,
    )

    assert result["passed"] is True
    assert result["error"] is None
    assert result["field_matches"] == {"total": True}


def test_summary_keeps_infrastructure_errors_separate_from_accuracy():
    rows = [
        {
            "runner": "tesseract",
            "passed": True,
            "error": None,
            "character_accuracy": 1.0,
            "word_accuracy": 1.0,
            "field_accuracy": 1.0,
            "elapsed_ms": 10.0,
        },
        {
            "runner": "tesseract",
            "passed": False,
            "error": "missing binary",
            "character_accuracy": 0.0,
            "word_accuracy": 0.0,
            "field_accuracy": 0.0,
            "elapsed_ms": 20.0,
        },
    ]

    summary = ocr.summarize(rows)[0]

    assert summary["passed"] == 1
    assert summary["errors"] == 1
    assert summary["character_accuracy"] == 0.5
    assert summary["median_ms"] == 15.0
