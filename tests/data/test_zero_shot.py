import datetime as dt

import polars as pl
import pytest

from msc_thesis.data.builders.zero_shot import low_activity_days, to_series_frame, window

START = dt.datetime(2017, 4, 1)
CFG = {
    "start_date": dt.date(2017, 4, 1),
    "n_days": 9,
    "start_test_day": 7,
    "n_test_days": 2,
    "n_stations": 2,
    "stations": None,
    "target": "check_ins",
    "past_covariates": ["check_outs"],
    "freq": 30,
}


def _grid(volumes: dict[str, int], n_days: int = 10, start: dt.datetime = START) -> pl.DataFrame:
    """Dense 30-min grid with constant counts per stop; spans one day past the 9-day window."""
    times = pl.datetime_range(start, start + dt.timedelta(days=n_days), "30m", closed="left", eager=True)
    return pl.concat([
        pl.DataFrame({"time_idx": times, "stop_id": stop, "check_ins": v, "check_outs": 2 * v})
        for stop, v in volumes.items()
    ])


DENSE = _grid({"a": 1, "b": 3, "c": 2})


def test_windows_renames_sorts_and_selects_columns():
    df = to_series_frame(DENSE, CFG)
    assert df.columns == ["item_id", "timestamp", "check_ins", "check_outs"]
    assert df["timestamp"].min() == START
    assert df["timestamp"].max() == START + dt.timedelta(days=9) - dt.timedelta(minutes=30)
    assert len(df) == 2 * 9 * 48
    assert df["item_id"].to_list() == sorted(df["item_id"].to_list())


def test_keeps_busiest_stations_before_test_period():
    # "a" is quiet before the test days and busy during them; ranking must ignore the test days.
    ts = DENSE.with_columns(
        pl.when((pl.col("stop_id") == "a") & (pl.col("time_idx") >= START + dt.timedelta(days=7)))
        .then(1000).otherwise(pl.col("check_ins")).alias("check_ins")
    )
    assert sorted(to_series_frame(ts, CFG)["item_id"].unique()) == ["b", "c"]


def test_explicit_stations_override_n_stations():
    df = to_series_frame(DENSE, {**CFG, "stations": ["a"]})
    assert df["item_id"].unique().to_list() == ["a"]


def test_explicit_stations_must_exist():
    with pytest.raises(ValueError, match=r"stations not found.*'zz'"):
        to_series_frame(DENSE, {**CFG, "stations": ["a", "zz"]})


def test_target_and_covariate_can_be_swapped():
    df = to_series_frame(DENSE, {**CFG, "target": "check_outs", "past_covariates": ["check_ins"]})
    assert df.columns == ["item_id", "timestamp", "check_outs", "check_ins"]


def test_rejects_non_dense_grid():
    sparse = DENSE.filter(~((pl.col("stop_id") == "b") & (pl.col("time_idx") == START)))
    with pytest.raises(ValueError, match="dense grid"):
        to_series_frame(sparse, CFG)


def test_rejects_window_not_fully_covered():
    late = _grid({"a": 1, "b": 3}, n_days=8, start=START + dt.timedelta(days=1))
    with pytest.raises(ValueError, match="not fully covered"):
        to_series_frame(late, CFG)


def test_rejects_bins_that_do_not_match_freq():
    with pytest.raises(ValueError, match="freq is 20 min"):
        to_series_frame(DENSE, {**CFG, "freq": 20})


def test_single_bin_does_not_pass_as_full_coverage():
    one = DENSE.filter(pl.col("time_idx") == START)
    with pytest.raises(ValueError, match="not fully covered"):
        to_series_frame(one, CFG)


def test_rejects_irregular_time_steps():
    irregular = DENSE.filter(pl.col("time_idx") != START + dt.timedelta(minutes=30))
    with pytest.raises(ValueError, match="regularly spaced"):
        to_series_frame(irregular, CFG)


def test_rejects_unknown_or_overlapping_channels():
    with pytest.raises(ValueError, match="distinct columns"):
        to_series_frame(DENSE, {**CFG, "past_covariates": ["check_ins"]})
    with pytest.raises(ValueError, match="distinct columns"):
        to_series_frame(DENSE, {**CFG, "target": "bike_pick"})


def test_window_requires_context_and_consistent_split():
    assert window(CFG) == (START, START + dt.timedelta(days=7), START + dt.timedelta(days=9))
    with pytest.raises(ValueError, match="start_test_day"):
        window({**CFG, "start_test_day": 6, "n_test_days": 3})
    with pytest.raises(ValueError, match="start_test_day"):
        window({**CFG, "n_test_days": 1})


def test_empty_selection_raises():
    with pytest.raises(ValueError, match="No rows left"):
        to_series_frame(_grid({"a": 1}, start=START + dt.timedelta(days=20)), CFG)   # no data in window


def test_low_activity_days_flags_outage():
    cfg = {**CFG, "n_days": 21, "start_test_day": 14, "n_test_days": 7, "n_stations": 1}
    df = to_series_frame(_grid({"a": 1}, n_days=21), cfg)
    outage = dt.date(2017, 4, 5)
    df = df.with_columns(
        pl.when(pl.col("timestamp").dt.date() == outage).then(0).otherwise(pl.col("check_ins")).alias("check_ins"),
        pl.when(pl.col("timestamp").dt.date() == outage).then(0).otherwise(pl.col("check_outs")).alias("check_outs"),
    )
    assert low_activity_days(df)["date"].to_list() == [outage]
