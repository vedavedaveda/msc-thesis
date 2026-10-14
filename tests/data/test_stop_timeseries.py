import datetime as dt

import pandas as pd
import polars as pl
import pyarrow.parquet as pq
import pytest

from msc_thesis.data.rejsekort import stop_timeseries
from msc_thesis.data.rejsekort.stop_timeseries import (
    bin_events,
    build_stop_locations,
    check_codes,
    resolve_bounds,
    validate_config,
    weight_expr,
    write_timeseries,
)

CHECK_MAP = {"Fi": "in", "Tr": "in", "Co": "out"}


def _events(rows: list[tuple]) -> pl.LazyFrame:
    return pl.LazyFrame(
        rows,
        schema={
            "event_time": pl.Datetime, "StopPointNr": pl.Int64, "Model": pl.String,
            # Person types are float64 in the ingested schema.
            "Passagertype1": pl.Float64, "PassagerAntal1": pl.Int64,
            "Passagertype2": pl.Float64, "PassagerAntal2": pl.Int64,
            "Passagertype3": pl.Float64, "PassagerAntal3": pl.Int64,
        },
        orient="row",
    )


def _row(time: str, stop: int | None, model: str, p1=(1, 1), p2=(None, None), p3=(None, None)) -> tuple:
    return (dt.datetime.fromisoformat(time), stop, model, *p1, *p2, *p3)


def test_validate_config_rejects_bad_interval():
    cfg = {"interval_minutes": 7, "count_mode": "transactions", "check_type_map": CHECK_MAP}
    with pytest.raises(ValueError, match="dividing 1440"):
        validate_config(cfg)


def test_validate_config_rejects_bad_map_values():
    cfg = {"interval_minutes": 20, "count_mode": "transactions", "check_type_map": {"Fi": "enter"}}
    with pytest.raises(ValueError, match="'in', 'out' or 'ignore'"):
        validate_config(cfg)


def test_check_codes_rejects_unmapped_code():
    events = _events([_row("2017-01-01 08:00", 1, "Xx")])
    with pytest.raises(ValueError, match="Unmapped Model codes"):
        check_codes(events, CHECK_MAP, confirmed=True)


def test_check_codes_requires_confirmation():
    events = _events([_row("2017-01-01 08:00", 1, "Fi")])
    with pytest.raises(ValueError, match="check_type_map_confirmed"):
        check_codes(events, CHECK_MAP, confirmed=False)


def test_bins_are_left_closed_and_sum_in_and_out():
    events = _events([
        _row("2017-01-01 08:00", 1, "Fi"),
        _row("2017-01-01 08:19", 1, "Tr"),
        _row("2017-01-01 08:19", 1, "Co"),
        _row("2017-01-01 08:20", 1, "Fi"),  # next bin
    ])
    start, end = resolve_bounds(events, None, None, 20)
    binned = bin_events(events, weight_expr(events, "transactions", []), CHECK_MAP, 20, start, end)
    first, second = binned.to_dict("records")
    assert (first["time_idx"], first["check_ins"], first["check_outs"]) == (
        pd.Timestamp("2017-01-01 08:00"), 2, 1,
    )
    assert (second["time_idx"], second["check_ins"], second["check_outs"]) == (
        pd.Timestamp("2017-01-01 08:20"), 1, 0,
    )


def test_ignored_codes_count_in_neither_channel_and_create_no_bins():
    events = _events([
        _row("2017-01-01 08:00", 1, "Fi"),
        _row("2017-01-01 08:05", 1, "Cc"),
        _row("2017-01-01 09:00", 2, "Cc"),  # stop 2 only ever sees ignored events
    ])
    cmap = {**CHECK_MAP, "Cc": "ignore"}
    start, end = resolve_bounds(events, None, None, 20)
    binned = bin_events(events, weight_expr(events, "transactions", []), cmap, 20, start, end)
    assert binned[["stop_id", "check_ins", "check_outs"]].to_dict("records") == [
        {"stop_id": "1", "check_ins": 1, "check_outs": 0}
    ]


def test_passenger_weight_only_counts_configured_person_types():
    events = _events([_row("2017-01-01 08:00", 1, "Fi", p1=(1, 2), p2=(99, 5), p3=(2, 1))])
    start, end = resolve_bounds(events, None, None, 20)
    weight = weight_expr(events, "passengers", [1, 2])
    binned = bin_events(events, weight, CHECK_MAP, 20, start, end)
    assert binned["check_ins"].item() == 3


def test_passenger_weight_rejects_missing_count_on_configured_slot():
    events = _events([_row("2017-01-01 08:00", 1, "Fi", p1=(1, None))])
    with pytest.raises(ValueError, match="missing or negative"):
        weight_expr(events, "passengers", [1])


def test_bin_events_rejects_missing_stop_id():
    events = _events([_row("2017-01-01 08:00", None, "Fi")])
    start, end = pd.Timestamp("2017-01-01"), pd.Timestamp("2017-01-02")
    with pytest.raises(ValueError, match="lack timestamps or stop IDs"):
        bin_events(events, pl.lit(1), CHECK_MAP, 20, start, end)


def test_resolve_bounds_rejects_unaligned_bounds():
    events = _events([_row("2017-01-01 08:00", 1, "Fi")])
    with pytest.raises(ValueError, match="aligned"):
        resolve_bounds(events, "2017-01-01 00:05", None, 20)


def test_build_stop_locations_normalises_ids_and_keeps_missing_null(tmp_path):
    gtfs = tmp_path / "stops.txt"
    gtfs.write_text("stop_id,stop_name,stop_lat,stop_lon\n 00123 ,A,55.6,12.5\n456,B,55.7,12.6\n")
    loc = build_stop_locations(["123", "999"], gtfs)
    assert loc.loc[0, ["stop_name", "latitude"]].tolist() == ["A", 55.6]
    assert loc.loc[1, ["latitude", "longitude"]].isna().all()


def test_build_stop_locations_rejects_collisions(tmp_path):
    gtfs = tmp_path / "stops.txt"
    gtfs.write_text("stop_id,stop_name,stop_lat,stop_lon\n0123,A,55.6,12.5\n123,B,55.7,12.6\n")
    with pytest.raises(ValueError, match="not unique"):
        build_stop_locations(["123"], gtfs)


def test_dense_output_zero_fills_and_preserves_totals(tmp_path):
    binned = pd.DataFrame({
        "time_idx": pd.to_datetime(["2017-01-01 00:00", "2017-01-01 23:40"]),
        "stop_id": ["1", "2"],
        "check_ins": [3, 0],
        "check_outs": [0, 4],
    })
    path = tmp_path / "stop_timeseries.parquet"
    start, end = pd.Timestamp("2017-01-01"), pd.Timestamp("2017-01-02")
    rows, totals = write_timeseries(binned, ["1", "2"], start, end, 20, True, path)
    assert rows == 72 * 2
    assert totals == {"check_ins": 3, "check_outs": 4}
    assert pq.read_table(path).num_rows == rows
    assert not path.with_name("stop_timeseries.partial.parquet").exists()


def test_sparse_output_writes_only_observed_bins(tmp_path):
    binned = pd.DataFrame({
        "time_idx": pd.to_datetime(["2017-01-01 08:00"]),
        "stop_id": ["1"], "check_ins": [1], "check_outs": [0],
    })
    path = tmp_path / "stop_timeseries.parquet"
    rows, _ = write_timeseries(
        binned, ["1"], pd.Timestamp("2017-01-01"), pd.Timestamp("2017-01-02"), 20, False, path
    )
    assert rows == 1


def test_build_without_gtfs_skips_stop_locations(tmp_path, monkeypatch):
    clean = tmp_path / "clean"
    clean.mkdir()
    _events([_row("2017-01-01 08:00", 1, "Fi"), _row("2017-01-01 08:10", 2, "Co")]).collect().write_parquet(
        clean / "part.parquet"
    )
    monkeypatch.setattr(stop_timeseries, "PROCESSED_DIR", tmp_path / "processed")
    cfg = {
        "year": 2017, "interval_minutes": 30, "count_mode": "transactions", "check_type_map": CHECK_MAP,
        "check_type_map_confirmed": True, "person_type_codes": [], "dense_output": True,
        "start_time": None, "end_time": None, "gtfs_stops_path": None,
    }
    out_dir = stop_timeseries.build_stop_timeseries(cfg, clean)
    assert (out_dir / "stop_timeseries.parquet").exists()
    assert not (out_dir / "stop_locations.parquet").exists()
