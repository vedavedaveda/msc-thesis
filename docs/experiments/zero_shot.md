# Zero-shot Chronos-2 evaluation

Mirrors the mobility-baselines `Chronos-2-evaluation` Citi Bike pick-drop setup.

```bash
uv run python -m msc_thesis.data.build zero_shot              # build series.parquet
uv run python -m msc_thesis.experiments.zero_shot.run         # forecast + score
uv run python -m msc_thesis.experiments.zero_shot.run --set n_test_days=1 --set start_test_day=90
```

`run.py` sets `TORCH_DISABLE_NATIVE_JIT=1` (unless already set) because torch's Triton-compiled ops need a C compiler.
Settings live in `configs/zero_shot.yaml`. Outputs go to `data/processed/zero_shot/<year>/`:
`forecasts.parquet` (one row per window, horizon and stop; re-score with
`msc_thesis.experiments.zero_shot.metrics.score_forecasts`) and `metrics.json`.

Reference behaviour that is replicated on purpose, so numbers stay comparable:

- Each forecast predicts `prediction_length + 1` bins and horizon `h` is scored at forecast time + `h`,
  so the first predicted bin is never scored.
- Metrics are computed per window and horizon, then averaged (mean of RMSEs, not pooled).
- MAPE only uses points with truth > 0; MAE and RMSE use all points.
- `IQR_MEAN` is the mean width of the 0.1-0.9 interval, `COVERAGE` the share of truth inside it.

One deliberate difference: windows where MAPE is undefined (all truth zero) are skipped for MAPE
instead of turning the average into NaN; their count is reported as `n_nan_mape_windows`, next to
`n_windows` (scored forecast time and horizon pairs) and `n_forecast_times`. A horizon with no defined
MAPE is left out of the overall MAPE.

## Prerequisites

The builder reads `data/processed/stop_timeseries/<year>/stop_timeseries.parquet`, so the full-year
pipeline for `year` (from `configs/zero_shot.yaml`) must have run first:

```bash
uv run python -m msc_thesis.data.rejsekort.ingestion --year 2017        # needs server access
uv run python -m msc_thesis.data.rejsekort.cleaning --year 2017
uv run python -m msc_thesis.data.rejsekort.stop_timeseries --year 2017
```

Partial spans (`--day`, `--start/--end`) write to separate folders and are not read by the builder;
see [running on a day range](../running.md#zero-shot-on-a-day-range) for a workaround.
The stop time series must also:

- be built with `dense_output: true`, so every stop has every bin;
- use `interval_minutes` equal to `freq` in `configs/zero_shot.yaml`;
- cover the whole `[start_date, start_date + n_days)` window.

The builder and `run.py` check each of these and fail with a message naming the fix.
See [the Rejsekort data page](../data/rejsekort.md) for what the upstream steps do.

## Outputs

Everything lands in `data/processed/zero_shot/<year>/`:

```
series.parquet     item_id, timestamp, <target>, <past_covariates>   (data.build zero_shot)
forecasts.parquet  item_id, forecast_time, timestamp, horizon,
                   prediction, q_low, q_high, truth                  (run.py)
metrics.json       {"config", "horizons", "overall",
                    "n_forecast_times", "n_windows", "n_nan_mape_windows"}   (run.py)
```

`forecasts.parquet` and `metrics.json` are replaced together, and only after scoring succeeds, so a
failed run leaves the previous pair in place. A new run overwrites the previous one for the same year.

## Re-scoring

`score_forecasts` needs only the forecasts frame, not the model:

```python
import polars as pl
from msc_thesis.experiments.zero_shot.metrics import score_forecasts

scores = score_forecasts(pl.read_parquet("data/processed/zero_shot/2017/forecasts.parquet"))
scores["overall"]
```

## Recorded runs

### 2017-03-16 to 2017-06-15 (92 days, 2026-10-14)

Zero-shot Chronos-2 on three months of 2017 data, testing on the last 14 days (2017-06-02 to
2017-06-15). Code: `main` at `9d8b2a9`. Run on the server.

To reproduce, run from a clean checkout of that commit:

```bash
git switch --detach 9d8b2a9 && uv sync

S="--year 2017 --start 2017-03-16 --end 2017-06-15"
uv run python -m msc_thesis.data.rejsekort.ingestion $S
uv run python -m msc_thesis.data.rejsekort.cleaning $S
uv run python -m msc_thesis.data.rejsekort.stop_timeseries $S --set check_type_map_confirmed=true

mv data/processed/stop_timeseries/2017 data/processed/stop_timeseries/2017_old 2>/dev/null
cp -r data/processed/stop_timeseries/2017-03-16_2017-06-15 data/processed/stop_timeseries/2017

W="--set start_date=2017-03-16 --set n_days=92 --set start_test_day=78 --set n_test_days=14"
uv run python -m msc_thesis.data.build zero_shot $W
uv run python -m msc_thesis.experiments.zero_shot.run $W
```

Everything else is the committed config:

- `configs/stop_timeseries.yaml`: 30-min bins, `count_mode: transactions`, dense output, and
  `check_type_map` with `Io` ignored. The map was accepted with `--set check_type_map_confirmed=true`
  without a decision on `Io`.
- `configs/zero_shot.yaml`: the 250 busiest stops before the test period, target `check_ins` with
  `check_outs` as a past covariate, horizons 30 to 360 min, `amazon/chronos-2`, seed 42.

`metrics.json` stores the full config used, so you can check a rerun against it. The steps above
are explained in [running on a day range](../running.md#zero-shot-on-a-day-range).

Overall metrics:

| MAE | MAPE | RMSE | COVERAGE | IQR_MEAN |
|---|---|---|---|---|
| 4.956 | 0.633 | 10.131 | 0.697 | 15.419 |

The test period includes 2017-06-05, which was both Whit Monday and Constitution Day (a public
holiday).

## References

- Settings: [`configs/zero_shot.yaml`](../../configs/zero_shot.yaml) (each key is commented there)
- Requirements: [`zero-shot-evaluation`](../../openspec/specs/zero-shot-evaluation/spec.md),
  [`forecast-metrics`](../../openspec/specs/forecast-metrics/spec.md)
- Code: `data/builders/zero_shot.py`, `experiments/zero_shot/run.py`, `experiments/zero_shot/metrics.py`
  (under `src/msc_thesis/`)
