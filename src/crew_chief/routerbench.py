"""crew_chief.routerbench — can a decision model choose the decision model?

``taskbench`` scores one model at a time. This module asks the next question:
given several candidate decision models, is it worth spending a call to pick
one (or to escalate from a cheap one to a slow one)? A strategy is judged on
both axes at once, because they trade against each other:

- quality: accuracy and macro-F1 of the answer it finally returns, plus the
  confusion matrix behind them
- time to inference: the latency of every call the strategy makes, including
  the router's own

Strategies, all scored on the same held-out items:

- ``single:<m>``    always ask one candidate (the baselines a router must beat)
- ``lookup``        the candidate with the best dev accuracy for the task; free
- ``route:<r>``     a router model picks a candidate from dev-measured profiles
                    written into the options; latency is the router call plus
                    the chosen candidate's call
- ``cascade@<t>``   ask the fastest candidate; if its top probability is below
                    ``t`` ask the next fastest, and so on (the candidate's own
                    probabilities are the prior that decides whether to escalate)
- ``oracle``        the fastest candidate that was right; an unreachable bound

Every candidate runs once on every item. Strategy latency is composed from those
measured per-call times, so a strategy never re-runs a model. Profiles shown to
the router come from ``dev`` items only; strategies are scored on ``heldout``.

Stdlib only.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass
from typing import Any

from crew_chief import scoring
from crew_chief import taskbench as tb
from crew_chief.render import nudge_label

DEFAULT_THRESHOLDS = (0.6, 0.8, 0.95)


class RouteError(ValueError):
    """The benchmark cannot be set up as asked."""


@dataclass(frozen=True)
class Call:
    """One candidate's answer to one item and what it cost."""

    value: str | None
    expected: str
    probabilities: dict[str, float] | None
    ms: float

    @property
    def correct(self) -> bool:
        return self.value == self.expected

    @property
    def confidence(self) -> float | None:
        if not self.probabilities:
            return None
        return max(self.probabilities.values())


@dataclass(frozen=True)
class Outcome:
    """What a strategy finally answered for one item and the total time it took."""

    value: str | None
    expected: str
    ms: float
    detail: str = ""


def model_label(spec: str) -> str:
    """``systemone:tev1`` -> ``tev1``: the name shown to a router as an option."""
    return spec.partition(":")[2] or spec


def item_split(task: tb.Task, index: int) -> str:
    return task.items[index].get("split", "train")  # canonical after load_task: train or test


def collect(task: tb.Task, runner) -> dict[int, Call]:
    """Run a candidate on every item of a single-question task."""
    qid = next(iter(task.questions))
    result = tb.run(task, runner)
    calls = {}
    for row in result["rows"]:
        answer = row.get("answers", {}).get(qid)
        if answer is None:
            continue
        calls[row["item"]] = Call(answer["value"], answer["expected"], answer["p"], row["ms"])
    return calls


# -- profiles and routing ----------------------------------------------------


def dev_profile(task: tb.Task, calls: dict[int, Call]) -> dict[str, float | None]:
    dev = [c for i, c in calls.items() if item_split(task, i) == "train"]
    return {
        "accuracy": sum(c.correct for c in dev) / len(dev) if dev else None,
        "ms": statistics.median(c.ms for c in dev) if dev else None,
    }


def router_task(task: tb.Task, profiles: dict[str, dict[str, float | None]]) -> tb.Task:
    """The one-question task a router answers: pick a candidate for this item."""
    criteria = {}
    for name, prof in profiles.items():
        acc = "unknown" if prof["accuracy"] is None else f"{prof['accuracy']:.2f}"
        ms = "unknown" if prof["ms"] is None else f"{prof['ms']:.0f}"
        criteria[name] = f"{acc} accuracy on this task's dev items, {ms} ms per item"
    question = tb.Question(
        "model",
        "choice",
        "Which model should sort this item? Prefer higher accuracy; among models that "
        "are about equally accurate, prefer the faster one.",
        criteria,
    )
    return tb.Task("model-router", "Pick a candidate model", {"model": question}, [])


def router_state(task: tb.Task, item_state: str) -> str:
    q = next(iter(task.questions.values()))
    return f"Task: {task.name}\nQuestion: {q.instructions}\nItem: {item_state}"


def lookup_choice(profiles: dict[str, dict[str, float | None]]) -> str:
    """Best dev accuracy, ties to the faster model; the no-call alternative to a router."""
    return max(
        profiles,
        key=lambda m: (profiles[m]["accuracy"] or 0.0, -(profiles[m]["ms"] or math.inf)),
    )


# -- strategies --------------------------------------------------------------


def _single(calls: dict[str, dict[int, Call]], model: str, items: list[int]) -> list[Outcome]:
    return [
        Outcome(calls[model][i].value, calls[model][i].expected, calls[model][i].ms) for i in items
    ]


def _oracle(calls: dict[str, dict[int, Call]], items: list[int]) -> list[Outcome]:
    outcomes = []
    for i in items:
        ranked = sorted(calls, key=lambda m: calls[m][i].ms)
        right = [m for m in ranked if calls[m][i].correct]
        pick = (right or ranked)[0]
        c = calls[pick][i]
        outcomes.append(Outcome(c.value, c.expected, c.ms, pick if right else "none"))
    return outcomes


def _cascade(
    calls: dict[str, dict[int, Call]], order: list[str], threshold: float, items: list[int]
) -> list[Outcome]:
    outcomes = []
    for i in items:
        total, last = 0.0, None
        for position, model in enumerate(order):
            last = calls[model][i]
            total += last.ms
            confident = last.value is not None and (last.confidence or 0.0) >= threshold
            if confident or position == len(order) - 1:
                outcomes.append(Outcome(last.value, last.expected, total, f"{position + 1} calls"))
                break
    return outcomes


def _routed(
    calls: dict[str, dict[int, Call]],
    picks: dict[int, tuple[str | None, float]],
    fallback: str,
    items: list[int],
) -> list[Outcome]:
    outcomes = []
    for i in items:
        pick, router_ms = picks[i]
        model = pick if pick in calls else fallback
        c = calls[model][i]
        detail = model if pick in calls else f"{model} (invalid pick)"
        outcomes.append(Outcome(c.value, c.expected, router_ms + c.ms, detail))
    return outcomes


def summarize(
    labels_by_task: dict[str, list[str]], outcomes: dict[str, list[Outcome]]
) -> dict[str, Any]:
    """Quality and latency of one strategy over every task's held-out items."""
    times, correct, total = [], 0, 0
    per_task, confusions, f1s = {}, {}, []
    for task_name, rows in outcomes.items():
        labels = labels_by_task[task_name]
        counts = {t: {p: 0 for p in labels} for t in labels}
        missed = {t: 0 for t in labels}
        hit = 0
        for o in rows:
            times.append(o.ms)
            if o.value is None:
                missed[o.expected] += 1
            else:
                counts[o.expected][o.value] += 1
                hit += o.value == o.expected
        conf = tb.confusion(labels, counts, missed)
        f1 = tb.macro_f1(conf)
        if f1 is not None:
            f1s.append(f1)
        per_task[task_name] = {
            "n": len(rows),
            "accuracy": round(hit / len(rows), 3) if rows else None,
            "macro_f1": None if f1 is None else round(f1, 3),
            "ms_mean": round(statistics.fmean(o.ms for o in rows), 1) if rows else None,
        }
        confusions[task_name] = conf
        correct += hit
        total += len(rows)
    return {
        "n": total,
        "accuracy": round(correct / total, 3) if total else None,
        "macro_f1": round(statistics.fmean(f1s), 3) if f1s else None,
        "ms_mean": round(statistics.fmean(times), 1) if times else None,
        "ms_median": round(statistics.median(times), 1) if times else None,
        "ms_p90": round(tb._p90(times), 1) if times else None,
        "per_task": per_task,
        "confusion": confusions,
    }


def pareto(strategies: dict[str, dict[str, Any]]) -> set[str]:
    """Achievable strategies no other beats on both accuracy (higher) and mean latency (lower).

    The oracle is a bound, not something to deploy, so it neither joins the front
    nor knocks a real strategy off it.
    """
    strategies = {n: s for n, s in strategies.items() if n != "oracle"}
    front = set()
    for name, s in strategies.items():
        dominated = any(
            o["accuracy"] >= s["accuracy"]
            and o["ms_mean"] <= s["ms_mean"]
            and (o["accuracy"] > s["accuracy"] or o["ms_mean"] < s["ms_mean"])
            for other, o in strategies.items()
            if other != name
        )
        if not dominated:
            front.add(name)
    return front


def score_strategies(
    strategies: dict[str, dict[str, Any]], profiles: list[scoring.Profile]
) -> dict[str, Any]:
    """Rank the achievable strategies under each profile, with a weight sensitivity sweep.

    The oracle is left out: it cannot be deployed, so it must not take a rank.
    """
    entries = {
        name: (s["accuracy"], s["ms_mean"], s["ms_p90"])
        for name, s in strategies.items()
        if name != "oracle" and s["accuracy"] is not None
    }
    return {
        p.name: {
            "profile": p.describe(),
            "ranking": scoring.rank(p, entries),
            "sensitivity": {
                f"{w:g}": names for w, names in scoring.sensitivity(p, entries).items()
            },
        }
        for p in profiles
    }


# -- benchmark ---------------------------------------------------------------


def run_benchmark(
    tasks: list[tb.Task],
    candidates: list[str],
    router,
    *,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    clock=time.perf_counter,
    profiles: list[scoring.Profile] | None = None,
) -> dict[str, Any]:
    """Score single models, lookup, a router, cascades and an oracle on held-out items."""
    names = [model_label(spec) for spec in candidates]
    if len(set(names)) != len(names) or len(names) < 2:
        raise RouteError("routing needs at least two candidates with distinct model names")
    for task in tasks:
        if len(task.questions) != 1:
            raise RouteError(f"{task.name}: routing benchmarks take single-question tasks")

    calls: dict[str, dict[str, dict[int, Call]]] = {n: {} for n in names}
    for task in tasks:
        for spec, name in zip(candidates, names, strict=True):
            calls[name][task.name] = collect(task, tb.make_runner(spec, task))

    labels_by_task = {t.name: next(iter(t.questions.values())).labels for t in tasks}
    outcomes: dict[str, dict[str, list[Outcome]]] = {}
    picks_log: dict[str, dict[int, dict[str, Any]]] = {}
    expected_best: list[tuple[str, str | None]] = []
    profiles_by_task: dict[str, dict] = {}
    dropped = 0

    def add(strategy: str, task_name: str, rows: list[Outcome]) -> None:
        outcomes.setdefault(strategy, {})[task_name] = rows

    for task in tasks:
        per_model = {n: calls[n][task.name] for n in names}
        # Pair the comparison: an item counts only if every candidate answered it.
        common = set.intersection(*(set(c) for c in per_model.values()))
        dropped += len(task.items) - len(common)
        heldout = sorted(i for i in common if item_split(task, i) == "test")
        if not heldout:
            raise RouteError(f"{task.name}: no test items answered by every candidate")
        dev_profiles = {n: dev_profile(task, per_model[n]) for n in names}
        profiles_by_task[task.name] = dev_profiles
        fallback = lookup_choice(dev_profiles)
        order = sorted(names, key=lambda n: dev_profiles[n]["ms"] or math.inf)

        for n in names:
            add(f"single:{n}", task.name, _single(per_model, n, heldout))
        add("lookup", task.name, _single(per_model, fallback, heldout))
        add("oracle", task.name, _oracle(per_model, heldout))
        for t in thresholds:
            add(f"cascade@{t:g}", task.name, _cascade(per_model, order, t, heldout))

        rtask = router_task(task, dev_profiles)
        picks: dict[int, tuple[str | None, float]] = {}
        log: dict[int, dict[str, Any]] = {}
        for i in heldout:
            started = clock()
            try:
                answer = router.answer(rtask, router_state(task, task.items[i]["state"]))["model"]
            except (OSError, KeyError, ValueError):
                answer = tb.Answer(None)
            elapsed = (clock() - started) * 1000
            picks[i] = (answer.value, elapsed)
            log[i] = {"pick": answer.value, "ms": round(elapsed, 2), "p": answer.probabilities}
            ranked = sorted(names, key=lambda n: per_model[n][i].ms)
            right = [n for n in ranked if per_model[n][i].correct]
            expected_best.append((right[0] if right else "none", answer.value))
        add(f"route:{router.name}", task.name, _routed(per_model, picks, fallback, heldout))
        picks_log[task.name] = log

    strategies = {name: summarize(labels_by_task, rows) for name, rows in outcomes.items()}
    labels = [*names, "none"]
    counts = {t: {p: 0 for p in [*labels, "invalid"]} for t in labels}
    for best, pick in expected_best:
        counts[best][pick if pick in names else "invalid"] += 1
    return {
        "candidates": names,
        "router": router.name,
        "tasks": [t.name for t in tasks],
        "dropped_items": dropped,
        "profiles": profiles_by_task,
        "strategies": strategies,
        "pareto": sorted(pareto(strategies)),
        "scores": score_strategies(strategies, profiles or []),
        "router_picks": counts,
        "router_log": picks_log,
    }


# -- reports -----------------------------------------------------------------


def _fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(result: dict[str, Any], stamp: str, chart: str | None = None) -> str:
    strategies, front = result["strategies"], set(result["pareto"])
    ordered = sorted(strategies, key=lambda n: strategies[n]["ms_mean"])
    lines = [
        f"# Router benchmark ({stamp})",
        "",
        f"Router `{result['router']}` choosing among {', '.join(result['candidates'])} on "
        f"{', '.join(result['tasks'])}. Scored on held-out items only; profiles shown to the",
        "router come from dev items. Latency is composed from each call's measured time: a",
        "routed item costs the router call plus the chosen model's call, a cascade item costs",
        "every call it made. `*` marks strategies no other beats on both accuracy and mean latency.",
        "",
        "| Strategy | n | accuracy | macro F1 | mean ms | median ms | p90 ms | |"
        + "".join(f" score: {name} |" for name in result.get("scores", {})),
        "|---|---|---|---|---|---|---|---|" + "---|" * len(result.get("scores", {})),
    ]
    for name in ordered:
        s = strategies[name]
        lines.append(
            f"| {name} | {s['n']} | {_fmt(s['accuracy'])} | {_fmt(s['macro_f1'])} | "
            f"{_fmt(s['ms_mean'], 1)} | {_fmt(s['ms_median'], 1)} | {_fmt(s['ms_p90'], 1)} | "
            f"{'*' if name in front else ''} |"
            + "".join(
                f" {_score_cell(result['scores'][p], name)} |" for p in result.get("scores", {})
            )
        )
    if chart:
        lines += ["", f"![accuracy against mean latency]({chart})"]
    if result["dropped_items"]:
        lines += ["", f"{result['dropped_items']} items were dropped (a candidate errored)."]

    lines += ["", "## Accuracy by task", "", "| Strategy | " + " | ".join(result["tasks"]) + " |"]
    lines.append("|" + "---|" * (len(result["tasks"]) + 1))
    for name in ordered:
        cells = [_fmt(strategies[name]["per_task"][t]["accuracy"]) for t in result["tasks"]]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    for pname, block in result.get("scores", {}).items():
        lines.extend(_render_scores(pname, block))

    counts = result["router_picks"]
    labels = [*result["candidates"], "none"]
    show_invalid = any(counts[t]["invalid"] for t in labels)
    head = [
        "fastest correct \\ router picked",
        *result["candidates"],
        *(["invalid"] if show_invalid else []),
    ]
    lines += [
        "",
        "## Router picks against the fastest correct candidate",
        "",
        "Rows: the fastest candidate that answered the item correctly (`none`: nobody did).",
        "Columns: the candidate the router chose. A router that works puts its weight on",
        "the diagonal; picking a slower correct model is cheaper than missing, but not free.",
        "",
        "| " + " | ".join(head) + " |",
        "|" + "---|" * len(head),
    ]
    for t in labels:
        row = [str(counts[t][p]) for p in head[1:]]
        if sum(counts[t].values()):
            lines.append("| " + " | ".join([t, *row]) + " |")

    routed = f"route:{result['router']}"
    for task_name, conf in strategies[routed]["confusion"].items():
        lines.extend(tb.render_confusion(routed, task_name, conf))
    return "\n".join(lines) + "\n"


def _score_cell(block: dict[str, Any], name: str) -> str:
    for row in block["ranking"]:
        if row["name"] == name:
            return "gated" if row["score"] is None else f"{row['score']:.3f}"
    return "—"  # the oracle is not ranked


def _render_scores(name: str, block: dict[str, Any]) -> list[str]:
    ranking = block["ranking"]
    lines = [
        "",
        f"## Scores: {name}",
        "",
        block["profile"] + ".",
        "Tied rows are within the profile's tie margin of the best score; treat them as",
        "equal. The oracle is not ranked.",
        "",
        "| Rank | Strategy | score | accuracy | speed | note |",
        "|---|---|---|---|---|---|",
    ]
    for rank_, row in enumerate(ranking, 1):
        note = (
            f"gated: {row['gate']}" if row["gate"] else ("tied for the lead" if row["tied"] else "")
        )
        score_ = "—" if row["score"] is None else f"{row['score']:.3f}"
        lines.append(
            f"| {rank_} | {row['name']} | {score_} | {row['quality']:.3f} | {row['speed']:.3f} | {note} |"
        )
    lines += [
        "",
        "Who leads as the weight on accuracy changes (speed gets the rest):",
        "",
        "| accuracy weight | tied for the lead |",
        "|---|---|",
    ]
    lines.extend(f"| {w} | {', '.join(names)} |" for w, names in block["sensitivity"].items())
    return lines


def render_svg(result: dict[str, Any]) -> str:
    """Accuracy (y) against mean latency per item (x, log scale), one dot per strategy."""
    strategies, front = result["strategies"], set(result["pareto"])
    width, height, left, right, top, bottom = 760, 420, 56, 150, 20, 48
    xs = [s["ms_mean"] for s in strategies.values()]
    ys = [s["accuracy"] for s in strategies.values()]
    lo, hi = math.log10(max(min(xs) * 0.8, 1)), math.log10(max(xs) * 1.25)
    y_lo = max(0.0, math.floor((min(ys) - 0.05) * 20) / 20)

    def px(ms: float) -> float:
        return left + (math.log10(ms) - lo) / (hi - lo) * (width - left - right)

    def py(acc: float) -> float:
        return top + (1 - (acc - y_lo) / (1 - y_lo)) * (height - top - bottom)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'data-layout="2" font-family="sans-serif" font-size="11" fill="currentColor" '
        'style="color:var(--text,#e2e4f0)">',
        f'<rect width="{width}" height="{height}" style="fill:var(--surface,#1a1d27)"/>',
        f'<rect x="{left}" y="{top}" width="{width - left - right}" height="{height - top - bottom}" '
        'fill="none" style="stroke:var(--border,#2e3250)"/>',
        f'<text x="{left + (width - left - right) / 2}" y="{height - 10}" text-anchor="middle">'
        "mean ms per item (log scale; lower is faster)</text>",
        f'<text x="14" y="{top + (height - top - bottom) / 2}" text-anchor="middle" '
        f'transform="rotate(-90 14 {top + (height - top - bottom) / 2})">accuracy (higher is better)</text>',
    ]
    steps = round((1 - y_lo) / 0.05)
    for k in range(steps + 1):
        acc = y_lo + k * 0.05
        out.append(f'<text x="{left - 6}" y="{py(acc) + 4}" text-anchor="end">{acc:.2f}</text>')
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{py(acc)}" y2="{py(acc)}" '
            'style="stroke:var(--border,#2e3250);stroke-opacity:0.5"/>'
        )
    for tick in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000):
        if lo <= math.log10(tick) <= hi:
            out.append(
                f'<text x="{px(tick)}" y="{height - bottom + 16}" text-anchor="middle">{tick}</text>'
            )
    placed: list[tuple[float, float, float]] = []
    for name, s in sorted(strategies.items(), key=lambda item: item[1]["ms_mean"]):
        x, y = px(s["ms_mean"]), py(s["accuracy"])
        dash = ' stroke-dasharray="2 2"' if name == "oracle" else ""
        colour = "var(--purple,#a06fff)" if name == "oracle" else "var(--accent,#5b7fff)"
        fill = colour if name in front else "none"
        radius = 5 if name in front else 4
        out.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" '
            f'style="fill:{fill};stroke:{colour}" stroke-width="1.5"{dash}/>'
        )
        label = name.replace("route:", "route ")
        label_y = nudge_label(placed, x + 8, x + 8 + 6.2 * len(label), y + 4)
        out.append(f'<text x="{x + 8:.1f}" y="{label_y:.1f}">{label}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2) + "\n"
