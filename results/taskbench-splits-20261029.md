# Task suites with held-out splits 2026-10-29

Four synthetic suites, each scored on its dev and held-out split by the keyword
baseline and three local runners (`taskbench-<task>[-heldout]-20261029-*.md` hold
the full tables). RTX 3090 idle under an exclusive ECU lease. `message-routing`
keeps its original 30 items as dev (its rules were fitted to all of them) and
gains 10 held-out items; the other suites have 16 dev and 8 held-out items with
baseline rules written from the dev items.

| Suite (n dev / held-out) | rules dev → held-out | clef-flash held-out | nimble held-out | qwen3:14b held-out |
|---|---|---|---|---|
| message-routing (30 / 10) | 0.97 0.90 0.97 → 0.90 0.90 0.90 | 0.90 1.00 1.00, Brier 0.081 | 1.00 1.00 1.00, Brier 0.021 | 1.00 1.00 1.00 |
| mail-triage (16 / 8) | 0.81 0.88 1.00 → 0.62 0.50 0.75 | 1.00 0.75 1.00, Brier 0.129 | 1.00 0.50 1.00, Brier 0.264 | 1.00 0.50 1.00 |
| receipt-category (16 / 8) | 1.00 1.00 → 0.38 0.75 | 1.00 1.00, Brier 0.045 | 1.00 1.00, Brier 0.026 | 1.00 1.00 |
| schema-extraction (16 / 8) | 0.88 1.00 1.00 → 1.00 1.00 1.00 | 1.00 0.88 0.88, Brier 0.057 | 1.00 1.00 1.00, Brier 0.029 | 1.00 0.75 1.00 |

Accuracy per question in suite order (message-routing: intent, urgent, risk;
mail-triage: category, action, phishing; receipt-category: category, recurring;
schema-extraction: kind, currency, due date).

Findings:

- The keyword baseline overfits as expected: 1.00 → 0.38 on receipt category,
  0.81 → 0.62 on mail category. Dev scores for rules mean little.
- On the held-out `message-routing` items `nimble` matches or beats `clef-flash`
  (all questions 1.00, Brier 0.021 against 0.081) at 145 ms against 129 ms. With
  10 items this is a single-item difference per question, not a ranking; the
  policy keeps `clef-flash`, which led on the 30 dev items, until a larger
  held-out run settles it.
- Mail `action` (how much attention an email needs) is hard for every model, 0.50
  to 0.75 on held-out: the policy for what needs a reply is a judgement the
  labels encode, and is the best candidate for a fine-tune or a rule.
- The held-out p90 of about 10 s is the first call after Ollama swapped the
  model in; the medians match the dev runs.
- Sample sizes are small (8 to 10 held-out items). Treat differences of one item
  as noise and grow the suites before ranking close models.
