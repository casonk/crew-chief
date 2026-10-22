"""crew_chief.taskbench — task-based decision benchmarks.

Speed benchmarks say how fast a model talks; test-based benchmarks say whether
it can fix code. Most local-model work in the portfolio is neither: it is a
bounded decision — route a message, pick a category, flag urgency, fill a
field from a fixed set. This module scores models on exactly that.

Tasks use the question format of TypeSafe AI's Jev decision model, so one task
file runs unchanged against every runner:

- ``choice``: pick one option from ``criteria`` (name -> description)
- ``score``:  pick a level from ``criteria`` (ordered list, low to high)
- ``noul``:   a yes/no proposition; the answer is a probability of "yes"

Runners:

- ``rules``       keyword baseline from the task file; the floor to beat
- ``ollama:<m>``  one call per item, output constrained to a JSON schema
- ``llamacpp:<m>`` one call per question, output constrained to option
                  letters; option probabilities come from token log-probs
- ``systemone:<m>`` a local decision model through Ollama's ``/v1/systemone``
                  endpoint (Ollama 0.35+; Jev-compatible API), e.g. nimble
- ``jev``         TypeSafe's hosted API (``TYPESAFE_API_KEY``); opt-in and
                  metered — only ever send synthetic task data

Metrics per runner and question: accuracy, invalid answers, latency per item,
and, where the runner reports probabilities, the multi-class Brier score.

Stdlib only.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import string
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JEV_URL = "https://api.typesafe.ai/v1/systemone"
QUESTION_TYPES = ("choice", "score", "noul")


class TaskError(ValueError):
    """The task file is malformed."""


# -- task --------------------------------------------------------------------


@dataclass(frozen=True)
class Question:
    qid: str
    type: str
    instructions: str
    criteria: Any = None

    @property
    def labels(self) -> list[str]:
        """Answer values in a fixed order: option names, level numbers, or yes/no."""
        if self.type == "choice":
            return list(self.criteria)
        if self.type == "score":
            return [str(i) for i in range(len(self.criteria))]
        return ["true", "false"]

    def describe(self) -> list[str]:
        if self.type == "choice":
            return [f"{name}: {text}" for name, text in self.criteria.items()]
        if self.type == "score":
            return [f"level {i}: {text}" for i, text in enumerate(self.criteria)]
        crit = self.criteria or {}
        return [
            f"yes: {crit.get('true', 'the statement holds')}",
            f"no: {crit.get('false', 'it does not')}",
        ]


@dataclass(frozen=True)
class Task:
    name: str
    description: str
    questions: dict[str, Question]
    items: list[dict[str, Any]]
    baseline: dict[str, Any] = field(default_factory=dict)


def load_task(path: Path) -> Task:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskError(f"{path}: {exc}") from exc
    questions = {}
    for qid, q in doc.get("questions", {}).items():
        qtype = q.get("type")
        if qtype not in QUESTION_TYPES:
            raise TaskError(f"{path}: question {qid!r} has type {qtype!r}")
        criteria = q.get("criteria")
        if qtype == "choice" and not (isinstance(criteria, dict) and len(criteria) >= 2):
            raise TaskError(f"{path}: choice {qid!r} needs a criteria map of 2+ options")
        if qtype == "score" and not (isinstance(criteria, list) and 2 <= len(criteria) <= 10):
            raise TaskError(f"{path}: score {qid!r} needs 2-10 ordered criteria")
        questions[qid] = Question(qid, qtype, str(q.get("instructions", "")), criteria)
    if not questions:
        raise TaskError(f"{path}: no questions")
    items = doc.get("items", [])
    for index, item in enumerate(items):
        expected = item.get("expected", {})
        for qid, value in expected.items():
            if qid not in questions:
                raise TaskError(f"{path}: item {index} expects unknown question {qid!r}")
            if normalize(questions[qid], value) is None:
                raise TaskError(f"{path}: item {index} has invalid {qid!r} value {value!r}")
    return Task(
        name=doc.get("name", path.stem),
        description=doc.get("description", ""),
        questions=questions,
        items=items,
        baseline=doc.get("baseline", {}),
    )


def normalize(question: Question, value: Any) -> str | None:
    """Map a runner's raw answer onto one of the question's labels, or None."""
    if question.type == "noul":
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value).strip().lower()
        return {"true": "true", "yes": "true", "false": "false", "no": "false"}.get(text)
    text = str(value).strip()
    return text if text in question.labels else None


# -- runners -----------------------------------------------------------------


@dataclass
class Answer:
    value: str | None  # a label, or None when the output was invalid
    probabilities: dict[str, float] | None = None


def _post(url: str, payload: dict, headers: dict | None = None, timeout: int = 300) -> Any:
    data = json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _prompt(task: Task, state: str) -> str:
    lines = [
        "You make bounded decisions about the input below. Answer every question with",
        "exactly one of its allowed values.",
        "",
        "INPUT:",
        state,
        "",
    ]
    for q in task.questions.values():
        lines.append(f"QUESTION {q.qid} ({q.type}): {q.instructions}")
        lines.extend(f"  - {line}" for line in q.describe())
    return "\n".join(lines)


class RulesRunner:
    """Keyword baseline: first matching rule wins, else the question's default."""

    name = "rules"

    def __init__(self, task: Task) -> None:
        self.rules = task.baseline

    def answer(self, task: Task, state: str) -> dict[str, Answer]:
        text = state.lower()
        answers = {}
        for qid, q in task.questions.items():
            spec = self.rules.get(qid, {})
            value = spec.get("default")
            for rule in spec.get("rules", []):
                if any(word.lower() in text for word in rule.get("if_any", [])):
                    value = rule["then"]
                    break
            answers[qid] = Answer(normalize(q, value) if value is not None else None)
        return answers


class OllamaRunner:
    """One call per item; Ollama constrains the reply to a JSON schema."""

    def __init__(self, model: str, url: str = "http://localhost:11434") -> None:
        self.model, self.url = model, url.rstrip("/")
        self.name = f"ollama:{model}"

    def schema(self, task: Task) -> dict:
        props = {}
        for qid, q in task.questions.items():
            if q.type == "noul":
                props[qid] = {"type": "boolean"}
            elif q.type == "score":
                props[qid] = {"type": "integer", "enum": list(range(len(q.criteria)))}
            else:
                props[qid] = {"type": "string", "enum": q.labels}
        return {"type": "object", "properties": props, "required": list(props)}

    def answer(self, task: Task, state: str) -> dict[str, Answer]:
        body = _post(
            f"{self.url}/api/chat",
            {
                "model": self.model,
                "messages": [{"role": "user", "content": _prompt(task, state)}],
                "format": self.schema(task),
                "stream": False,
                "think": False,
                "options": {"temperature": 0},
            },
        )
        try:
            raw = json.loads(body.get("message", {}).get("content", ""))
        except json.JSONDecodeError:
            raw = {}
        return {qid: Answer(normalize(q, raw.get(qid))) for qid, q in task.questions.items()}


class LlamaCppRunner:
    """One call per question, reply limited to an option letter; probabilities from log-probs.

    This is the local stand-in for a decision model: the label set is fixed,
    the model emits one constrained token, and the distribution over the
    allowed letters is the answer's probability vector.
    """

    def __init__(self, model: str, url: str = "http://localhost:8081") -> None:
        self.model, self.url = model, url.rstrip("/")
        self.name = f"llamacpp:{model}"

    @staticmethod
    def letters(question: Question) -> list[str]:
        return list(string.ascii_uppercase[: len(question.labels)])

    def answer(self, task: Task, state: str) -> dict[str, Answer]:
        return {qid: self._one(task, q, state) for qid, q in task.questions.items()}

    def _one(self, task: Task, q: Question, state: str) -> Answer:
        letters = self.letters(q)
        options = "\n".join(
            f"{letter}) {line}" for letter, line in zip(letters, q.describe(), strict=True)
        )
        prompt = (
            f"INPUT:\n{state}\n\nQUESTION: {q.instructions}\n{options}\n\n"
            "Reply with the single letter of the best option."
        )
        grammar = "root ::= " + " | ".join(f'"{letter}"' for letter in letters)
        body = _post(
            f"{self.url}/v1/chat/completions",
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1,
                "temperature": 0,
                "grammar": grammar,
                "logprobs": True,
                "top_logprobs": 20,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        choice = body["choices"][0]
        picked = choice.get("message", {}).get("content", "").strip()
        probs = letter_probabilities(choice.get("logprobs"), letters)
        by_label = {q.labels[i]: probs.get(letter, 0.0) for i, letter in enumerate(letters)}
        if picked in letters:
            value = q.labels[letters.index(picked)]
        elif probs:
            value = q.labels[letters.index(max(probs, key=probs.get))]
        else:
            value = None
        return Answer(value, by_label if probs else None)


def letter_probabilities(logprobs: dict | None, letters: list[str]) -> dict[str, float]:
    """Renormalized probability of each allowed letter from OpenAI-style top_logprobs."""
    if not logprobs or not logprobs.get("content"):
        return {}
    raw: dict[str, float] = {}
    for entry in logprobs["content"][0].get("top_logprobs", []):
        token = entry.get("token", "").strip()
        if token in letters:
            raw[token] = raw.get(token, 0.0) + math.exp(entry["logprob"])
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()} if total > 0 else {}


class SystemOneRunner:
    """A decision model behind the Jev-style ``/v1/systemone`` API.

    Ollama (0.35+) serves local decision models such as Nimble, Tev1 and Clef
    on this API; TypeSafe serves Jev. One call answers every question.
    """

    def __init__(self, model: str, url: str, api_key: str = "", label: str = "systemone") -> None:
        self.api_key, self.model, self.url = api_key, model, url
        self.name = f"{label}:{model}"

    def request(self, task: Task, state: str) -> dict:
        questions = {}
        for qid, q in task.questions.items():
            spec: dict[str, Any] = {"type": q.type, "instructions": q.instructions}
            if q.criteria is not None:
                spec["criteria"] = q.criteria
            questions[qid] = spec
        return {"state": state, "model": self.model, "questions": questions}

    def answer(self, task: Task, state: str) -> dict[str, Answer]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = _post(self.url, self.request(task, state), headers=headers)
        return parse_jev(task, body)


class JevRunner(SystemOneRunner):
    """TypeSafe AI's hosted Jev decision model. Metered; synthetic data only."""

    def __init__(self, api_key: str, model: str = "jev-latest", url: str = JEV_URL) -> None:
        if not api_key:
            raise TaskError("the jev runner needs TYPESAFE_API_KEY")
        super().__init__(model, url, api_key, label="jev")


def parse_jev(task: Task, body: dict) -> dict[str, Answer]:
    answers = {}
    raw = body.get("answers", {})
    for qid, q in task.questions.items():
        a = raw.get(qid, {})
        if q.type == "noul" and "noul" in a:
            p = float(a["noul"])
            answers[qid] = Answer("true" if p >= 0.5 else "false", {"true": p, "false": 1 - p})
        elif q.type in ("choice", "score") and a.get("probabilities"):
            probs = {str(k): float(v) for k, v in a["probabilities"].items()}
            value = str(a["choice"]) if q.type == "choice" else max(probs, key=probs.get)
            answers[qid] = Answer(normalize(q, value), probs)
        else:
            answers[qid] = Answer(None)
    return answers


def make_runner(spec: str, task: Task):
    kind, _, arg = spec.partition(":")
    if kind == "rules":
        return RulesRunner(task)
    if kind == "ollama" and arg:
        return OllamaRunner(arg, os.environ.get("CREW_CHIEF_URL", "http://localhost:11434"))
    if kind == "llamacpp" and arg:
        url = os.environ.get("CREW_CHIEF_LLAMACPP_URL", "http://localhost:8081")
        return LlamaCppRunner(arg, url)
    if kind == "systemone" and arg:
        base = os.environ.get("CREW_CHIEF_URL", "http://localhost:11434").rstrip("/")
        return SystemOneRunner(arg, f"{base}/v1/systemone")
    if kind == "jev":
        return JevRunner(os.environ.get("TYPESAFE_API_KEY", ""), arg or "jev-latest")
    raise TaskError(
        f"unknown runner {spec!r}; use rules, ollama:<model>, llamacpp:<model>, "
        "systemone:<model>, jev"
    )


# -- scoring -----------------------------------------------------------------


def brier(probabilities: dict[str, float], truth: str, labels: list[str]) -> float:
    return sum(
        (probabilities.get(label, 0.0) - (1.0 if label == truth else 0.0)) ** 2 for label in labels
    )


def run(task: Task, runner, *, clock=time.perf_counter) -> dict[str, Any]:
    per_question = {
        qid: {"correct": 0, "invalid": 0, "total": 0, "brier": []} for qid in task.questions
    }
    latencies, errors, rows = [], 0, []
    for index, item in enumerate(task.items):
        started = clock()
        try:
            answers = runner.answer(task, item["state"])
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            errors += 1
            rows.append({"item": index, "error": str(exc)[:200]})
            continue
        latencies.append((clock() - started) * 1000)
        row = {"item": index, "answers": {}}
        for qid, truth in item.get("expected", {}).items():
            q = task.questions[qid]
            truth = normalize(q, truth)
            ans = answers.get(qid, Answer(None))
            stats = per_question[qid]
            stats["total"] += 1
            if ans.value is None:
                stats["invalid"] += 1
            elif ans.value == truth:
                stats["correct"] += 1
            if ans.probabilities:
                stats["brier"].append(brier(ans.probabilities, truth, q.labels))
            row["answers"][qid] = {"value": ans.value, "expected": truth, "p": ans.probabilities}
        rows.append(row)

    summary = {}
    for qid, s in per_question.items():
        summary[qid] = {
            "accuracy": round(s["correct"] / s["total"], 3) if s["total"] else None,
            "invalid": s["invalid"],
            "n": s["total"],
            "brier": round(statistics.fmean(s["brier"]), 3) if s["brier"] else None,
        }
    return {
        "runner": runner.name,
        "task": task.name,
        "items": len(task.items),
        "errors": errors,
        "latency_ms_median": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_p90": round(_p90(latencies), 1) if latencies else None,
        "questions": summary,
        "rows": rows,
    }


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]


def render_markdown(results: list[dict[str, Any]], task: Task, stamp: str) -> str:
    qids = list(task.questions)
    header = (
        "| Runner | "
        + " | ".join(f"{q} acc" for q in qids)
        + " | Brier (mean) | invalid | errors | median ms | p90 ms |"
    )
    lines = [
        f"# Task benchmark: {task.name} ({stamp})",
        "",
        task.description,
        "",
        f"{len(task.items)} items. Accuracy per question; Brier is the multi-class Brier",
        "score over questions where the runner reports probabilities (lower is better).",
        "",
        header,
        "|" + "---|" * (len(qids) + 6),
    ]
    for r in results:
        qs = r["questions"]
        accuracy = ["—" if qs[q]["accuracy"] is None else f"{qs[q]['accuracy']:.2f}" for q in qids]
        briers = [qs[q]["brier"] for q in qids if qs[q]["brier"] is not None]
        cells = [
            r["runner"],
            *accuracy,
            f"{statistics.fmean(briers):.3f}" if briers else "—",
            str(sum(qs[q]["invalid"] for q in qids)),
            str(r["errors"]),
            str(r["latency_ms_median"]),
            str(r["latency_ms_p90"]),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
