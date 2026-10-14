"""Forecast metrics, ported from mobility-baselines (evaluation.py, utils.probabilistic_metrics).

The arithmetic is kept identical to the reference on purpose, quirks included:
  * MAPE only uses points with truth > 0; MAE and RMSE use every point.
  * Every metric is computed per (forecast time, horizon) window, then averaged over
    windows, then over horizons. Per-window values are never pooled.
  * "IQR_MEAN" is the mean width of the [lower, upper] quantile interval (0.1-0.9 by
    default), not an inter-quartile range.

`score_forecasts` works on the persisted forecasts frame alone, so any run can be
re-scored without the model.
"""

import warnings

import numpy as np
import polars as pl

METRICS = ("MAE", "MAPE", "RMSE", "COVERAGE", "IQR_MEAN")

FORECAST_COLUMNS = ("item_id", "forecast_time", "timestamp", "horizon", "prediction", "q_low", "q_high", "truth")


def mae(true: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.absolute(pred - true)))


def rmse(true: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(pred - true))))


def mape(true: np.ndarray, pred: np.ndarray, mask_value: float | None = 0) -> float:
    """Mean absolute percentage error over points with truth > mask_value (NaN if none)."""
    if mask_value is not None:
        mask = true > mask_value
        true, pred = true[mask], pred[mask]
    if len(true) == 0:
        return float("nan")
    return float(np.mean(np.absolute(np.divide(true - pred, true))))


def point_metrics(true: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    return {"MAE": mae(true, pred), "MAPE": mape(true, pred, mask_value=0), "RMSE": rmse(true, pred)}


def interval_metrics(true: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> dict[str, float]:
    inside = (true >= lower) & (true <= upper)
    return {"COVERAGE": float(np.mean(inside)), "IQR_MEAN": float(np.mean(upper - lower))}


def window_metrics(forecasts: pl.DataFrame) -> pl.DataFrame:
    """One row per (forecast_time, horizon) with every metric."""
    rows = []
    for (forecast_time, horizon), g in forecasts.group_by(["forecast_time", "horizon"], maintain_order=True):
        true, pred = g["truth"].to_numpy(), g["prediction"].to_numpy()
        rows.append({
            "forecast_time": forecast_time,
            "horizon": horizon,
            **point_metrics(true, pred),
            **interval_metrics(true, g["q_low"].to_numpy(), g["q_high"].to_numpy()),
        })
    return pl.DataFrame(rows).sort("horizon", "forecast_time")


def aggregate(windows: pl.DataFrame) -> dict:
    """Mean over windows per horizon, then mean over horizons.

    Windows with undefined MAPE (all truth zero) are skipped for MAPE only; the reference
    would propagate NaN. `n_nan_mape_windows` reports how many were skipped.
    """
    per_horizon = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN MAPE at a horizon stays NaN
        for horizon, g in windows.group_by("horizon", maintain_order=True):
            per_horizon[int(horizon[0])] = {m: float(np.nanmean(g[m].to_numpy())) for m in METRICS}
    overall = {m: float(np.mean([v[m] for v in per_horizon.values()])) for m in METRICS}
    return {
        "horizons": per_horizon,
        "overall": overall,
        "n_windows": windows["forecast_time"].n_unique(),
        "n_nan_mape_windows": int(windows["MAPE"].is_nan().sum()),
    }


def score_forecasts(forecasts: pl.DataFrame) -> dict:
    missing = set(FORECAST_COLUMNS) - set(forecasts.columns)
    if missing:
        raise ValueError(f"Forecasts frame is missing columns: {sorted(missing)}")
    return aggregate(window_metrics(forecasts))
