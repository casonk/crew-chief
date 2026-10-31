# Choosing and selecting decision models

How crew-chief decides which local model should make a bounded decision (sort a
list item into its category, route a message, fill a field from a fixed set),
what the tests measure, what they found on 2026-10-30, and how to add models and
use cases. Commands and file formats are in
[task-benchmarks.md](task-benchmarks.md); evidence is under `results/`.

## What is being decided

Two questions, kept separate:

1. **Which model answers best?** A fixed set of categories, one item, one answer.
2. **Is it worth choosing the model per item?** A second model (or the first
   model's own confidence) picks who answers. That costs a call, so it must earn
   its time back.

Both are judged on **quality and time to inference together**. A model that is
two points more accurate but ten times slower is not better for an interactive
Clockwork action, and a router that saves nothing but adds a call is worse than
no router.

## Test strategy

### Suites

One suite per use case, in `benchmarks/decisions/`. Today the use cases are the
seven Clockwork lists (`clockwork-*.json`: groceries, shopping, watch, listen,
read, todo, invest) plus `message-routing`, `mail-triage`, `receipt-category` and
`schema-extraction`. Each suite is one or more typed questions (`choice`,
`score`, `noul`) and items with expected answers.

- **Synthetic only.** Items are generic names or well-known public titles, never
  entries from a real list, message or receipt.
- **Every label appears in both splits.** A suite that never shows a label in
  `heldout` cannot reveal a model that never answers it.
- **Dev and held-out.** Keyword rules, prompts, router profiles and thresholds
  are fitted on `dev`; a fixed configuration is scored once on `heldout`. A state
  that appears twice in a suite is rejected so a dev answer cannot leak.

### Prompts

Every question and its allowed values come **before** the input. Chat runners get
them as a system message; `llamacpp` puts the options ahead of `INPUT`. On the
watch suite this moved `qwen2.5-coder:7b` from 0.45 to 0.80, so a surprising
score should send you to the prompt before it sends you to the model.

### Metrics

| Metric | Meaning |
|---|---|
| accuracy | share of items answered correctly |
| confusion matrix | rows are the expected label, columns the answer; shows which pairs get mixed up |
| precision / recall / F1 per label, macro-F1 | whether errors are spread out or concentrated; macro-F1 weights every label equally |
| invalid | answers outside the allowed values (a column of the matrix) |
| Brier | calibration of the reported probabilities (lower is better); only runners that report probabilities have one |
| latency | median, p90 and mean ms per item, measured per call |

Read the matrix before the accuracy, and read accuracy next to latency.

### Aggregate score

For ranking many models and suites, reports add one score per **scoring
profile** (`config/scoring-profiles.toml`; the code is `src/crew_chief/scoring.py`):

```
score = accuracy_weight * accuracy + (1 - accuracy_weight) * speed
speed = (1 - relative_weight) * absolute + relative_weight * relative
        (each taken on the mean and on the p90, blended by tail_weight)
absolute = 1 at or under target_ms, 0 at or over ceiling_ms, log-linear between
relative = 1 for the fastest performer in the comparison, 0 for the slowest,
           log-linear between
```

The absolute curve keeps a score meaning the same thing from run to run; the
relative curve spreads the models actually on the table, so five models that are
all under the target are still told apart. `relative_weight` is the global factor
that blends them, and both profiles use 0.5. The comparison is every performer in
the same report: the runners of one `taskbench` suite, or the strategies of one
`routebench` run (the oracle and zero-latency rule baselines set no range). Gates
stay absolute, so a model cannot pass by being the least bad.

| Profile | For | accuracy / speed | relative share of speed | full speed credit | no speed credit | gates |
|---|---|---|---|---|---|---|
| `interactive` | a person waits (a Clockwork action, a chat reply) | 0.7 / 0.3 | 0.5 | <= 100 ms | >= 1,000 ms | accuracy >= 0.80, p90 <= 1,500 ms |
| `batch` | nobody waits (a nightly recategorize) | 0.95 / 0.05 | 0.5 | <= 500 ms | >= 10,000 ms | accuracy >= 0.85 |

The weights are a product decision, not a measurement, so the score is a ranking
aid and never a verdict:

- A model that misses a gate is shown as `gated` and ranks below every model
  that passes, so speed cannot buy back an unacceptable miss.
- Scores within the profile's `tie_margin` of the best are marked **tied for the
  lead**. Treat them as equal; the margin is about one held-out item.
- Every ranking comes with a sensitivity table: who leads at accuracy weights
  from 0.5 to 0.95. A lead that flips inside that range is not a lead.
- The oracle is never ranked, and the Pareto front, the confusion matrices and the
  raw accuracy and latency stay in the report.
- Change a profile only in a pull request that says why. Every ranking moves with
  it, so a result file records which profile text produced it.

`taskbench` adds a `score: <profile>` column per profile (accuracy averaged over
the task's questions); `routebench` adds the columns plus a ranking and
sensitivity section per profile. `--profiles PATH` uses another file and
`--no-score` omits the columns.

### The bench interface (`benchui`)

`crew-chief benchui` serves a page on loopback port 8766. The shared Caddy
(wiring-harness, client certificate required) puts it at
`https://bench.crew-chief.internal/`; it also serves the shared `results/` folder
at the site root (`/latest.html`, `/results/`), as the static site did before it.

- **Run it:** `scripts/install_benchui_systemd.sh` installs and starts the user
  unit `crew-chief-benchui`, which accepts the Caddy hostname through
  `CREW_CHIEF_BENCH_HOSTS`. The wiring-harness registry entry
  (`crew-chief-bench`) is a plain `port = 8766` proxy; apply it with
  `scripts/apply_site_changes.sh --skip-mtls --skip-dnsmasq --skip-dns-check`.

- **Profiles:** sliders for every profile field, saved under
  `~/.local/state/crew-chief/bench/profiles.toml` (seeded from the tracked
  defaults; `CREW_CHIEF_BENCH_STATE` moves it). While you drag, the server
  rescores a chosen result and the ranking, the accuracy and speed points and the
  sensitivity table move with it. Saved profiles are what new jobs score with.
  Promote one to `config/scoring-profiles.toml` in a pull request to make it a
  tracked default.
- **New run:** pick `taskbench` or `routebench`, the suites, the runners or
  candidates (the System One models and whatever Ollama has pulled), the split,
  and optionally "private", which writes to the state directory instead of the
  shared `results/` folder.
- **Jobs:** a queue that runs one job at a time (concurrent runs on one GPU would
  distort each other's latency), with status, progress, a log, cancel, and the GPU
  memory in use at start.
- **Results:** every `taskbench` and `routebench` result, linked both ways to the
  job that wrote it; "Score" opens any result under the profile being edited.

The interface only builds command lines from known suites and a fixed runner
syntax, never runs a shell, rejects non-loopback hosts and cross-origin posts,
and stops its running job when it exits.

### Model comparison (`taskbench`)

Run each candidate on the same items with `crew-chief taskbench <suite>
--runner ...`. Runners: `rules` (keyword floor), `ollama:<m>`, `llamacpp:<m>`,
`systemone:<m>` and `jev`. Include `rules` so a model has a floor to beat.

### Selection (`routebench`)

`crew-chief routebench <suites...>` runs every candidate once on every item, then
scores strategies on the **held-out** items using the measured per-call results:

| Strategy | What it does | Latency |
|---|---|---|
| `single:<m>` | always ask one candidate | that call |
| `lookup` | the candidate with the best dev accuracy for the task | that call |
| `route:<r>` | a router picks a candidate; its options carry each candidate's dev accuracy and median latency | router call + chosen call |
| `cascade@<t>` | ask the fastest candidate; escalate to the next if its top probability is below `t` | every call made |
| `oracle` | the fastest candidate that was right | that call; a bound, not deployable |

Rules that keep the comparison honest:

- All strategies see the same items, and an item counts only if every candidate
  answered it.
- Router profiles come from dev items; scoring uses held-out items.
- The oracle is shown but never joins the Pareto front.
- A router is judged against the best `single:` and against `lookup`, not
  against nothing. It earns its place only if it sits on the front above both.
- Run on an idle GPU under an exclusive ECU lease, and record how many runs
  each number comes from.

## Results (2026-10-30)

Evidence: `results/taskbench-clockwork-sorting-20261030.md` (all items, five
runners) and `results/routebench-20261030-064003.{md,svg,json}` (held-out items,
four candidates). One run each, idle GPU.

### Models

Unweighted mean accuracy over the seven Clockwork suites (228 items), median
latency per item across suites:

| Model | Kind | mean accuracy | median ms per item |
|---|---|---|---|
| `clef-flash` | System One | 0.96 | 68-139 |
| `clef` | System One | 0.96 | 558-1116 |
| `nimble` | System One | 0.95 | 74-161 |
| `tev1` | System One | 0.93 | 49-135 |
| `qwen2.5-coder:7b` | chat, JSON-constrained | 0.91 | 122-139 |

The System One models led on groceries, watch and todo. The chat model led on
invest and shopping (1.00 on both), so no model wins every list. `clef` is five
to ten times slower than `clef-flash` for no accuracy gain. `tev1` has the best
calibration on groceries (Brier 0.003); `nimble` on read and todo.

### Selection

88 held-out items, four System One candidates, `clef-flash` as router:

| Strategy | accuracy | macro F1 | mean ms | p90 ms | on front |
|---|---|---|---|---|---|
| single `tev1` | 0.91 | 0.87 | 71 | 105 | yes |
| single `clef-flash` | 0.94 | 0.92 | 98 | 139 | yes |
| cascade, escalate below 0.6 | 0.93 | 0.92 | 99 | 107 | |
| single `nimble` | 0.92 | 0.90 | 112 | 160 | |
| cascade, below 0.8 | 0.94 | 0.93 | 144 | 220 | |
| lookup | 0.90 | 0.86 | 195 | 1132 | |
| cascade, below 0.95 | 0.94 | 0.92 | 279 | 1295 | |
| route (`clef-flash` picks) | 0.94 | 0.92 | 322 | 250 | |
| single `clef` | 0.94 | 0.92 | 873 | 1377 | |
| oracle (bound) | 0.95 | 0.94 | 78 | 105 | |

- Routing matched asking `clef-flash` directly on accuracy at 3.3 times the
  latency. The router's own call is about 90 ms typically but averaged 211 ms.
- The router picked `clef-flash` for 65 of 88 items, `nimble` 18 times, `tev1`
  3 times and `clef` twice, while `tev1` was the fastest correct model for 80.
  It largely ignored the latency profiles, and may favor itself.
- The cascade bought nothing: at 0.6 it costs the same as `clef-flash` alone and
  is one point less accurate.
- `lookup` picks `clef` for tasks where it leads on dev, which makes its p90
  1.1 s.
- The oracle gains about four points over `tev1` at similar speed, so these four
  models leave little for a selector to win.

Scores for the same strategies (full ranking and sensitivity in the result file):

| Strategy | `interactive` | `batch` |
|---|---|---|
| cascade, escalate below 0.6 | **0.937** (tied) | 0.932 |
| single `tev1` | **0.935** (tied) | 0.914 |
| single `clef-flash` | **0.935** (tied) | **0.943** (lead) |
| single `nimble` | 0.903 | 0.919 |
| cascade, below 0.8 | 0.886 | **0.939** (tied) |
| route (`clef-flash` picks) | 0.810 | 0.931 |
| lookup | 0.769 | 0.893 |
| cascade, below 0.95 | 0.767 | 0.932 |
| single `clef` | 0.666 | 0.916 |

Speed is half relative (against these nine strategies) and half absolute. For
`interactive`, `cascade@0.6`, `tev1` and `clef-flash` are tied for the lead
(within 0.02); routing and `clef` fall behind because of latency. For `batch`,
`clef-flash` leads, tied only with `cascade@0.8`: with speed worth 5% and half of
it relative, accuracy decides, and routing trails because it pays a second call
for no accuracy gain.

## Backlog triage: sorting an entry into a group and a repository

`benchmarks/decisions/backlog-triage.json` (91 synthetic entries, 12 stand-in repositories with one-line
descriptions plus `unknown`, 6 groups plus `unknown`) models Clockwork's To Code form: a new entry arrives with
no group or repository and a decision model must pick both or admit it does not know. Results on held-out
entries (`results/backlog-triage-gating-20261031.md`, raw runs beside it):

| Model | repo accuracy | group accuracy | median ms per entry |
|---|---|---|---|
| `clef` | 0.82 | **0.74** | 897 |
| `clef-flash` | **0.82** | 0.54 | 189 |
| `nimble` | 0.74 | 0.49 | 211 |
| `tev1` | 0.51 | 0.28 | 140 |
| `qwen2.5-coder:7b` (chat) | 0.46 | 0.31 | 167 |

- **The repository is a good fit for a decision model** when each repository comes with a short description.
  `clef-flash` matches `clef` at a fifth of the latency. Gated at confidence 0.6 it answers 74% of entries and is
  wrong on 8%; the rest become `unknown`.
- **The group is the hard part.** Only `clef` is usable, and only gated: at 0.6 it answers 59% and is wrong on
  8%. The groups overlap (a security fix is also a fix), so expect `unknown` often, or a stronger model later.
- Clockwork's auto-sort uses `clef-flash` for the repository and `clef` for the group at 0.6, and files
  anything unsure as `unknown` (PR in Clockwork).

Limits: the keyword baseline scores 0.97 on groups and 0.82 on repositories, higher than every model. The
entries share vocabulary (I wrote them and the rules together), so keyword rules look better here than they
would on real, messier entries; treat the baseline as an upper bound, not a floor. Real repository names are not
self-describing, so the result assumes Clockwork supplies each repository's description (it reads
`.github/repository.toml`). Single run, 39 held-out entries: a point is one entry.

## Recommendation

For sorting Clockwork list items into categories:

1. **Use `clef-flash` as the default decision model** (0.94 held-out, 98 ms mean,
   139 ms p90 on a router-free path).
2. **Use `tev1` where latency matters more than three points** (0.91, 71 ms).
3. **Do not route among System One models.** On these tasks selection cost more
   than it saved: under `interactive` routing scores 0.810 against 0.935 for
   `clef-flash` alone. A cascade from `tev1` at a 0.6 threshold ties
   `clef-flash` on score (0.937 against 0.935) with a better p90 (107 against
   139 ms), but it adds a moving part for no accuracy, so it is not worth it
   unless tail latency becomes the constraint.
4. **Avoid `clef` for interactive use**; use it only where its better calibration
   matters and 0.6-1.1 s per item is acceptable.
5. **Do not put `lookup` on dev accuracy in front of models with very different
   latencies**; it chooses the slow model whenever it leads by an item.
6. **Treat the chat model as a second tier, not the default.** `qwen2.5-coder:7b`
   led on invest and shopping, so a cascade from a decision model to a chat
   model is the selection design still worth testing (BACKLOG).

This is advisory, from one run on 88 held-out items. It is not governed policy:
a `[tasks.*]` entry in `config/serving-policy.toml` needs the larger held-out
set tracked in BACKLOG first.

### Limits of these results

- Small samples: each suite has 20-60 items, so a few points are one item. A
  repeated run of the same prompt moved some scores by up to 5 points.
- One router tried, and only System One candidates. A different router, or a
  chat-model candidate, can change the answer.
- Item names are short and generic. Real list entries (typos, brand names,
  mixed languages) are harder; the suites measure relative, not absolute, quality.
- Scores depend on the profile weights and on the speed curve's target and
  ceiling. At `interactive`, `clef-flash` and `tev1` swap the lead around an
  accuracy weight between 0.7 and 0.8; the ties and the sensitivity table show that, a single
  rank does not.
- Latency is Ollama on one RTX 3090, per-item and sequential. It does not
  measure throughput under concurrent load.

## Adding models

1. Pull or install the model, then give it a serving-policy entry (`unreviewed`
   is enough to start; see [serving-policy.md](serving-policy.md)).
2. Run it with the right runner (`ollama:<m>` for a chat model, `systemone:<m>`
   for a decision model) on **every** existing decision suite, with `rules`
   alongside, on an idle GPU. Include held-out items (`--split all`).
3. Add it as a `--candidate` to `routebench` and compare it with the current best
   `single:` on the front.
4. Check the score under each profile and the sensitivity table, not just the
   rank.
5. Commit the result files under `results/` and update the Results and
   Recommendation sections above. Only then change a policy entry's status.

A model that is better on one suite and worse on another is a finding, not a
tie: record both and say which use case each fits.

## Adding use cases

1. Write `benchmarks/decisions/<name>.json` with `questions`, `items` and a
   `baseline`. For a list, use the list's real categories and take them from the
   code that uses them (for Clockwork, the category lists in `web/app.py`), so the
   benchmark keeps testing what production sends.
2. Cover every label in both `dev` and `heldout`; write baseline rules from `dev`
   only. Keep items synthetic or public.
3. Keep it to a single question if you want `routebench` to cover it
   (`routebench` rejects multi-question suites).
4. Run the rules baseline first: a baseline near 1.00 on `dev` and low on
   `heldout` shows the split works.
5. Add a loader check in `tests/test_taskbench.py`, list the suite in
   [task-benchmarks.md](task-benchmarks.md), and rerun the model comparison.
6. If the source list changes (a category added), update the suite in the same
   change.

## Adding or changing a scoring profile

Add a `[profiles.<name>]` table to `config/scoring-profiles.toml` with
`accuracy_weight`, `target_ms` and `ceiling_ms`, and optionally `tail_weight`,
`min_accuracy`, `max_p90_ms` and `tie_margin`. Name the use case it stands for in
`description`, pick the target from what the caller actually waits for, and set
gates for what is unacceptable rather than for what is merely worse. The loader
rejects out-of-range values (`tests/test_scoring.py`). New or changed profiles
need a pull request, since every ranking moves with them.

## Adding selection strategies

Add a function in `src/crew_chief/routerbench.py` that returns one `Outcome`
(`value`, `expected`, `ms`) per held-out item from the stored per-candidate calls,
register it in `run_benchmark`, and add an offline test in
`tests/test_routerbench.py` with hand-computed accuracy and latency. A strategy
must account for every call it makes in `ms`.

## Reproducing

```bash
# model comparison on every Clockwork suite, with the keyword floor
for t in benchmarks/decisions/clockwork-*.json; do
  crew-chief taskbench "$t" --split all --runner rules \
    --runner systemone:clef-flash --runner systemone:clef \
    --runner systemone:nimble --runner systemone:tev1 \
    --runner ollama:qwen2.5-coder:7b
done

# selection strategies
crew-chief routebench benchmarks/decisions/clockwork-*.json \
  --router systemone:clef-flash
```

Write sensitive trials elsewhere with `--out`: everything in `results/` is
served to everyone with access to the benchmark site.
