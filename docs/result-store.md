# Result store and on-the-fly renderings

Every benchmark run is saved as a JSON file in `results/`. Those files stay the record, but each tool that
wanted a chart or a table wrote its own parser and its own generator. The result store replaces that with one
derived file and a set of renderers:

```
results/*.json  --import-->  state/store.sqlite  --render-->  svg | csv | json | md | html
(the record)                 (long-format rows)               (on request, nothing stored per format)
```

The store is rebuildable: delete `store.sqlite` and the next request rebuilds it from `results/`.

## Why SQLite

Parquet was the first idea (columnar, compressed). At this size it buys nothing: the whole `results/` folder
is 5.6 MB of JSON, 0.9 MB compressed, and rendering one view takes under a millisecond from SQLite. Parquet
also needs `pyarrow`, and crew-chief is stdlib-only. SQLite is in the standard library, is one file, and
indexes the rows a view needs. A zstd JSON Lines archive and a Parquet export are tracked in `BACKLOG.md`.

## Rows

| Table | One row per | Holds |
|---|---|---|
| `runs` | imported result file | source file name, kind (`taskbench` or `routebench`), task, created, content hash |
| `measures` | run, performer, task, question | items, accuracy, macro F1, mean/median/p90 latency, tokens per second, extra fields (JSON) |
| `answers` | run, performer, item, question (taskbench) | the answer, the expected value, its confidence, latency |

Importing is idempotent: a file is read again only when its hash changed, and an edited file replaces its rows.
Five kinds of result file are imported; anything else is skipped:

| Kind | Files | Becomes |
|---|---|---|
| `taskbench` | `taskbench-*.json` | accuracy and macro F1 per runner, task and question; one answer row per item |
| `routebench` | `routebench-*.json` | accuracy and latency per strategy and task |
| `testbench` | `test-bench-*.json` | a model's pass rate on a task is the accuracy, agent seconds the latency; one answer row per trial |
| `speedbench` | `bench-*.json` (inference speed) | `tps` (tokens per second) and time to first token per model and prompt |
| `enginebench` | `engine-matrix-*`, `serving-features-*` | `tps` per model and configuration; other fields in `extra` |

A schema change rebuilds the store from `results/` (`PRAGMA user_version`), so it never needs migrating by hand.
Renderings pick the metric the run has (accuracy, or tokens per second for a speed run) and leave out columns that
are empty for it.

## Renderings

`GET /render/<run>/<chart>.<format>` on the bench interface (`/api/store/runs` lists the runs):

| Chart | Formats | What it is |
|---|---|---|
| `scatter` | `svg` | accuracy against mean latency (log scale), Pareto front filled |
| `bars` | `svg` | accuracy per performer with its latency |
| `table` | `csv` `json` `md` `html` | one row per performer |
| `tasks` | `csv` `json` `md` `html` | per task and performer |

Every result has one strip of views, `html · json · md · svg · bars · csv`, in the viewer bar and under the top
bar of an HTML report. A view is the saved file when there is one (`results/<name>.md`, `.svg`, `.html`) and the
rendering above otherwise; `json` is only ever the saved data, and `bars` and `csv` exist for any result in the
store. A browser gets each rendering as a themed page with the top bar and a raw link; a script (no
`Accept: text/html`) or `?raw=1` gets the plain file, and `/files/...` is always plain.

**SVG and themes.** Charts style themselves with the portfolio tokens. Inline in a page they follow the page.
As a standalone file they carry their own: `?theme=neon` (any theme in `themes/themes.toml`) embeds that
theme's colours, and with no theme the file follows the viewer's light or dark setting.

## Adding a view or a source

- **A new rendering** is one function in `crew_chief/render.py` and an entry in `CHARTS`; it reads rows through
  `resultstore.performers` / `tasks` or a query of its own.
- **A new result kind** needs a branch in `resultstore._kind` and an importer that writes `measures` (and
  `answers` when there are per-item rows).
