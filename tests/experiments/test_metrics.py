import datetime as dt

import numpy as np
import polars as pl
import pytest

from msc_thesis.experiments.zero_shot.metrics import (
    interval_metrics,
    mape,
    point_metrics,
    score_forecasts,
)

T0 = dt.datetime(2017, 6, 18)


def test_point_metrics_known_values():
    m = point_metrics(np.array([1.0, 2.0, 4.0]), np.array([2.0, 2.0, 2.0]))
    assert m["MAE"] == pytest.approx(1.0)
    assert m["RMSE"] == pytest.approx(np.sqrt(5 / 3))
    assert m["MAPE"] == pytest.approx(np.mean([1.0, 0.0, 0.5]))


def test_zero_truth_excluded_from_mape_only():
    true, pred = np.array([0.0, 2.0]), np.array([4.0, 1.0])
    m = point_metrics(true, pred)
    assert m["MAPE"] == pytest.approx(0.5)      # only the truth=2 point
    assert m["MAE"] == pytest.approx(2.5)       # both points
    assert m["RMSE"] == pytest.approx(np.sqrt((16 + 1) / 2))


def test_mape_nan_when_all_truth_zero():
    assert np.isnan(mape(np.zeros(3), np.ones(3)))


def test_coverage_and_width():
    true = np.array([1.0, 5.0, 3.0, 10.0])
    lower, upper = np.array([0.0, 4.0, 3.0, 0.0]), np.array([2.0, 6.0, 4.0, 9.0])
    m = interval_metrics(true, lower, upper)
    assert m["COVERAGE"] == pytest.approx(0.75)  # closed interval: 3.0 on the edge counts
    assert m["IQR_MEAN"] == pytest.approx(np.mean([2, 2, 1, 9]))


def _window(forecast_time, horizon, true, pred):
    return pl.DataFrame({
        "item_id": [f"s{i}" for i in range(len(true))],
        "forecast_time": forecast_time,
        "timestamp": forecast_time + dt.timedelta(minutes=horizon),
        "horizon": horizon,
        "prediction": [float(p) for p in pred],
        "q_low": [float(p) - 1 for p in pred],
        "q_high": [float(p) + 1 for p in pred],
        "truth": [float(t) for t in true],
    })


def test_aggregation_is_mean_of_window_rmses_not_pooled():
    # window 1: errors [1, 1] -> RMSE 1; window 2: errors [3, 3, 3, 3] with more points -> RMSE 3
    df = pl.concat([
        _window(T0, 30, [1, 1], [2, 2]),
        _window(T0 + dt.timedelta(minutes=30), 30, [0, 0, 0, 0], [3, 3, 3, 3]),
    ])
    out = score_forecasts(df)
    assert out["horizons"][30]["RMSE"] == pytest.approx(2.0)          # pooled would be sqrt(7.0)
    assert out["overall"]["RMSE"] == pytest.approx(2.0)
    assert out["n_windows"] == 2
    assert out["n_forecast_times"] == 2


def test_overall_is_mean_over_horizons():
    df = pl.concat([
        _window(T0, 30, [0, 0], [1, 1]),    # MAE 1
        _window(T0, 60, [0, 0], [3, 3]),    # MAE 3
    ])
    out = score_forecasts(df)
    assert out["horizons"][30]["MAE"] == pytest.approx(1.0)
    assert out["horizons"][60]["MAE"] == pytest.approx(3.0)
    assert out["overall"]["MAE"] == pytest.approx(2.0)


def test_nan_mape_windows_skipped_and_counted():
    df = pl.concat([
        _window(T0, 30, [0, 0], [1, 1]),                                   # MAPE undefined
        _window(T0 + dt.timedelta(minutes=30), 30, [2, 2], [1, 1]),        # MAPE 0.5
    ])
    out = score_forecasts(df)
    assert out["horizons"][30]["MAPE"] == pytest.approx(0.5)
    assert out["n_nan_mape_windows"] == 1


def test_window_counts_use_the_same_unit():
    df = pl.concat([_window(T0, h, [0, 0], [1, 1]) for h in (30, 60, 90)])
    out = score_forecasts(df)
    assert out["n_forecast_times"] == 1
    assert out["n_windows"] == 3
    assert out["n_nan_mape_windows"] == 3   # never more than n_windows


def test_horizon_without_defined_mape_is_left_out_of_overall():
    df = pl.concat([
        _window(T0, 30, [0, 0], [1, 1]),    # MAPE undefined at every window of horizon 30
        _window(T0, 60, [2, 2], [1, 1]),    # MAPE 0.5
    ])
    out = score_forecasts(df)
    assert np.isnan(out["horizons"][30]["MAPE"])
    assert out["overall"]["MAPE"] == pytest.approx(0.5)


def test_missing_columns_raise():
    with pytest.raises(ValueError, match="missing columns"):
        score_forecasts(pl.DataFrame({"item_id": ["a"]}))
