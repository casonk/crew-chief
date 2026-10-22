"""Bounded local model selection for test-repair benchmark trials."""

from __future__ import annotations

import json
import math
import re
import time

from crew_chief.taskbench import Question, SystemOneRunner, Task


def route_test_repair(
    *,
    task: dict,
    repo: str,
    candidates: list[str],
    fallback: str,
    router_model: str,
    url: str,
    min_confidence: float = 0.55,
    timeout: int = 30,
    profiles: dict | None = None,
) -> dict:
    """Select an eligible model using only information available before a trial.

    Failure and uncertain answers use the caller's known eligible fallback. The
    historical reference implementation and post-run outcomes never enter state.
    """
    if len(set(candidates)) != len(candidates) or len(candidates) < 2:
        raise ValueError("routing needs at least two distinct candidate models")
    if fallback not in candidates:
        raise ValueError("router fallback must be one of the candidates")
    if not 0 <= min_confidence <= 1 or not math.isfinite(min_confidence):
        raise ValueError("router confidence threshold must be between 0 and 1")
    if timeout < 1:
        raise ValueError("router timeout must be positive")
    profile_map = profiles or {}
    criteria = {}
    for name in candidates:
        profile = profile_map.get(name, {})
        criteria[name] = (
            f"family={profile.get('family', 'unknown')}; "
            f"parameters={profile.get('parameter_size', 'unknown')}; "
            f"quantization={profile.get('quantization', 'unknown')}"
        )
    question = Question(
        "model",
        "choice",
        "Choose the smallest likely capable coding agent for this test repair. "
        "Prefer a stronger model when the task looks complex. Choose exactly one candidate.",
        criteria,
    )
    decision_task = Task("test-repair-router", "Select a coding agent", {"model": question}, [])
    test_signals = {}
    if "evolution" in task:
        patch = task["patch_path"].read_text(encoding="utf-8", errors="replace")
        added = [
            line[1:]
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        test_signals = {
            "added_test_names": re.findall(r"^def (test_\w+)", "\n".join(added), re.MULTILINE)[:20],
            "added_assertions": sum(bool(re.match(r"\s*assert\b", line)) for line in added),
            "added_lines": len(added),
            "old_source_failure_counts": task.get("history_review", {})
            .get("new_tests_on_old_source", {})
            .get("counts", {}),
        }
    state = json.dumps(
        {
            "repository": repo,
            "task": task["name"],
            "instructions": task["prompt"],
            "test_command": task["test_command"],
            "test_paths": task.get("evolution", {}).get("test_paths", []),
            "editable_paths": task["editable_paths"],
            "test_signals": test_signals,
        },
        sort_keys=True,
    )
    started = time.monotonic()
    result = {
        "router_model": router_model,
        "selected_model": fallback,
        "fallback_model": fallback,
        "confidence": None,
        "probabilities": None,
        "fallback_reason": None,
    }
    try:
        answer = SystemOneRunner(
            router_model, f"{url.rstrip('/')}/v1/systemone", timeout=timeout
        ).answer(decision_task, state)["model"]
        probabilities = answer.probabilities
        result["probabilities"] = probabilities
        if answer.value not in candidates:
            result["fallback_reason"] = "invalid_choice"
        elif not isinstance(probabilities, dict) or not isinstance(
            probabilities.get(answer.value), (int, float)
        ):
            result["fallback_reason"] = "missing_confidence"
        else:
            confidence = float(probabilities[answer.value])
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                result["fallback_reason"] = "invalid_confidence"
            elif confidence < min_confidence:
                result["confidence"] = confidence
                result["fallback_reason"] = "low_confidence"
            else:
                result["selected_model"] = answer.value
                result["confidence"] = confidence
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        result["fallback_reason"] = type(exc).__name__
    result["router_seconds"] = round(time.monotonic() - started, 2)
    return result
