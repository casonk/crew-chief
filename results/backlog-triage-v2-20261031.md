# Backlog triage v2: 26 repositories, hard entries, active sorting (2026-10-31)

`benchmarks/decisions/backlog-triage.json` was re-modelled on how Clockwork's To Code groups work: one
`repo` question over 26 synthetic repositories plus `unknown` (the group follows from the repository), with
uneven descriptions (from one word to a long paragraph) and 24 hard entries among 185: typos (7), two
repositories in one sentence (6; the label is the repository whose code changes), vague wording with no
repository (6) and entries that name none but imply one (5). Idle RTX 3090, Ollama `/v1/systemone`, one run
per cell, `--split all` (107 dev, 78 held-out). Raw runs: `taskbench-backlog-triage-all-20261031-053815.*` and
`taskbench-backlog-triage-active-<25|50|75>-all-*.*`. Results of the previous 12-repository suite stay in
`results/` for history and measure a different task.

## Plain suite (185 entries)

| Runner | accuracy | dev | held-out | median ms |
|---|---|---|---|---|
| `clef` | **0.89** | 0.94 | 0.82 | 1076 |
| `clef-flash` | 0.83 | 0.86 | 0.78 | 217 |
| `nimble` | 0.79 | 0.85 | 0.71 | 272 |
| `tev1` | 0.72 | 0.79 | 0.63 | 169 |
| keyword rules | 0.76 | 0.79 | 0.72 | 0 |

By kind of entry (accuracy; counts are 161 plain, 7, 6, 6, 5, so a cell is a handful of entries):

| Runner | plain | typo | two repos | vague | implied |
|---|---|---|---|---|---|
| `clef` | 0.89 | 1.00 | 0.67 | 1.00 | 1.00 |
| `clef-flash` | 0.86 | 0.86 | 0.50 | **0.00** | 1.00 |
| `nimble` | 0.76 | 1.00 | 0.83 | 1.00 | 1.00 |
| `tev1` | 0.71 | 1.00 | 0.50 | 1.00 | 0.40 |
| keyword rules | 0.78 | 1.00 | 0.17 | 1.00 | 0.40 |

`clef-flash` answers a repository for every vague entry ("Make it faster") instead of `unknown`; the others
decline. Two repositories in one sentence is the hardest kind for every runner.

Confidence gating on the repository answer (below the threshold the answer becomes `unknown`):

| Model | Threshold | Covered | Correct | Wrong |
|---|---|---|---|---|
| `clef-flash` | 0.0 | 0.97 | 0.83 | 0.17 |
| `clef-flash` | 0.6 | 0.82 | 0.82 | 0.06 |
| `clef` | 0.0 | 0.91 | 0.89 | 0.09 |
| `clef` | 0.6 | 0.78 | 0.82 | 0.03 |
| `clef` | 0.8 | 0.64 | 0.69 | 0.02 |

## Active sorting: examples in the descriptions

A share of each repository's own entries is written into its description as examples (what Clockwork would
do by passing the active sorting) and removed from the scored items. The table compares each model with its
own plain-suite answers on the same scored entries, so the removed items do not explain the change.
"Answered / wrong" is at confidence 0.6.

| Share passed | Runner | n | plain | with examples | change | answered | wrong | median ms |
|---|---|---|---|---|---|---|---|---|
| 25% | `clef-flash` | 132 | 0.80 | 0.80 | +0.00 | 0.47 | 0.03 | 423 |
| 25% | `clef` | 132 | 0.86 | 0.84 | -0.02 | 0.58 | 0.04 | 2237 |
| 25% | `nimble` | 132 | 0.78 | 0.77 | -0.02 | 0.69 | 0.06 | 499 |
| 25% | `tev1` | 132 | 0.70 | 0.73 | +0.03 | 0.69 | 0.08 | 312 |
| 50% | `clef-flash` | 92 | 0.76 | 0.76 | +0.00 | 0.24 | 0.01 | 550 |
| 50% | `clef` | 92 | 0.84 | 0.77 | -0.07 | 0.37 | 0.02 | 2652 |
| 50% | `nimble` | 92 | 0.75 | 0.70 | -0.05 | 0.64 | 0.09 | 649 |
| 50% | `tev1` | 92 | 0.66 | 0.68 | +0.02 | 0.60 | 0.09 | 408 |
| 75% | `clef-flash` | 48 | 0.71 | 0.73 | +0.02 | 0.15 | 0.04 | 718 |
| 75% | `clef` | 48 | 0.83 | 0.77 | -0.06 | 0.19 | 0.02 | 3167 |
| 75% | `nimble` | 48 | 0.79 | 0.71 | -0.08 | 0.60 | 0.08 | 819 |
| 75% | `tev1` | 48 | 0.65 | 0.75 | +0.10 | 0.56 | 0.12 | 516 |

Examples did not help the three models worth using: `clef-flash` is flat, `clef` and `nimble` lose 2 to 8
points, and every model becomes slower (median latency doubles at 25% and triples at 75%). The confidence of
the accurate models also falls, so far fewer answers pass a 0.6 gate (`clef-flash` answers 82% with no examples
and 47%, 24%, 15% with 25%, 50%, 75% of them). Only `tev1`, the weakest, gains (+0.10 is five entries of 48).
This agrees with the real-backlog check in `docs/decision-model-selection.md` (two example titles per
repository did not help).

## Limits

- **The keyword rules were written with every entry in view**, including the typos, so 0.76 is the best case for
  them and "a model beats the keywords" is conservative. They fail on two-repository entries (0.17) and
  implied ones (0.40), which share no keyword with their repository.
- One run per cell. The hard kinds hold 5 to 7 entries each, and the 75% variant scores 48, so differences of a
  few points (and `tev1`'s +0.10) are within noise; the direction (no gain from examples, slower, less
  confident) is the same in all three variants.
- Real repository names are not self-describing and real entries are messier; the suite is synthetic. Case
  variants of one repository name are handled in Clockwork (`canonical_repos`), not asked of the model.
