# msc-thesis
This is for our MSc Thesis

## Zero-shot Chronos-2 evaluation

Mirrors the mobility-baselines `Chronos-2-evaluation` Citi Bike pick-drop setup.

```bash
uv run python -m msc_thesis.data.build zero_shot              # build series.parquet
uv run python -m msc_thesis.experiments.zero_shot.run         # forecast + score
uv run python -m msc_thesis.experiments.zero_shot.run --set n_test_days=1 --set start_test_day=90
```

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
instead of turning the average into NaN; their count is reported as `n_nan_mape_windows`.
