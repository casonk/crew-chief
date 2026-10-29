# Task Benchmarks

Speed benchmarks (`scripts/benchmark.py`, `scripts/llamacpp_bench.sh`) say how
fast a model generates. Test-based benchmarks say whether it can fix code.
Most local-model work in the portfolio is a third kind: a **bounded decision**
— route a message, pick a category, flag urgency, rate risk, fill a field from
a fixed set. `crew-chief taskbench` scores models on those decisions.

## Task format

Tasks use the question types of TypeSafe AI's Jev decision model, so a task
file can run unchanged against local models and against Jev:

| Type | Answer | `criteria` |
|---|---|---|
| `choice` | one option name | map of option name → description |
| `score` | one level, 0..n-1 | ordered list, low → high (2–10 levels) |
| `noul` | yes/no (probability of yes) | optional `{"true": ..., "false": ...}` |

A task file (`benchmarks/decisions/*.json`) holds `questions`, `items` (each a
`state` and the `expected` answers), and an optional keyword `baseline`. Task
data is synthetic: never put real messages, receipts, or personal data in a
task file.

```bash
crew-chief taskbench benchmarks/decisions/message-routing.json \
  --runner rules --runner ollama:qwen3:14b --runner llamacpp:qwen3:32b
```

## Dev and held-out splits

Each item may carry `"split": "heldout"`; items without one are `dev`. Fit
keyword rules, prompts and thresholds against `dev` only, then score the fixed
configuration once on `heldout`. `crew-chief taskbench` runs `dev` by default
(`--split heldout` or `--split all` otherwise) and names held-out result files
`taskbench-<task>-heldout-<stamp>`. A state that appears twice in a task file is
rejected, so a dev answer cannot leak into the held-out score.

Suites: `message-routing`, `mail-triage`, `receipt-category` and
`schema-extraction`. The first one's keyword rules were fitted to all of its
original 30 items, so those are `dev` and its 10 newer items are the held-out
split; the other three have 16 dev and 8 held-out items each, with rules written
from the dev items. The gap between a runner's dev and held-out accuracy is the
overfit: the keyword baseline on `receipt-category` scores 1.00 on dev and 0.38 on
held-out category.

## Runners

| Runner | How it answers | Probabilities |
|---|---|---|
| `rules` | keyword rules from the task file | no |
| `ollama:<model>` | one call per item, reply constrained to a JSON schema | no |
| `llamacpp:<model>` | one call per question, reply constrained to one option letter | yes, from token log-probs |
| `systemone:<model>` | local decision model via Ollama's `/v1/systemone` (Nimble, Tev1, Clef) | yes, from the model |
| `jev[:<model>]` | TypeSafe's hosted API (`TYPESAFE_API_KEY`) | yes, calibrated by the vendor |

Metrics: accuracy and invalid answers per question, median and p90 latency per
item, and the multi-class Brier score where probabilities exist (lower is
better; it rewards being confident only when right).

## Decision models and Jev

Jev ([TypeSafe AI](https://typesafe.ai/blog/introducing-system-one-models-and-jev),
launched 2026-09-15) is a "System One" model: it never writes text. It takes a
state and typed questions and returns, for each, a choice, score, or yes/no
with probabilities, trained with reinforcement learning for calibrated
decisions. The vendor reports 70–500 ms per call. It is hosted only — no open
weights, no customer fine-tuning — so in this portfolio it is a **reference
point**, not a backend:

- Run it only on synthetic task data, opt-in, with the key held as a secret.
  It is metered, and its compliance posture is not established.
- Use it to answer "how good can a decision model be on this task?" and to
  calibrate what local options must reach.

### Local decision models (Ollama 0.35+)

Ollama 0.35 added a `/v1/systemone` endpoint modelled on Jev's API, and
decision models that run on it locally: **Clef Flash** and **Clef**
(Cloudflare; Clef also judges images), **Nimble** (Bespoke Labs) and **Tev1**
(Together AI). Ollama reports them with a `decision` capability; they answer
typed questions and are not chat or tool-calling models. The `systemone:<model>`
runner scores them with the same task files.

On message-routing (`results/taskbench-message-routing-20261022-systemone.md`)
Clef Flash answered all three questions in one 120 ms call at 0.97/1.00/0.93
accuracy and the best calibration measured (Brier 0.062), ahead of qwen3:14b
as a chat model (421 ms, no probabilities). This is the local decision-model
path; Jev remains an external reference.

The `llamacpp` runner is the earlier local analogue: a fixed label set, one
constrained token, and a probability per option. First results
(`results/taskbench-message-routing-20261021.md`) show the trade-off: ~65 ms
per question with probabilities, but lower accuracy than a free reply from the
same model, because a single token leaves no room to reason.

## Local path: fine-tuning for explicit output selection

What makes a decision model good is training on the output format itself:
select one option from a closed set, with calibrated probabilities. Locally:

1. Grow the task suites (several tasks, a held-out split per task) so there is
   training data and an honest test set.
2. Fine-tune a small model (LoRA on a 1.7B–4B instruct model, or an encoder
   classifier) to answer with the option token directly, trained with
   log-loss so its probabilities are calibrated.
3. Export to GGUF, serve with llama.cpp, and score it with `taskbench` against
   the base models, the rules baseline, and Jev.
4. Record the winner per task in the serving policy.

See `BACKLOG.md` for the tracked items.
