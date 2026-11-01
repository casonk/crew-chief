# Decision models under the standard train/test protocol (2026-11-01)

Protocol: every prompt carries the whole train split as worked examples (System One models: in front
of the input, inside `state`, which measured better than the question instructions); only the test
split is scored; nothing from test is ever shown. All 12 decision suites, one run each, on an idle GPU.
Per-suite files: `taskbench-<suite>-test-20261101-*.md` here (the 0.85 MB backlog-triage JSON is not
committed; it reproduces from the suite).

Mean accuracy over each suite's questions (test split):

| Suite | rules | bayes | clef-flash | clef | nimble | tev1 |
|---|---|---|---|---|---|---|
| backlog-triage | 0.72 | 0.19 | 0.82 | **0.90** | 0.82 | 0.70 |
| clockwork-grocery-type | 0.42 | 0.17 | 1.00 | 1.00 | 1.00 | 1.00 |
| clockwork-invest-category | 0.17 | 0.42 | 0.83 | **1.00** | 0.92 | **1.00** |
| clockwork-listen-category | 0.40 | 0.40 | 1.00 | 1.00 | 1.00 | 1.00 |
| clockwork-read-category | 0.25 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 |
| clockwork-shopping-type | 0.19 | 0.19 | 0.94 | **1.00** | 0.94 | **1.00** |
| clockwork-todo-category | 0.30 | 0.40 | 1.00 | 1.00 | 1.00 | 1.00 |
| clockwork-watch-category | 0.25 | 0.25 | 1.00 | 1.00 | 1.00 | 1.00 |
| mail-triage | 0.62 | 0.71 | 0.92 | **0.96** | 0.83 | 0.83 |
| message-routing | 0.90 | 0.83 | **1.00** | 0.97 | 0.90 | **1.00** |
| receipt-category | 0.56 | 0.56 | 1.00 | 1.00 | 1.00 | 1.00 |
| schema-extraction | **1.00** | 0.83 | 0.96 | **1.00** | **1.00** | **1.00** |
| **mean** | 0.48 | 0.45 | 0.96 | **0.99** | 0.95 | 0.96 |
| median ms/item (median of suites) | ~0 | ~0 | 248 | 1660 | 274 | 162 |

Reading it:

- The four System One models are within a few points of each other except on the hard 27-way
  `backlog-triage` (0.70-0.90) and on `mail-triage`; `clef` is the most accurate but about 7x slower
  than `clef-flash` and `tev1`. `tev1` is the fastest and ties `clef-flash` on the mean.
- Both baselines are far behind: the keyword rules (fitted on train) and the Bayesian prior (naive
  Bayes plus the joint over answer combinations, train only) reach about 0.45-0.48. The prior alone
  is weakest where classes are many and train items few (backlog-triage, 0.19 with ~4 items per
  repository). Fusing it with a model was neutral to slightly worse (see the changelog), so it is
  kept as a baseline, not a default.
- These runs are not comparable with earlier results. Anything labelled `earlier` in the result
  store (dev/heldout scoring splits, no train examples in the prompts) or `zero-shot` used a
  different protocol; the store and the rendered pages now say so.
