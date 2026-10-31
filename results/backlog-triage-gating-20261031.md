# Backlog triage: confidence gating (2026-10-31)

Held-out split of `benchmarks/decisions/backlog-triage.json` (39 synthetic entries, 12 repositories plus
`unknown`, 6 groups), idle RTX 3090, Ollama `/v1/systemone`. An answer below the confidence threshold becomes
`unknown`. **Covered** is the share of entries that got a real (non-`unknown`) answer; **wrong** is the share
that got a real answer that was incorrect; **correct** counts a right answer or a right `unknown`. Thresholds
were chosen on the dev split (52 entries) and reported here on held-out.

| Question | Model | Threshold | Covered | Correct | Wrong | Median ms |
|---|---|---|---|---|---|---|
| repo | clef-flash | 0.0 | 0.92 | 0.82 | 0.15 | 189 |
| repo | clef-flash | 0.6 | 0.74 | 0.74 | 0.08 | 189 |
| repo | clef | 0.6 | 0.72 | 0.74 | 0.05 | 897 |
| group | clef | 0.0 | 0.87 | 0.74 | 0.18 | 897 |
| group | clef | 0.6 | 0.59 | 0.56 | 0.08 | 897 |
| group | clef-flash | 0.0 | 0.64 | 0.54 | 0.15 | 189 |

Accuracy without gating (held-out): repo 0.82 for `clef-flash` and `clef`, 0.74 `nimble`, 0.51 `tev1`;
group 0.74 `clef`, 0.54 `clef-flash`, 0.49 `nimble`, 0.28 `tev1`. The keyword baseline scores 0.97 and
0.82: the suite is easy for keywords because the entries share vocabulary (see the limits in
`docs/decision-model-selection.md`).
