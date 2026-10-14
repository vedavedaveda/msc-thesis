"""Rejsekort stop time series: cleaned parquet -> check-ins/check-outs per stop and time bin.

Experiment-agnostic: a shared stage that experiment builders read from. Reads the
cleaned Rejsekort dataset (no filtering to complete journeys or S-trains) and writes
two linked parquet files to data/processed/stop_timeseries/<year>/:

    stop_timeseries.parquet
        time_idx, stop_id, check_ins, check_outs
    stop_locations.parquet
        stop_id, stop_name, latitude, longitude

Raw events stay lazy; only the aggregated bins are collected. The dense output is
written one day at a time. Stop IDs are not merged into stations.

Assumptions (see configs/stop_timeseries.yaml):
- `Model` codes map to check-in/out via `check_type_map`, which must be reviewed
  and confirmed. Unknown or missing codes raise instead of being dropped; codes
  mapped to "ignore" are excluded from both channels and logged with their counts.
- Bins are left-closed, right-open, labelled by their start. Timestamps are local
  and timezone-naive, as in cleaning: the repeated autumn DST hour cannot be told apart.
- Zeros in dense output mean "no recorded events", not proof the feed was complete.

    uv run python -m msc_thesis.data.rejsekort.stop_timeseries --year 2017
    uv run python -m msc_thesis.data.rejsekort.stop_timeseries --year 2017 --start 2017-06-19 --end 2017-06-26

`--day` / `--start --end` read the matching partial clean (see cleaning.py) and set
`start_time` / `end_time` to cover exactly those days.
"""

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from msc_thesis.data.rejsekort.cleaning import clean_path
from msc_thesis.data.rejsekort.ingestion import add_span_args, parse_span
from msc_thesis.utils.logging import get_logger
from msc_thesis.utils.paths import CONFIGS_DIR, PROCESSED_DIR

log = get_logger(__name__)

Config = dict[str, Any]

CONFIG_NAME = "stop_timeseries"
OUTPUT_NAME = "stop_timeseries"
PERSON_SLOTS = (1, 2, 3)
COUNT_MODES = {"transactions", "passengers"}
CHECK_TYPES = {"in", "out", "ignore"}  # "ignore": a known code that is neither counted as in nor out
MAX_DAILY_GRID_ROWS = 10_000_000

OUTPUT_SCHEMA = pa.schema([
    ("time_idx", pa.timestamp("ns")),
    ("stop_id", pa.string()),
    ("check_ins", pa.int64()),
    ("check_outs", pa.int64()),
])


def validate_config(cfg: Config) -> None:
    interval = cfg["interval_minutes"]
    if not isinstance(interval, int) or interval <= 0 or 1440 % interval:
        raise ValueError("interval_minutes must be a positive integer dividing 1440")
    if cfg["count_mode"] not in COUNT_MODES:
        raise ValueError(f"count_mode must be one of {sorted(COUNT_MODES)}")
    mapping = cfg["check_type_map"]
    if not mapping or not set(mapping.values()) <= CHECK_TYPES:
        raise ValueError("check_type_map values must be 'in', 'out' or 'ignore'")


def check_codes(events: pl.LazyFrame, check_type_map: dict[str, str], confirmed: bool) -> pl.DataFrame:
    """Event count per `Model` code; raise on unmapped codes or an unconfirmed map."""
    code_counts = events.group_by("Model").agg(pl.len().alias("events")).collect().sort("Model")
    unknown = [code for code in code_counts["Model"].to_list() if code not in check_type_map]
    if unknown:
        raise ValueError(f"Unmapped Model codes: {unknown}. Verify and update check_type_map.")
    if not confirmed:
        raise ValueError(
            f"Review the Model code counts and set check_type_map_confirmed: true.\n{code_counts}"
        )
    return code_counts


def weight_expr(events: pl.LazyFrame, count_mode: str, person_type_codes: list[int]) -> pl.Expr:
    """Per-event weight: 1 per event, or passengers of the configured person types.

    Passenger values are not filled across trips; missing or negative counts on
    configured person slots raise, and events with no recorded people weigh zero.
    """
    if count_mode == "transactions":
        return pl.lit(1, dtype=pl.Int64)
    # Person types are stored as floats (e.g. 1.0); cast so `is_in` matches the integer codes.
    person_type = {slot: pl.col(f"Passagertype{slot}").cast(pl.Int64) for slot in PERSON_SLOTS}
    invalid_slots = [
        person_type[slot].is_in(person_type_codes)
        & (pl.col(f"PassagerAntal{slot}").is_null() | (pl.col(f"PassagerAntal{slot}") < 0))
        for slot in PERSON_SLOTS
    ]
    invalid = events.filter(pl.any_horizontal(invalid_slots)).select(pl.len()).collect().item()
    if invalid:
        raise ValueError(f"{invalid} events have missing or negative person counts")
    return pl.sum_horizontal([
        pl.when(person_type[slot].is_in(person_type_codes))
        .then(pl.col(f"PassagerAntal{slot}"))
        .otherwise(0)
        for slot in PERSON_SLOTS
    ])


def resolve_bounds(
    events: pl.LazyFrame, start: object, end: object, interval_minutes: int
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Half-open [start, end) window; defaults cover the full event-date span."""
    bounds = events.select(
        pl.col("event_time").min().alias("first"),
        pl.col("event_time").max().alias("last"),
    ).collect().row(0, named=True)
    if bounds["first"] is None:
        raise ValueError("The input dataset is empty")
    start_time = pd.Timestamp(start) if start is not None else pd.Timestamp(bounds["first"]).normalize()
    end_time = (
        pd.Timestamp(end) if end is not None
        else pd.Timestamp(bounds["last"]).normalize() + pd.Timedelta(days=1)
    )
    if start_time.tzinfo is not None or end_time.tzinfo is not None:
        raise ValueError("Use timezone-naive bounds matching the cleaned timestamps")
    freq = f"{interval_minutes}min"
    if start_time >= end_time or start_time.floor(freq) != start_time or end_time.floor(freq) != end_time:
        raise ValueError("Bounds must be increasing and aligned to interval boundaries")
    return start_time, end_time


def bin_events(
    events: pl.LazyFrame,
    weight: pl.Expr,
    check_type_map: dict[str, str],
    interval_minutes: int,
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
) -> pd.DataFrame:
    """Sparse (time_idx, stop_id) -> check_ins, check_outs for the observed bins."""
    invalid = events.filter(
        pl.col("event_time").is_null() | pl.col("StopPointNr").is_null()
    ).select(pl.len()).collect().item()
    if invalid:
        raise ValueError(f"{invalid} events lack timestamps or stop IDs")

    binned = (
        events.filter(
            (pl.col("event_time") >= start_time.to_pydatetime())
            & (pl.col("event_time") < end_time.to_pydatetime())
            & pl.col("Model").replace_strict(check_type_map).ne("ignore")
        )
        .with_columns(
            pl.col("StopPointNr").cast(pl.String).alias("stop_id"),
            pl.col("event_time").dt.truncate(f"{interval_minutes}m").alias("time_idx"),
            pl.col("Model").replace_strict(check_type_map).alias("check_type"),
            weight.cast(pl.Int64).alias("weight"),
        )
        .group_by("time_idx", "stop_id")
        .agg(
            pl.col("weight").filter(pl.col("check_type") == "in").sum().alias("check_ins"),
            pl.col("weight").filter(pl.col("check_type") == "out").sum().alias("check_outs"),
        )
        .collect()
        .to_pandas()
        .sort_values(["time_idx", "stop_id"])
        .reset_index(drop=True)
    )
    if binned.empty:
        raise ValueError("No events within the requested bounds")
    return binned


def build_stop_locations(stop_ids: list[str], gtfs_stops_path: Path) -> pd.DataFrame:
    """Join GTFS coordinates onto Rejsekort stop IDs.

    GTFS IDs are stripped of whitespace and leading zeros to match Rejsekort's
    numeric IDs; collisions after normalization are rejected. Missing coordinates
    stay null, with no nearest-station substitution.
    """
    if not gtfs_stops_path.is_file():
        raise FileNotFoundError(f"GTFS stops not found: {gtfs_stops_path}")
    gtfs = pd.read_csv(
        gtfs_stops_path, dtype={"stop_id": "string"},
        usecols=["stop_id", "stop_name", "stop_lat", "stop_lon"],
    )
    gtfs["stop_id"] = gtfs["stop_id"].str.strip().str.replace(r"^0+(?=\d)", "", regex=True)
    if gtfs["stop_id"].isna().any() or gtfs["stop_id"].eq("").any():
        raise ValueError("GTFS contains missing stop IDs")
    if gtfs["stop_id"].duplicated().any():
        raise ValueError("GTFS stop IDs are not unique after normalization; inspect the mapping")

    locations = (
        pd.DataFrame({"stop_id": stop_ids})
        .merge(gtfs, on="stop_id", how="left", validate="one_to_one")
        .rename(columns={"stop_lat": "latitude", "stop_lon": "longitude"})
    )
    for column in ("latitude", "longitude"):
        locations[column] = pd.to_numeric(locations[column], errors="raise")
    invalid = (
        (locations["latitude"].notna() & ~locations["latitude"].between(-90, 90))
        | (locations["longitude"].notna() & ~locations["longitude"].between(-180, 180))
    )
    if invalid.any():
        raise ValueError("GTFS contains coordinates outside valid latitude/longitude ranges")
    missing = locations[["latitude", "longitude"]].isna().any(axis=1).sum()
    log.info("%d of %d stops lack complete coordinates", missing, len(locations))
    return locations


def write_timeseries(
    binned: pd.DataFrame,
    stop_ids: list[str],
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    interval_minutes: int,
    dense: bool,
    path: Path,
) -> tuple[int, dict[str, int]]:
    """Write one day at a time; returns (rows written, written totals)."""
    freq = f"{interval_minutes}min"
    tmp = path.with_name(path.stem + ".partial.parquet")
    expected = binned[["check_ins", "check_outs"]].sum().astype("int64")
    written = pd.Series({"check_ins": 0, "check_outs": 0}, dtype="int64")
    rows = 0
    try:
        with pq.ParquetWriter(tmp, OUTPUT_SCHEMA, compression="zstd") as writer:
            for date in pd.date_range(start_time.normalize(), end_time, freq="1D", inclusive="left"):
                day_start = max(date, start_time)
                day_end = min(date + pd.Timedelta(days=1), end_time)
                day = binned.loc[(binned["time_idx"] >= day_start) & (binned["time_idx"] < day_end)]
                if dense:
                    intervals = pd.date_range(day_start, day_end, freq=freq, inclusive="left")
                    if len(intervals) * len(stop_ids) > MAX_DAILY_GRID_ROWS:
                        raise ValueError(
                            "Daily grid exceeds 10 million rows; use sparse output or a longer interval"
                        )
                    grid = pd.MultiIndex.from_product([intervals, stop_ids], names=["time_idx", "stop_id"])
                    day = day.set_index(["time_idx", "stop_id"]).reindex(grid, fill_value=0).reset_index()
                day = day.astype({"check_ins": "int64", "check_outs": "int64"})
                writer.write_table(pa.Table.from_pandas(day, schema=OUTPUT_SCHEMA, preserve_index=False))
                rows += len(day)
                written += day[["check_ins", "check_outs"]].sum()
        if not written.equals(expected):
            raise AssertionError("Export changed the aggregated counts")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return rows, {k: int(v) for k, v in written.items()}


def build_stop_timeseries(cfg: Config, input_path: Path | None = None) -> Path:
    """`input_path` defaults to the full-year clean for `cfg["year"]`."""
    validate_config(cfg)
    year = cfg["year"]
    interval = cfg["interval_minutes"]
    input_path = input_path or clean_path(year)
    if not input_path.exists():
        raise FileNotFoundError(f"Cleaned dataset not found: {input_path}. Run cleaning first.")
    files = sorted(input_path.rglob("*.parquet")) if input_path.is_dir() else [input_path]
    if not files:
        raise ValueError("No input Parquet files found")

    events = pl.scan_parquet(files)
    code_counts = check_codes(events, cfg["check_type_map"], cfg["check_type_map_confirmed"])
    log.info("Model code counts:\n%s", code_counts)
    ignored = code_counts.filter(pl.col("Model").replace_strict(cfg["check_type_map"]) == "ignore")
    if len(ignored):
        log.info("Ignored (not counted as in or out):\n%s", ignored)
    weight = weight_expr(events, cfg["count_mode"], cfg["person_type_codes"])
    start_time, end_time = resolve_bounds(events, cfg["start_time"], cfg["end_time"], interval)

    binned = bin_events(events, weight, cfg["check_type_map"], interval, start_time, end_time)
    stop_ids = sorted(binned["stop_id"].unique())
    log.info("%d stops, %d observed bins; count mode: %s", len(stop_ids), len(binned), cfg["count_mode"])

    stop_locations = build_stop_locations(stop_ids, Path(cfg["gtfs_stops_path"]))

    out_dir = stop_timeseries_dir(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    timeseries_path = out_dir / "stop_timeseries.parquet"
    locations_path = out_dir / "stop_locations.parquet"
    rows, totals = write_timeseries(
        binned, stop_ids, start_time, end_time, interval, cfg["dense_output"], timeseries_path
    )
    stop_locations.to_parquet(locations_path, index=False, compression="zstd")
    log.info("Wrote %d time-series rows to %s", rows, timeseries_path)
    log.info("Wrote %d stop locations to %s", len(stop_locations), locations_path)
    log.info("Totals (%s): %s", cfg["count_mode"], totals)
    return out_dir


def stop_timeseries_dir(year: int) -> Path:
    """Where `build_stop_timeseries` writes for `year`; experiment builders read from here."""
    return PROCESSED_DIR / OUTPUT_NAME / str(year)


def load_config() -> Config:
    with open(CONFIGS_DIR / f"{CONFIG_NAME}.yaml") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, help="overrides `year` in the config")
    add_span_args(parser)
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE",
                        help="override a config entry; VALUE is parsed as YAML")
    args = parser.parse_args()

    cfg = load_config()
    if args.year is not None:
        cfg["year"] = args.year
    for item in args.overrides:
        key, sep, value = item.partition("=")
        if not sep or key not in cfg:
            parser.error(f"--set expects KEY=VALUE with a key from the config ({sorted(cfg)}), got {item!r}")
        cfg[key] = yaml.safe_load(value)
    start, end = parse_span(parser, args)
    input_path = None
    if start is not None:
        input_path = clean_path(cfg["year"], start, end)
        cfg["start_time"], cfg["end_time"] = start, end + dt.timedelta(days=1)
    out_dir = build_stop_timeseries(cfg, input_path)
    log.info("Wrote stop time series to %s", out_dir)


if __name__ == "__main__":
    main()
