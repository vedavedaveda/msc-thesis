import datetime as dt
import json

import numpy as np
import pandas as pd
import polars as pl
import pytest

from msc_thesis.experiments.zero_shot import run as zs
from msc_thesis.experiments.zero_shot.metrics import score_forecasts

START = dt.datetime(2017, 4, 1)
CFG = {
    "year": 2017,
    "start_date": dt.date(2017, 4, 1),
    "n_days": 91,
    "start_test_day": 77,
    "n_test_days": 14,
    "n_stations": 250,
    "stations": None,
    "target": "check_ins",
    "past_covariates": ["check_outs"],
    "freq": 30,
    "prediction_length": 12,
    "horizons": [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360],
    "quantile_levels": [0.1, 0.5, 0.9],
    "cross_learning": True,
    "stride_steps": 1,
    "seed": 42,
    "model_id": "stub",
}


def _small_cfg(**kw):
    return {**CFG, "n_days": 10, "start_test_day": 8, "n_test_days": 2, **kw}


def _series(n_days=10, stops=("a", "b")) -> pd.DataFrame:
    times = pd.date_range(START, periods=n_days * 48, freq="30min")
    rows = [
        pd.DataFrame({"item_id": s, "timestamp": times, "check_ins": np.arange(len(times), dtype=float) % 7,
                      "check_outs": 1.0})
        for s in stops
    ]
    return pd.concat(rows, ignore_index=True)


class StubPipeline:
    """Predicts the bin index (0 = first predicted bin) so horizon alignment is visible."""

    def __init__(self):
        self.calls = []

    def predict_df(self, df, *, future_df, prediction_length, quantile_levels, id_column, timestamp_column,
                   target, cross_learning):
        self.calls.append({"context": df, "prediction_length": prediction_length,
                           "quantile_levels": quantile_levels, "cross_learning": cross_learning})
        last = df[timestamp_column].max()
        rows = []
        for item in df[id_column].unique():
            for k in range(prediction_length):
                rows.append({id_column: item, timestamp_column: last + pd.Timedelta(minutes=30 * (k + 1)),
                             "target_name": target, "predictions": float(k), "0.1": k - 1.0, "0.5": float(k),
                             "0.9": k + 1.0})
        return pd.DataFrame(rows)


def test_default_config_has_660_windows():
    times = zs.forecast_times(CFG)
    assert len(times) == 660
    assert times[0] == pd.Timestamp("2017-06-17")
    assert times[-1] + pd.Timedelta(minutes=360) == pd.Timestamp("2017-07-01") - pd.Timedelta(minutes=30)


def test_context_is_previous_week_strictly_before_forecast_time():
    df, t = _series(), pd.Timestamp("2017-04-09")
    ctx = zs.context_slice(df, t, ["item_id", "timestamp", "check_ins", "check_outs"])
    assert ctx["timestamp"].max() < t
    assert ctx["timestamp"].min() == t - pd.Timedelta(days=7)
    assert len(ctx) == 2 * 7 * 48


def test_horizon_alignment_and_call_arguments():
    stub = StubPipeline()
    out = zs.run_windows(stub, _series(), _small_cfg())
    call = stub.calls[0]
    assert call["prediction_length"] == 13 and call["cross_learning"] is True
    assert call["quantile_levels"] == [0.1, 0.5, 0.9]
    h30 = out.filter(pl.col("horizon") == 30)
    assert set(h30["prediction"]) == {1.0}            # second predicted bin: first bin is not scored
    assert set(out.filter(pl.col("horizon") == 360)["prediction"]) == {12.0}
    first = out["forecast_time"].min()
    assert (h30.filter(pl.col("forecast_time") == first)["timestamp"] == first + dt.timedelta(minutes=30)).all()
    assert out["forecast_time"].n_unique() == 2 * 48 - 12


def test_missing_truth_raises_with_window_and_horizon():
    df = _series()
    df = df[df["timestamp"] != pd.Timestamp("2017-04-09 01:00")]   # truth for first window at +60 min
    with pytest.raises(ValueError, match=r"horizon 60 min at forecast time 2017-04-09 00:00"):
        zs.run_windows(StubPipeline(), df, _small_cfg())


def test_horizon_validation():
    with pytest.raises(ValueError, match="horizons"):
        zs.validate_config(_small_cfg(horizons=[30, 45]))
    with pytest.raises(ValueError, match="horizons"):
        zs.validate_config(_small_cfg(horizons=[390]))


def test_outputs_roundtrip_to_identical_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(zs, "PROCESSED_DIR", tmp_path)
    out = zs.run_windows(StubPipeline(), _series(), _small_cfg())
    out_dir = zs.write_outputs(out, _small_cfg())
    saved = json.loads((out_dir / "metrics.json").read_text())
    rescored = score_forecasts(pl.read_parquet(out_dir / "forecasts.parquet"))
    for key in ("horizons", "overall"):
        assert json.loads(json.dumps(rescored[key])) == saved[key]
    assert saved["n_windows"] == 2 * 48 - 12


def test_missing_series_error_names_file_and_builder(tmp_path, monkeypatch):
    monkeypatch.setattr(zs, "PROCESSED_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match=r"series\.parquet.*data\.build zero_shot"):
        zs.load_series(CFG)


def test_run_end_to_end_with_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(zs, "PROCESSED_DIR", tmp_path)
    d = tmp_path / "zero_shot" / "2017"
    d.mkdir(parents=True)
    pl.from_pandas(_series()).write_parquet(d / "series.parquet")
    out_dir = zs.run(_small_cfg(), pipeline=StubPipeline())
    assert (out_dir / "forecasts.parquet").exists() and (out_dir / "metrics.json").exists()


def test_cli_overrides_run_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(zs, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(zs, "load_pipeline", lambda model_id: StubPipeline())
    d = tmp_path / "zero_shot" / "2017"
    d.mkdir(parents=True)
    pl.from_pandas(_series()).write_parquet(d / "series.parquet")
    monkeypatch.setattr("sys.argv", ["run", "--set", "n_days=10", "--set", "start_test_day=8",
                                     "--set", "n_test_days=2"])
    zs.main()
    assert json.loads((d / "metrics.json").read_text())["n_windows"] == 2 * 48 - 12
    assert "MAE" in capsys.readouterr().out


def test_native_jit_disabled_by_default_without_overriding_user_setting():
    import os
    import subprocess
    import sys

    code = "import os, msc_thesis.experiments.zero_shot.run; print(os.environ['TORCH_DISABLE_NATIVE_JIT'])"
    base = {k: v for k, v in os.environ.items() if k != "TORCH_DISABLE_NATIVE_JIT"}
    run = lambda env: subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.strip()
    assert run(base) == "1"
    assert run({**base, "TORCH_DISABLE_NATIVE_JIT": "0"}) == "0"
