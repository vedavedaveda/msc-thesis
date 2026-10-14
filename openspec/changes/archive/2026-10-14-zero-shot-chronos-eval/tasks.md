# Tasks

## 1. Setup

- [x] 1.1 Add `chronos-forecasting` and `torch` to `pyproject.toml`, run `uv sync`, and verify `python -c "from chronos import Chronos2Pipeline"` succeeds on Python 3.13 (pin Python if not)
- [x] 1.2 Extend `configs/zero_shot.yaml` with `freq`, `prediction_length`, `horizons`, `quantile_levels`, `cross_learning`, `stride_steps`, `seed`, `model_id`; verify `load_config("zero_shot")` returns them and `freq` matches `stop_timeseries.yaml` `interval_minutes`
- [x] 1.3 Create package `src/msc_thesis/experiments/zero_shot/` (with `__init__.py`) and verify `import msc_thesis.experiments.zero_shot` works

## 2. Metrics

- [x] 2.1 Port MAE, RMSE, MAPE (`true > 0` mask) and interval coverage/width into `metrics.py`; verify unit tests in `tests/experiments/test_metrics.py` cover the known-value, zero-truth and coverage scenarios of `forecast-metrics`
- [x] 2.2 Implement per-window then per-horizon then overall aggregation over a forecasts frame; verify a test shows mean-of-RMSEs (1 and 3 gives 2), not pooled RMSE

## 3. Evaluation runner

- [x] 3.1 Implement window and context slicing (7-day context, strictly before forecast time, stride, window count) as pure functions; verify tests for 660 windows with default config and no-leakage bounds
- [x] 3.2 Implement the forecast loop calling `Chronos2Pipeline.predict_df` with `prediction_length + 1`, quantiles and `cross_learning`, horizon lookup at `t + h`, seeded, with a missing-truth error; verify a test with a stub pipeline checks alignment (30 min equals second predicted bin) and the error
- [x] 3.3 Write per-window forecasts parquet and metrics summary JSON under `data/processed/zero_shot/<year>/`; verify a test re-computes the summary from the parquet alone with identical values
- [x] 3.4 Add the CLI `python -m msc_thesis.experiments.zero_shot.run` with `--set KEY=VALUE` overrides and a clear error when `series.parquet` is missing; verify the missing-file error and an override on a small synthetic series run end to end with the stub pipeline

## 4. Integration

- [x] 4.1 Run the real pipeline on a short window (e.g. `--set n_stations=10 --set n_test_days=1` equivalent) and verify forecasts parquet and summary JSON are produced with sane values
- [x] 4.2 Document the run command, outputs and the deliberately replicated reference quirks in `README.md`; verify the documented command runs as written
