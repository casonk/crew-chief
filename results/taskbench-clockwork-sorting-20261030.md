# Clockwork list sorting, decision models against a chat model (2026-10-30)

Seven synthetic suites (`benchmarks/decisions/clockwork-*.json`, 228 items) that
sort an item into the categories of a Clockwork list. Every item (dev and
held-out) was scored once per runner; allowed values are stated before the input.
RTX 3090 idle, one run, no repeat. Four System One models through Ollama's
`/v1/systemone`, and `qwen2.5-coder:7b` (the model Clockwork's grocery
categorizer uses) through `/api/chat` with a JSON-schema-constrained reply.

Cells are accuracy / Brier (lower is better; chat models report none) / median
ms per item.

| Suite (n) | clef-flash | clef | nimble | tev1 | qwen2.5-coder:7b |
|---|---|---|---|---|---|
| grocery-type (60) | 1.00 / .018 / 119 | .98 / .016 / 724 | .98 / .018 / 131 | 1.00 / .003 / 84 | .88 / — / 131 |
| shopping-type (48) | .96 / .060 / 139 | .98 / .028 / 828 | .94 / .071 / 161 | .96 / .056 / 135 | 1.00 / — / 129 |
| watch-category (20) | .95 / .126 / 85 | .95 / .123 / 558 | .95 / .080 / 81 | .90 / .118 / 54 | .80 / — / 125 |
| listen-category (25) | .96 / .071 / 73 | 1.00 / .047 / 1116 | .92 / .085 / 87 | .92 / .088 / 56 | .92 / — / 133 |
| read-category (20) | 1.00 / .046 / 68 | .95 / .133 / 558 | 1.00 / .015 / 74 | .95 / .090 / 57 | .95 / — / 122 |
| todo-category (25) | .96 / .089 / 79 | .96 / .103 / 583 | .96 / .035 / 91 | .92 / .108 / 49 | .84 / — / 139 |
| invest-category (30) | .90 / .142 / 75 | .87 / .135 / 578 | .87 / .224 / 88 | .87 / .203 / 65 | 1.00 / — / 129 |
| unweighted mean | .96 | .96 | .95 | .93 | .91 |

Invalid answers: 0 for every runner; runner errors: 0.

## Prompt order (same model, same items)

`qwen2.5-coder:7b` accuracy with the item first, then the categories, against the
categories first, then the item:

| Suite | item first | categories first |
|---|---|---|
| grocery | .93 | .88 |
| shopping | .92 | 1.00 |
| watch | .45 | .80 |
| listen | .88 | .92 |
| read | .80 | .90 |
| todo | .88 | .84 |
| invest | .83 | .97 |

Re-running the categories-first prompt moved some scores by up to 5 points
(invest .97 then 1.00, read .90 then .95) although the temperature is 0, so
differences of a few points between single runs are noise. Item-first results
from before 2026-10-30 are not comparable.

## Selection strategies

The router benchmark over the same suites is in
`routebench-20261030-064003.{md,svg,json}` (88 held-out items, four System One
candidates, `clef-flash` as router). Summary and recommendation:
`docs/decision-model-selection.md`.
