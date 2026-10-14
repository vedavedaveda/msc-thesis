# Design

## Context

Builder output is ready (`data/processed/zero_shot/<year>/series.parquet`, dense grid, 250 stops, 91 days). Reference logic lives in `Chronos-2-evaluation/main.py` and `utils.evaluation_loop`, `evaluation.py`. The repo already uses YAML configs via `load_config`, polars for data, a CLI per stage (`python -m msc_thesis.data.build`). See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**
- Same windows, context, horizons, quantiles and metric arithmetic as the reference.
- Cheap re-scoring: forecasts persisted once.

**Non-Goals:**
- Hydra, tqdm-style reproduction of console output, other datasets or models.
- Fixing reference quirks (decided: replicate).

## Decisions

1. **Layout**: `src/msc_thesis/experiments/zero_shot/{metrics.py,run.py}`, CLI `python -m msc_thesis.experiments.zero_shot.run`, `--set KEY=VALUE` overrides like the build CLI. Keeps parity with `data/build.py`; Hydra rejected to avoid a second config system.
2. **Metrics ported verbatim** into `metrics.py` (numpy), including the `mask_value` quirk. Unit tests pin known values.
3. **Scoring split from inference**: the loop writes forecasts parquet; metrics computed by a function over that frame. The reference scores inline; separating allows re-scoring and tests without a model. Per-window averaging is kept in the scoring function, so numbers match.
4. **Pandas at the Chronos boundary**: `predict_df` needs pandas frames; read parquet with polars, convert once, slice windows with timestamp filters as the reference does.
5. **Config**: add `freq` (derived from `configs/stop_timeseries.yaml` `interval_minutes`, single source), `prediction_length: 12`, `horizons` (minutes, 30..360), `quantile_levels: [0.1, 0.5, 0.9]`, `cross_learning: true`, `stride_steps: 1`, `seed: 42`, `model_id: amazon/chronos-2`.
6. **Device**: cuda if available else cpu, as in reference.
7. **Output**: forecasts as one parquet (item_id, forecast_time, timestamp, horizon_min?, prediction, q0.1, q0.9, truth) restricted to scored horizons; summary JSON with per-horizon and overall metrics plus the config used.

## Risks / Trade-offs

- [Runtime: 660 calls x 250 stops] -> GPU; checkpoint-free for now, parquet written at end; add partial flush if CPU runs prove too long.
- [torch/chronos wheels on Python >=3.13] -> verify during first task; pin Python if needed.
- [MAPE unstable on zero-heavy stop counts; a window with all-zero truth has undefined MAPE, which the reference would propagate as NaN] -> kept for parity, but such windows are skipped for MAPE only and counted in `n_nan_mape_windows`; raw forecasts persisted so alternatives (e.g. MASE, sMAPE) can be computed later.
- [Forecast storage size] -> 660 x 250 x 12 rows ~ 2M rows, small with zstd.
- [Naive local grid across DST] -> not an issue for Apr-Jun 2017; builder already validates regular spacing.

## Open Questions

- Whether a historical-average baseline (reference `mobility_detrender.py`) should follow as a separate change for comparison.
