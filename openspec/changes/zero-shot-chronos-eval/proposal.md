# Proposal

## Why

The zero-shot dataset builder (`data/builders/zero_shot.py`) already produces a Chronos-2-ready long table mirroring the mobility-baselines Citi Bike pick-drop setup, but nothing consumes it. The thesis needs a zero-shot Chronos-2 baseline on Rejsekort stops that is directly comparable to the paper's numbers, so the evaluation must follow `Chronos-2-evaluation` (`main.py`, `utils.evaluation_loop`, `evaluation.py`) as closely as possible.

## What Changes

- Add a sliding-window zero-shot evaluation runner: load `data/processed/zero_shot/<year>/series.parquet`, run Chronos-2 (`amazon/chronos-2`) over the test days, score per horizon.
- Port the reference metrics verbatim (MAE, RMSE, MAPE with `true > 0` mask, 10-90 interval coverage and width), including its arithmetic: per-window metrics averaged across windows, then across horizons.
- Replicate reference quirks on purpose and document them: `prediction_length = 12 + 1`, horizon `h` scored at `t + h` minutes (first predicted bin unscored), "IQR_MEAN" is the 10-90 width.
- Persist per-window forecasts (median and quantiles, with truth) to parquet, plus a metrics summary JSON, so re-scoring needs no rerun of the ~660 windows.
- Extend `configs/zero_shot.yaml` with model and evaluation keys; no Hydra, reuse `load_config`.
- Add `chronos-forecasting` and `torch` dependencies.

Out of scope: the data builder and stop time series (unchanged), fine-tuning, other baselines (HA, graph models), event covariates, plots.

## Capabilities

### New Capabilities
- `zero-shot-evaluation`: sliding-window Chronos-2 forecasting over the zero-shot series, reference-faithful windowing, context, horizons, and persisted forecasts and summary.
- `forecast-metrics`: reference-faithful point and interval metrics and their aggregation across windows and horizons.

### Modified Capabilities

None. No specs exist yet; the builder's behavior is not changing.

## Impact

- New code: `src/msc_thesis/experiments/zero_shot/` (runner, metrics) and tests under `tests/`.
- Changed: `configs/zero_shot.yaml` (additive keys), `pyproject.toml` (deps; Python >=3.13 compatibility of `torch`/`chronos-forecasting` to verify).
- Outputs: `data/processed/zero_shot/<year>/` forecasts parquet and metrics JSON.
- Compute: ~660 `predict_df` calls of 250 stops x 336 context bins; GPU recommended.
