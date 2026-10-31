# `clef-flash` on vague entries: a second run and the confidence gate (2026-10-31)

Question from `results/backlog-triage-v2-20261031.md`: `clef-flash` answered a repository for every vague
entry ("Make it faster") instead of `unknown` (0.00 on that kind). Is that noise, and does the confidence gate
Clockwork already uses cover it?

Second run of the plain `backlog-triage` suite (185 entries, all splits, idle RTX 3090) through the bench
queue: report `taskbench-backlog-triage-all-20261031-081410.md`, beside the first run
(`taskbench-backlog-triage-all-20261031-053815.*`). The second run's raw JSON (1.4 MB) is not committed; it is
in the interface's local results folder, and the runs are deterministic, so rerunning reproduces it.

## The runs are the same

| Runner | accuracy, run 1 | accuracy, run 2 | answers that changed (of 185) |
|---|---|---|---|
| `clef` | 0.89 | 0.89 | 0 |
| `clef-flash` | 0.83 | 0.83 | 0 |
| `nimble` | 0.79 | 0.78 | 1 (a vague entry) |
| `tev1` | 0.72 | 0.72 | not compared |
| keyword rules | 0.76 | 0.76 | 0 |

The decision models are close to deterministic, so repeating a run adds almost nothing. The uncertainty is the
number of hard entries (six vague, six naming two repositories), not run-to-run noise. Grow the suite, do not
repeat it.

## `clef-flash` is wrong on vague entries, but not confident

| Entry | `clef-flash` answer | confidence |
|---|---|---|
| Make it faster | `blog-site` | 0.19 |
| Fix the thing that broke yesterday | `scheduler-service` | 0.30 |
| Tidy up the settings page | `router-config` | 0.20 |
| Check why it is slow at night | `network-guard` | 0.20 |
| Add a dark mode | `blog-site` | 0.47 |
| Update the docs | `diagram-tool` | 0.52 |

Gating (an answer below the threshold becomes `unknown`), and what it costs among the other 179 entries:

| Gate | vague entries that become `unknown` | other entries that were right and become `unknown` |
|---|---|---|
| 0.5 | 5 of 6 | 7 |
| 0.6 (Clockwork's default) | **6 of 6** | 10 (6%) |
| 0.8 | 6 of 6 | 50 (28%) |
| 0.9 | 6 of 6 | 108 (60%) |

At the 0.6 gate Clockwork already uses, every vague entry is filed as `unknown` and the cost is 10 correct
answers. The weakness only matters ungated.

## Limits

Six vague entries is a small sample, and the confidences sit close to the 0.5 to 0.6 boundary for two of them
(0.47 and 0.52), so a different vague entry could pass the gate. The next step is more vague and
two-repository entries, then the same table.
