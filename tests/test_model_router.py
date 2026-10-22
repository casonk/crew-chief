"""Routing must use pre-run task data and fail safely on uncertain decisions."""

from crew_chief import model_router
from crew_chief.taskbench import Answer


def test_route_uses_only_pre_run_data(monkeypatch, tmp_path):
    observed = {}

    def answer(self, decision_task, state):
        observed["state"] = state
        observed["criteria"] = decision_task.questions["model"].criteria
        return {"model": Answer("small", {"small": 0.8, "strong": 0.2})}

    monkeypatch.setattr(model_router.SystemOneRunner, "answer", answer)
    patch = tmp_path / "new-tests.patch"
    patch.write_text("+++ b/tests/test_value.py\n+def test_new_rule():\n+    assert value == 2\n")
    task = {
        "name": "repair",
        "prompt": "Make the new tests pass.",
        "test_command": ["pytest", "-q"],
        "editable_paths": ["src/value.py"],
        "patch_path": patch,
        "evolution": {
            "before": "old",
            "after": "SECRET_REFERENCE_COMMIT",
            "test_paths": ["tests/test_value.py"],
        },
        "history_review": {"reference_changed_paths": ["SECRET_REFERENCE_FIX"]},
    }
    result = model_router.route_test_repair(
        task=task,
        repo="example",
        candidates=["small", "strong"],
        fallback="strong",
        router_model="decision",
        url="http://localhost:11434",
    )
    assert result["selected_model"] == "small"
    assert result["fallback_reason"] is None
    assert result["confidence"] == 0.8
    assert "SECRET_REFERENCE" not in observed["state"]
    assert '"added_test_names": ["test_new_rule"]' in observed["state"]
    assert '"old_source_failure_counts": {}' in observed["state"]
    assert set(observed["criteria"]) == {"small", "strong"}


def test_route_falls_back_on_uncertain_invalid_and_unavailable(monkeypatch):
    task = {
        "name": "repair",
        "prompt": "Fix it",
        "test_command": ["pytest", "-q"],
        "editable_paths": ["src/value.py"],
    }

    def answer(value, probabilities):
        monkeypatch.setattr(
            model_router.SystemOneRunner,
            "answer",
            lambda *_: {"model": Answer(value, probabilities)},
        )
        return model_router.route_test_repair(
            task=task,
            repo="example",
            candidates=["small", "strong"],
            fallback="strong",
            router_model="decision",
            url="http://localhost:11434",
        )

    assert answer("small", {"small": 0.51})["fallback_reason"] == "low_confidence"
    assert answer("other", {"other": 1.0})["fallback_reason"] == "invalid_choice"
    assert answer("small", None)["fallback_reason"] == "missing_confidence"
    monkeypatch.setattr(
        model_router.SystemOneRunner,
        "answer",
        lambda *_: (_ for _ in ()).throw(TimeoutError()),
    )
    assert (
        model_router.route_test_repair(
            task=task,
            repo="example",
            candidates=["small", "strong"],
            fallback="strong",
            router_model="decision",
            url="http://localhost:11434",
        )["selected_model"]
        == "strong"
    )
