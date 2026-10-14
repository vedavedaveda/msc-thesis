"""Builder for the zero-shot experiment (Chronos-2, following the mobility-baselines Citi Bike setup).

Reads the shared stop time series (rejsekort/stop_timeseries.py) and writes one long
table to data/processed/zero_shot/<year>/series.parquet:

    item_id, timestamp, check_ins, check_outs      (sorted by item_id, timestamp)

One row per (stop, time bin) on a dense, regular grid covering `n_days` from
`start_date`. `target` is the series to forecast and `past_covariates` are passed as
context only, as in the paper's `bike_pick` / `bike_drop` pairing. The paper's 250
stations are mirrored by keeping the `n_stations` busiest stops, ranked on the days
before the test period so the test data does not pick the stations. Aggregation and
the check-in/out definition live upstream; this step only selects and validates.
"""

import datetime as dt
from pathlib import Path

import polars as pl

from msc_thesis.data.builders.base import Config
from msc_thesis.data.rejsekort.stop_timeseries import stop_timeseries_dir
from msc_thesis.utils.fs import atomic_file
from msc_thesis.utils.logging import get_logger
from msc_thesis.utils.paths import PROCESSED_DIR

log = get_logger(__name__)

EXPERIMENT = "zero_shot"
CHANNELS = {"check_ins", "check_outs"}
CONTEXT_DAYS = 7          # Chronos-2 eval feeds one week of history before each forecast
LOW_ACTIVITY_RATIO = 0.5  # flag days below this share of their weekday's median volume


def _as_datetime(value: object) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    return dt.datetime.fromisoformat(str(value))


def window(cfg: Config) -> tuple[dt.datetime, dt.datetime, dt.datetime]:
    """(start, test start, end) of the half-open window, checked against the split settings."""
    n_days, test_day, n_test = cfg["n_days"], cfg["start_test_day"], cfg["n_test_days"]
    if not CONTEXT_DAYS <= test_day or test_day + n_test != n_days:
        raise ValueError(
            f"Need {CONTEXT_DAYS} <= start_test_day and start_test_day + n_test_days == n_days, "
            f"got start_test_day={test_day}, n_test_days={n_test}, n_days={n_days}"
        )
    start = _as_datetime(cfg["start_date"])
    return start, start + dt.timedelta(days=test_day), start + dt.timedelta(days=n_days)


def select_stations(df: pl.DataFrame, cfg: Config, test_start: dt.datetime) -> list[str]:
    """Explicit `stations`, or the `n_stations` busiest stops before the test period."""
    if cfg["stations"] is not None:
        stations = [str(s) for s in cfg["stations"]]
        missing = sorted(set(stations) - set(df["item_id"].unique().to_list()))
        if missing:
            raise ValueError(f"stations not found in the stop time series window: {missing}")
        return stations
    ranked = (
        df.filter(pl.col("timestamp") < test_start)
        .group_by("item_id")
        .agg((pl.col("check_ins") + pl.col("check_outs")).sum().alias("volume"))
        .sort(["volume", "item_id"], descending=[True, False])
    )
    if len(ranked) < cfg["n_stations"]:
        log.warning("Only %d stops available; wanted n_stations=%d", len(ranked), cfg["n_stations"])
    return ranked.head(cfg["n_stations"])["item_id"].to_list()


def low_activity_days(df: pl.DataFrame) -> pl.DataFrame:
    """Days whose total volume is far below the median for that weekday.

    Dense zero-filling cannot tell feed outages from real zero demand; this flags
    candidates to inspect (holidays will show up here too).
    """
    daily = (
        df.group_by(pl.col("timestamp").dt.date().alias("date"))
        .agg((pl.col("check_ins") + pl.col("check_outs")).sum().alias("volume"))
        .with_columns(pl.col("date").dt.weekday().alias("weekday"))
    )
    return (
        daily.with_columns(pl.col("volume").median().over("weekday").alias("weekday_median"))
        .filter(pl.col("volume") < LOW_ACTIVITY_RATIO * pl.col("weekday_median"))
        .sort("date")
    )


def to_series_frame(ts: pl.DataFrame, cfg: Config) -> pl.DataFrame:
    """Window, select stations and validate the stop time series into the Chronos input layout."""
    target, covariates = cfg["target"], list(cfg["past_covariates"])
    unknown = ({target} | set(covariates)) - CHANNELS
    if unknown or target in covariates:
        raise ValueError(
            f"target and past_covariates must be distinct columns from {sorted(CHANNELS)}, "
            f"got target={target!r}, past_covariates={covariates}"
        )
    start, test_start, end = window(cfg)

    df = ts.rename({"stop_id": "item_id", "time_idx": "timestamp"}).filter(
        (pl.col("timestamp") >= start) & (pl.col("timestamp") < end)
    )
    df = df.filter(pl.col("item_id").is_in(select_stations(df, cfg, test_start)))
    if df.is_empty():
        raise ValueError("No rows left after applying the window and station selection")

    df = df.select("item_id", "timestamp", target, *covariates).sort("item_id", "timestamp")

    # Chronos is fed fixed-length windows per item, so every stop needs every time bin.
    times = df["timestamp"].unique().sort()
    steps = times.diff().drop_nulls().unique()
    if len(steps) > 1:
        raise ValueError(f"Time bins are not regularly spaced; found steps {steps.to_list()}")
    if (df.group_by("item_id").len()["len"] != len(times)).any():
        raise ValueError(
            "Series are not on a common dense grid (stops have different numbers of bins). "
            "Rebuild stop_timeseries with dense_output: true."
        )
    expected = int((end - start) / steps.item()) if len(steps) else 1
    if times[0] != start or len(times) != expected:
        raise ValueError(
            f"Window [{start}, {end}) is not fully covered: {len(times)} bins from {times[0]}, "
            f"expected {expected}. Rebuild stop_timeseries over this window."
        )
    return df


def build_zero_shot(cfg: Config) -> Path:
    source = stop_timeseries_dir(cfg["year"]) / "stop_timeseries.parquet"
    if not source.exists():
        raise FileNotFoundError(
            f"Stop time series not found: {source}. "
            f"Run `python -m msc_thesis.data.rejsekort.stop_timeseries --year {cfg['year']}` first."
        )
    start, _, end = window(cfg)
    ts = pl.scan_parquet(source).filter(pl.col("time_idx").is_between(start, end, closed="left")).collect()
    df = to_series_frame(ts, cfg)

    flagged = low_activity_days(df)
    if not flagged.is_empty():
        log.warning("Low-activity days (check for outages or holidays):\n%s", flagged)

    out_dir = PROCESSED_DIR / EXPERIMENT / str(cfg["year"])
    out_dir.mkdir(parents=True, exist_ok=True)
    with atomic_file(out_dir / "series.parquet") as tmp:
        df.write_parquet(tmp, compression="zstd")
    log.info(
        "Wrote %d rows (%d stops, %d bins) to %s",
        len(df), df["item_id"].n_unique(), df["timestamp"].n_unique(), out_dir / "series.parquet",
    )
    return out_dir
