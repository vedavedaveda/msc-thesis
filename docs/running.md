# Running the pipeline

Step-by-step commands for running the pipeline on the server. What each step does and why is in
[the README](../README.md#pipeline) and [the Rejsekort data page](data/rejsekort.md); each module's
docstring has its full CLI usage.

## Before you start

```bash
cd ~/msc-thesis
git switch main && git pull
uv sync
```

- You need `~/.rkd_pass` and read access to `/mnt/raid/data_sortedmob/RKD/RawFiles/encrypted`.
- Ingestion decrypts a full year and the zero-shot run forecasts hundreds of windows. Start long
  runs inside `tmux` (or `screen`) so they survive a dropped SSH connection.

## Choosing a span

Every Rejsekort step takes `--year`, and optionally a smaller span inside that year:

| Run | Flags |
|---|---|
| Full year | `--year 2017` |
| One day | `--year 2017 --day 2017-06-19` |
| Day range (inclusive) | `--year 2017 --start 2017-03-16 --end 2017-06-15` |

Use **the same span flags for ingestion, cleaning and stop_timeseries**. Each step reads the
folder the previous one wrote for that span. The examples below use a full year; add the span flags
to each command for a range.

## 1. Ingestion

```bash
uv run python -m msc_thesis.data.rejsekort.ingestion --year 2017
```

Writes `data/interim/rejsekort/rejsekort_<span>/`. A day range still reads the whole archive (it
is one compressed stream), so it takes about as long as a full year; it only writes less.

## 2. Cleaning

```bash
uv run python -m msc_thesis.data.rejsekort.cleaning --year 2017
```

Writes `data/interim/rejsekort/clean_<span>/`. "Ingested dataset not found" means the span flags
differ from the ingestion run.

## 3. Stop time series

```bash
uv run python -m msc_thesis.data.rejsekort.stop_timeseries --year 2017
```

Writes `data/processed/stop_timeseries/<span>/stop_timeseries.parquet`. Settings are in
`configs/stop_timeseries.yaml`; override any of them with `--set KEY=VALUE`.

While `check_type_map_confirmed` is `false` in the config, the step stops and prints the event
count per `Model` code. Review the counts (especially `Io`), then either set it to `true` in the YAML
or pass `--set check_type_map_confirmed=true`.

## 4. Zero-shot dataset

```bash
uv run python -m msc_thesis.data.build zero_shot
```

Reads `data/processed/stop_timeseries/<year>/`, the full-year folder only, and writes
`data/processed/zero_shot/<year>/series.parquet`. The window, split and stations come from
`configs/zero_shot.yaml`. To run on a day range, see [below](#zero-shot-on-a-day-range).

## 5. Zero-shot forecast and scoring

```bash
uv run python -m msc_thesis.experiments.zero_shot.run
```

Writes `forecasts.parquet` and `metrics.json` to `data/processed/zero_shot/<year>/` and prints the
overall metrics. Uses the GPU when torch finds one. Pass the same `--set` overrides as in step 4,
because the run rebuilds the window from the config.

A new run for the same year overwrites the previous outputs. Copy the folder first if you want to
keep them, for example `cp -r data/processed/zero_shot/2017 data/processed/zero_shot/2017_<label>`.

## Zero-shot on a day range

The zero-shot builder does not take span flags yet. To use a range, run steps 1–3 with the span,
copy the result to the year folder, and override the window:

```bash
S="--year 2017 --start 2017-03-16 --end 2017-06-15"
uv run python -m msc_thesis.data.rejsekort.ingestion $S
uv run python -m msc_thesis.data.rejsekort.cleaning $S
uv run python -m msc_thesis.data.rejsekort.stop_timeseries $S

# Move any existing year folder aside first: if the target exists, cp -r copies *into* it.
mv data/processed/stop_timeseries/2017 data/processed/stop_timeseries/2017_old 2>/dev/null
cp -r data/processed/stop_timeseries/2017-03-16_2017-06-15 data/processed/stop_timeseries/2017

W="--set start_date=2017-03-16 --set n_days=92 --set start_test_day=78 --set n_test_days=14"
uv run python -m msc_thesis.data.build zero_shot $W
uv run python -m msc_thesis.experiments.zero_shot.run $W
```

- `n_days` is the number of days in the range.
- The test period is the last `n_test_days`, and `start_test_day + n_test_days` must equal `n_days`.
- Copy rather than symlink. A later full-year `stop_timeseries` run would write through a symlink
  and overwrite the range.
- The year folder now holds the range, not a full year. Move it aside before building a real
  full-year series.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Archive not found` / `Password file not found` | Not on the server, or `~/.rkd_pass` is missing. |
| `Ingested dataset not found` / `Cleaned dataset not found` | Span flags differ from the previous step's run. |
| `Review the Model code counts and set check_type_map_confirmed: true` | See [step 3](#3-stop-time-series). |
| `Stop time series not found` (zero-shot build) | No full-year folder for `year`; run step 3 without span flags, or see [the day-range recipe](#zero-shot-on-a-day-range). |
| `No rows left after applying the window and station selection` | The stop time series doesn't cover the window. Check its dates; a nested folder from `cp -r` into an existing folder is a common cause. |
| `Window ... is not fully covered` / `... covers ... but this config needs ...` | The window overrides don't match the data, or steps 4 and 5 used different `--set` values. |
| `git switch main` fails on `scrap/*.ipynb` even after stash/reset | nbstripout's git filter makes a notebook with committed outputs look modified. Run `git switch -f main`; to stop it recurring, commit the notebook with `git add --renormalize <notebook>`. |
