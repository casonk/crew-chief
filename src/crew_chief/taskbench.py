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

Protocol: every task has a train and a test split. The whole train set is always
given to a model a priori, as worked examples in its system prompt (an item is
never shown its own answer: when a train item is scored it is left out of its own
examples), and results are scored on the test split by default. ``--zero-shot``
drops the examples for an ablation and is reported as such. The keyword baseline
is fitted on train only.

Stdlib only.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import math
import os
import re
import statistics
import string
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JEV_URL = "https://api.typesafe.ai/v1/systemone"
QUESTION_TYPES = ("choice", "score", "noul")
# Every item is `train` (the examples every prompt carries, and what rules are fitted to) or
# `test` (scored, never shown to a model). An item with no `split` is train. `all` selects both.
# `dev` and `heldout` are the old names for `train` and `test` and are still read.
SPLITS = ("train", "test")
SPLIT_ALIASES = {"dev": "train", "heldout": "test"}


def canonical_split(value: Any) -> str:
    """``train`` or ``test`` for a split name (including the old ``dev`` and ``heldout``)."""
    name = SPLIT_ALIASES.get(str(value), str(value))
    if name not in SPLITS:
        raise TaskError(f"unknown split {value!r}; use train, test or all")
    return name


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


def _state_key(state: Any) -> str:
    return " ".join(str(state).lower().split())


@dataclass(frozen=True)
class Task:
    name: str
    description: str
    questions: dict[str, Question]
    items: list[dict[str, Any]]
    baseline: dict[str, Any] = field(default_factory=dict)
    split: str = "all"
    # The train items every prompt carries a priori; kept whole when a split is selected.
    examples: tuple[dict[str, Any], ...] = ()
    zero_shot: bool = False

    def select(self, split: str) -> Task:
        """This task restricted to one split; ``all`` keeps every item. The examples stay."""
        if split == "all":
            return self
        name = canonical_split(split)
        items = [i for i in self.items if i["split"] == name]
        if not items:
            raise TaskError(f"{self.name} has no {name} items")
        return dataclasses.replace(self, items=items, split=name)

    def examples_for(self, state: str) -> tuple[dict[str, Any], ...]:
        """The examples for scoring *state*: every train item except the one being scored."""
        key = _state_key(state)
        return tuple(e for e in self.examples if _state_key(e["state"]) != key)

    def without_examples(self) -> Task:
        """The same task with no examples in any prompt (a zero-shot ablation, reported as such)."""
        return dataclasses.replace(self, examples=(), zero_shot=True)

    @property
    def leave_one_out(self) -> bool:
        """True when train items are scored: each is then scored without its own example."""
        return self.split in ("train", "all")


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
    items = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(doc.get("items", [])):
        try:
            item = {**raw, "split": canonical_split(raw.get("split", "train"))}
        except TaskError as exc:
            raise TaskError(f"{path}: item {index}: {exc}") from exc
        items.append(item)
        # The same text in two items could leak a train answer into the test score.
        key = " ".join(str(item.get("state", "")).lower().split())
        if key in seen:
            raise TaskError(f"{path}: item {index} repeats the state of item {seen[key]}")
        seen[key] = index
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
        examples=tuple(i for i in items if i["split"] == "train"),
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


def example_answers(task: Task, example: dict[str, Any], qids: list[str] | None = None) -> str:
    """An example's correct answers as ``qid=label`` pairs (only for the questions asked about)."""
    pairs = []
    for qid in qids or list(task.questions):
        if qid in example.get("expected", {}):
            pairs.append(f"{qid}={normalize(task.questions[qid], example['expected'][qid])}")
    return ", ".join(pairs)


def format_examples(
    task: Task,
    state: str,
    qids: list[str] | None = None,
    answer: Callable[[dict[str, Any]], str] | None = None,
) -> str:
    """The train examples as worked answers to place before the input; empty when there are none.

    The item being scored is left out, so a model is never shown the answer it is asked for.
    """
    examples = task.examples_for(state)
    if not examples:
        return ""
    lines = [
        "EXAMPLES: inputs that have already been decided, with their correct answers. "
        "Follow the same reasoning for the new INPUT.",
        "",
    ]
    render = answer or (lambda e: example_answers(task, e, qids))
    for example in examples:
        text = render(example)
        if text:  # an example with no answer to this question teaches nothing about it
            lines.append(f"INPUT: {example['state']}")
            lines.append(f"ANSWER: {text}")
    return "\n".join(lines) if len(lines) > 2 else ""


def _instructions(task: Task, state: str = "") -> str:
    """The questions and every allowed answer, then the train examples, all before the input."""
    lines = [
        "You make bounded decisions about the input you are given. Answer every question",
        "with exactly one of its allowed values; do not invent values outside the list.",
        "",
    ]
    for q in task.questions.values():
        lines.append(f"QUESTION {q.qid} ({q.type}): {q.instructions}")
        lines.append("Allowed values:")
        lines.extend(f"  - {line}" for line in q.describe())
        lines.append("")
    text = "\n".join(lines).rstrip()
    examples = format_examples(task, state)
    return f"{text}\n\n{examples}" if examples else text


def _prompt(task: Task, state: str) -> str:
    return f"{_instructions(task, state)}\n\nINPUT:\n{state}"


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
                "messages": [
                    {"role": "system", "content": _instructions(task, state)},
                    {"role": "user", "content": f"INPUT:\n{state}"},
                ],
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
        examples = format_examples(
            task,
            state,
            [q.qid],
            lambda e: (
                letters[q.labels.index(normalize(q, e["expected"][q.qid]))]
                if q.qid in e.get("expected", {})
                else ""
            ),
        )
        prompt = (
            f"QUESTION: {q.instructions}\nAllowed options:\n{options}\n\n"
            + (f"{examples}\n\n" if examples else "")
            + f"INPUT:\n{state}\n\nReply with the single letter of the best option."
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

    def __init__(
        self,
        model: str,
        url: str,
        api_key: str = "",
        label: str = "systemone",
        timeout: int = 300,
    ) -> None:
        self.api_key, self.model, self.url = api_key, model, url
        self.timeout = timeout
        self.name = f"{label}:{model}"

    def request(self, task: Task, state: str) -> dict:
        # The API has no system prompt, so the train examples go in front of the input inside
        # ``state``. Measured on the test splits this beat putting them in each question's
        # instructions (results/example-placement-*.md).
        questions = {}
        for qid, q in task.questions.items():
            spec: dict[str, Any] = {"type": q.type, "instructions": q.instructions}
            if q.criteria is not None:
                spec["criteria"] = q.criteria
            questions[qid] = spec
        examples = format_examples(task, state)
        body = f"{examples}\n\nNEW INPUT (decide this one):\n{state}" if examples else state
        return {"state": body, "model": self.model, "questions": questions}

    def answer(self, task: Task, state: str) -> dict[str, Answer]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = _post(self.url, self.request(task, state), headers=headers, timeout=self.timeout)
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


# -- bayesian prior from the train split -------------------------------------

JOINT_LIMIT = 5000  # label combinations; a larger joint is skipped and questions stay independent


def tokens(state: str) -> set[str]:
    """The distinct lowercase words of an input; the features of the naive-Bayes prior."""
    return {w for w in re.findall(r"[a-z0-9']+", state.lower()) if len(w) > 1}


class BayesPrior:
    """Probabilities fitted on the train examples alone (Laplace-smoothed counts).

    Per question: P(label) and P(word | label), combined as naive Bayes. Across questions: the
    joint P(label combination), so an answer set that never occurs in train is unlikely even if each
    answer alone is plausible. ``posterior`` returns one distribution per question.
    """

    def __init__(
        self,
        task: Task,
        examples: tuple[dict[str, Any], ...],
        alpha: float = 1.0,
        word_alpha: float = 0.1,
    ) -> None:
        self.task, self.alpha, self.word_alpha = task, alpha, word_alpha
        self.rows = []
        for e in examples:
            truth = {}
            for qid, q in task.questions.items():
                if qid in e.get("expected", {}):
                    truth[qid] = normalize(q, e["expected"][qid])
            if truth:
                self.rows.append((tokens(e["state"]), truth))
        self.vocab = {w for words, _ in self.rows for w in words}
        self.label_n: dict[str, dict[str, int]] = {}
        self.word_n: dict[str, dict[str, dict[str, int]]] = {}
        for qid, q in task.questions.items():
            self.label_n[qid] = {label: 0 for label in q.labels}
            self.word_n[qid] = {label: {} for label in q.labels}
        self.joint_n: dict[tuple, int] = {}
        for words, truth in self.rows:
            for qid, label in truth.items():
                if label is None:
                    continue
                self.label_n[qid][label] += 1
                for w in words:
                    self.word_n[qid][label][w] = self.word_n[qid][label].get(w, 0) + 1
            if len(truth) == len(task.questions) and None not in truth.values():
                key = tuple(truth[qid] for qid in task.questions)
                self.joint_n[key] = self.joint_n.get(key, 0) + 1

    def marginal(self, qid: str) -> dict[str, float]:
        n = self.label_n[qid]
        total = sum(n.values()) + self.alpha * len(n)
        return {label: (c + self.alpha) / total for label, c in n.items()}

    def naive(self, qid: str, state: str) -> dict[str, float]:
        """P(label | words) for one question, with the words' evidence in log space."""
        words = tokens(state) & self.vocab
        marginal = self.marginal(qid)
        logs = {}
        for label, prior in marginal.items():
            counts = self.word_n[qid][label]
            denom = sum(counts.values()) + self.word_alpha * len(self.vocab)
            score = math.log(prior)
            for w in words:
                score += math.log((counts.get(w, 0) + self.word_alpha) / denom)
            logs[label] = score
        return _softmax(logs)

    def joint_prior(self) -> dict[tuple, float] | None:
        labels = [q.labels for q in self.task.questions.values()]
        size = math.prod(len(x) for x in labels)
        if size > JOINT_LIMIT or len(labels) < 2:
            return None
        total = sum(self.joint_n.values()) + self.alpha * size
        return {
            key: (self.joint_n.get(key, 0) + self.alpha) / total
            for key in itertools.product(*labels)
        }

    def posterior(
        self, state: str, likelihood: dict[str, dict[str, float]] | None = None
    ) -> dict[str, dict[str, float]]:
        """Per-question distributions. With *likelihood* (a model's probabilities) they are fused:
        posterior ∝ prior × likelihood, the joint correcting the marginals it already contains."""
        qids = list(self.task.questions)
        per_q = {}
        for qid in qids:
            base = self.naive(qid, state)
            if likelihood and qid in likelihood:
                # the model's probabilities replace the word evidence; the label prior stays
                base = _normalise(
                    {
                        label: self.marginal(qid)[label]
                        * max(likelihood[qid].get(label, 0.0), 1e-6)
                        for label in base
                    }
                )
            per_q[qid] = base
        joint = self.joint_prior()
        if joint is None:
            return per_q
        marg = {qid: self.marginal(qid) for qid in qids}
        score = {}
        for key, prior in joint.items():
            value = prior
            for qid, label in zip(qids, key, strict=True):
                value *= per_q[qid][label] / marg[qid][label]
            score[key] = value
        score = _normalise(score)
        out = {qid: {label: 0.0 for label in self.task.questions[qid].labels} for qid in qids}
        for key, p in score.items():
            for qid, label in zip(qids, key, strict=True):
                out[qid][label] += p
        return out


def _normalise(scores: dict) -> dict:
    total = sum(scores.values()) or 1.0
    return {k: v / total for k, v in scores.items()}


def _softmax(logs: dict[str, float]) -> dict[str, float]:
    top = max(logs.values())
    return _normalise({k: math.exp(v - top) for k, v in logs.items()})


def _top(probs: dict[str, float]) -> str:
    return max(probs, key=probs.get)


class BayesRunner:
    """The prior alone: naive Bayes plus the joint, fitted on train. A baseline any model must beat."""

    name = "bayes"

    def __init__(self, task: Task) -> None:
        self.cache: dict[str, BayesPrior] = {}

    def prior(self, task: Task, state: str) -> BayesPrior:
        key = _state_key(state)  # leave-one-out: a train item is scored by a prior without it
        if key not in self.cache:
            self.cache[key] = BayesPrior(task, task.examples_for(state))
        return self.cache[key]

    def answer(self, task: Task, state: str) -> dict[str, Answer]:
        post = self.prior(task, state).posterior(state)
        return {qid: Answer(_top(p), p) for qid, p in post.items()}


class BayesFusionRunner:
    """A model's answer weighed against the train prior: posterior ∝ prior × model likelihood.

    A model without probabilities (a plain JSON reply) counts as 0.9 for its answer and the
    remainder spread over the other labels.
    """

    def __init__(self, inner, task: Task) -> None:
        self.inner, self.bayes = inner, BayesRunner(task)
        self.name = f"bayes+{inner.name}"

    def answer(self, task: Task, state: str) -> dict[str, Answer]:
        got = self.inner.answer(task, state)
        likelihood = {}
        for qid, ans in got.items():
            labels = task.questions[qid].labels
            if ans.probabilities:
                likelihood[qid] = ans.probabilities
            elif ans.value is not None:
                rest = 0.1 / max(len(labels) - 1, 1)
                likelihood[qid] = {x: (0.9 if x == ans.value else rest) for x in labels}
        post = self.bayes.prior(task, state).posterior(state, likelihood)
        return {qid: Answer(_top(p), p) for qid, p in post.items()}


def make_runner(spec: str, task: Task):
    kind, _, arg = spec.partition(":")
    if kind == "rules":
        return RulesRunner(task)
    if kind == "bayes":
        return BayesFusionRunner(make_runner(arg, task), task) if arg else BayesRunner(task)
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
        f"unknown runner {spec!r}; use rules, bayes, bayes:<runner>, ollama:<model>, llamacpp:<model>, "
        "systemone:<model>, jev"
    )


# -- scoring -----------------------------------------------------------------


def brier(probabilities: dict[str, float], truth: str, labels: list[str]) -> float:
    return sum(
        (probabilities.get(label, 0.0) - (1.0 if label == truth else 0.0)) ** 2 for label in labels
    )


def protocol(task: Task) -> dict[str, Any]:
    """How this run was set up, recorded with its results so they are never read as another protocol."""
    return {
        "split": task.split,
        "train_examples": len(task.examples),
        "zero_shot": task.zero_shot,
        "leave_one_out": task.leave_one_out,
    }


def protocol_line(task: Task) -> str:
    """One sentence on how the run was set up, for the top of a report."""
    if task.zero_shot:
        shot = "**Zero-shot ablation**: no train examples in the prompts; not comparable with the standard protocol."
    else:
        shot = f"All {len(task.examples)} train examples are in every prompt as worked examples."
    if task.leave_one_out:
        scored = "Train items are scored leave-one-out (each without its own example)."
    else:
        scored = "Only test items are scored, and none is ever shown to a model."
    return f"Protocol: {shot} {scored}"


def run(task: Task, runner, *, clock=time.perf_counter) -> dict[str, Any]:
    per_question = {
        qid: {
            "correct": 0,
            "invalid": 0,
            "total": 0,
            "brier": [],
            "counts": {t: {p: 0 for p in q.labels} for t in q.labels},
            "missed": {t: 0 for t in q.labels},
        }
        for qid, q in task.questions.items()
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
        elapsed_ms = (clock() - started) * 1000
        latencies.append(elapsed_ms)
        row = {"item": index, "ms": round(elapsed_ms, 2), "answers": {}}
        for qid, truth in item.get("expected", {}).items():
            q = task.questions[qid]
            truth = normalize(q, truth)
            ans = answers.get(qid, Answer(None))
            stats = per_question[qid]
            stats["total"] += 1
            if ans.value is None:
                stats["invalid"] += 1
                stats["missed"][truth] += 1
            else:
                stats["counts"][truth][ans.value] += 1
                if ans.value == truth:
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
            "confusion": confusion(task.questions[qid].labels, s["counts"], s["missed"]),
        }
    return {
        "runner": runner.name,
        "task": task.name,
        "items": len(task.items),
        "errors": errors,
        "latency_ms_mean": round(statistics.fmean(latencies), 1) if latencies else None,
        "latency_ms_median": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_p90": round(_p90(latencies), 1) if latencies else None,
        "questions": summary,
        "protocol": protocol(task),
        "rows": rows,
    }


def confusion(
    labels: list[str], counts: dict[str, dict[str, int]], missed: dict[str, int]
) -> dict[str, Any]:
    """Confusion matrix (rows: expected, columns: answered) with per-label precision/recall.

    ``invalid`` counts items whose answer was not an allowed value; they lower
    recall for the expected label but belong to no predicted column.
    """
    per_label = {}
    for label in labels:
        support = sum(counts[label].values()) + missed[label]
        predicted = sum(counts[t][label] for t in labels)
        hit = counts[label][label]
        precision = hit / predicted if predicted else None
        recall = hit / support if support else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall
            else (0.0 if support and predicted else None)
        )
        per_label[label] = {
            "support": support,
            "precision": None if precision is None else round(precision, 3),
            "recall": None if recall is None else round(recall, 3),
            "f1": None if f1 is None else round(f1, 3),
        }
    return {"labels": labels, "counts": counts, "invalid": missed, "per_label": per_label}


def macro_f1(conf: dict[str, Any]) -> float | None:
    """Unweighted mean F1 over the labels that occur; a never-predicted label scores 0."""
    scores = [stats["f1"] or 0.0 for stats in conf["per_label"].values() if stats["support"]]
    return statistics.fmean(scores) if scores else None


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]


def result_entry(result: dict[str, Any]) -> tuple[float, float, float] | None:
    """A run's accuracy (averaged over its questions), mean latency and p90 latency."""
    accuracies = [q["accuracy"] for q in result["questions"].values() if q["accuracy"] is not None]
    mean, p90 = result.get("latency_ms_mean"), result.get("latency_ms_p90")
    if not accuracies or mean is None or p90 is None:
        return None
    return statistics.fmean(accuracies), mean, p90


def result_score(result: dict[str, Any], profile, ref=None) -> str:
    """A run's score under a scoring profile; ``ref`` is the latency range of all runners."""
    from crew_chief import scoring

    entry = result_entry(result)
    if entry is None:
        return "—"
    got = scoring.score(profile, *entry, ref=ref)
    return "gated" if got.value is None else f"{got.value:.3f}"


def render_markdown(
    results: list[dict[str, Any]], task: Task, stamp: str, profiles: list | None = None
) -> str:
    profiles = profiles or []
    qids = list(task.questions)
    from crew_chief import scoring

    ref = scoring.reference(
        {r["runner"]: entry for r in results if (entry := result_entry(r)) is not None}
    )
    header = (
        "| Runner | "
        + " | ".join(f"{q} acc" for q in qids)
        + " | "
        + " | ".join(f"{q} macro F1" for q in qids)
        + " | Brier (mean) | invalid | errors | median ms | p90 ms |"
        + "".join(f" score: {p.name} |" for p in profiles)
    )
    lines = [
        f"# Task benchmark: {task.name} ({stamp})",
        "",
        task.description,
        "",
        f"{len(task.items)} items ({task.split} split). Accuracy per question; Brier is the multi-class Brier",
        "score over questions where the runner reports probabilities (lower is better).",
        "",
        protocol_line(task),
        "",
        header,
        "|" + "---|" * (2 * len(qids) + 6 + len(profiles)),
    ]
    for r in results:
        qs = r["questions"]
        accuracy = ["—" if qs[q]["accuracy"] is None else f"{qs[q]['accuracy']:.2f}" for q in qids]
        briers = [qs[q]["brier"] for q in qids if qs[q]["brier"] is not None]
        f1s = [macro_f1(qs[q]["confusion"]) for q in qids]
        cells = [
            r["runner"],
            *accuracy,
            *["—" if f is None else f"{f:.2f}" for f in f1s],
            f"{statistics.fmean(briers):.3f}" if briers else "—",
            str(sum(qs[q]["invalid"] for q in qids)),
            str(r["errors"]),
            str(r["latency_ms_median"]),
            str(r["latency_ms_p90"]),
            *[result_score(r, p, ref) for p in profiles],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    if profiles:
        lines += [
            "",
            "Scores (accuracy averaged over questions; relative speed is measured against the "
            "runners in this table; `gated` fails a profile's gate):",
        ]
        lines.extend(f"- `{p.name}`: {p.describe()}" for p in profiles)
    for r in results:
        for qid in qids:
            lines.extend(render_confusion(r["runner"], qid, r["questions"][qid]["confusion"]))
    return "\n".join(lines) + "\n"


def render_confusion(runner: str, qid: str, conf: dict[str, Any]) -> list[str]:
    """Markdown confusion matrix for one runner and question.

    Rows are the expected label, columns what the runner answered; the diagonal
    is correct. ``invalid`` is a column for answers outside the allowed values.
    """
    labels = conf["labels"]
    if not any(v["support"] for v in conf["per_label"].values()):
        return []
    show_invalid = any(conf["invalid"].values())
    head = ["expected \\ answered", *labels, *(["invalid"] if show_invalid else []), "recall"]
    lines = [
        "",
        f"## Confusion matrix: {runner} / {qid}",
        "",
        "| " + " | ".join(head) + " |",
        "|" + "---|" * len(head),
    ]
    for t in labels:
        stats = conf["per_label"][t]
        if not stats["support"]:
            continue
        cells = [t, *(str(conf["counts"][t][p]) for p in labels)]
        if show_invalid:
            cells.append(str(conf["invalid"][t]))
        cells.append("—" if stats["recall"] is None else f"{stats['recall']:.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    precision = ["precision"]
    for p in labels:
        value = conf["per_label"][p]["precision"]
        precision.append("—" if value is None else f"{value:.2f}")
    precision.extend([""] * (len(head) - len(precision)))
    lines.append("| " + " | ".join(precision) + " |")
    return lines


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
