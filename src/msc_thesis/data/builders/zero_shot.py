"""Builder for the zero-shot experiment: counts per station per time step.

Reads the cleaned Rejsekort dataset (which must contain `check_type`) and writes
a tidy table to data/processed/zero_shot/:

    counts_<granularity>_<start>_<end>/station_batch=<k>/part-0.parquet
        station, time, check_type, count     (zero-filled, regular time grid)
    stations.parquet
        station, name                        (most frequent name per station)

Memory: the sparse counts are aggregated one day at a time, and the dense
zero-filled grid is built one batch of stations at a time, never for the year.
"""

import datetime as dt
import shutil
from pathlib import Path

import polars as pl

from msc_thesis.data.builders.base import Config
from msc_thesis.data.rejsekort.cleaning import clean_path
from msc_thesis.utils.fs import publish_dir, tmp_dir_for
from msc_thesis.utils.logging import get_logger
from msc_thesis.utils.paths import PROCESSED_DIR

log = get_logger(__name__)

EXPERIMENT = "zero_shot"


def _every(granularity: str) -> str:
    """Convert e.g. "5min" to polars' interval syntax ("5m"); whole minutes only."""
    minutes = pl.Series([granularity]).str.extract(r"^(\d+)\s*min$", 1)[0]
    if minutes is None or int(minutes) < 1:
        raise ValueError(f"granularity must look like '5min' (whole minutes), got {granularity!r}")
    return f"{int(minutes)}m"


def _time_bins(cfg: Config, every: str) -> pl.Series:
    start, end = cfg["start_date"], cfg["end_date"]
    return pl.datetime_range(
        dt.datetime.combine(start, dt.time.min),
        dt.datetime.combine(end, dt.time.max),
        interval=every,
        eager=True,
    ).alias("time")


def _select_days(clean_dir: Path, start: dt.date, end: dt.date) -> list[Path]:
    """Day partitions that can hold events in [start, end].

    Partitions are named by journey date, and a journey can run past midnight, so
    the day before `start` is included. Unparseable names are kept to be safe.
    """
    keep = []
    for d in sorted(clean_dir.glob("RejseDato=*")):
        try:
            day = dt.datetime.strptime(d.name.split("=", 1)[1], "%d%b%Y").date()
        except ValueError:
            keep.append(d)
            continue
        if start - dt.timedelta(days=1) <= day <= end + dt.timedelta(days=1):
            keep.append(d)
    return keep


def _aggregate_days(clean_dir: Path, sparse_dir: Path, cfg: Config, every: str) -> pl.DataFrame:
    """Sparse counts per (station, time, check_type) for each day; returns station names."""
    station, count = cfg["station_key"], cfg["count"]
    day_dirs = _select_days(clean_dir, cfg["start_date"], cfg["end_date"])
    if not day_dirs:
        raise FileNotFoundError(f"No day partitions in {clean_dir} overlap the period. Run cleaning first?")

    start = dt.datetime.combine(cfg["start_date"], dt.time.min)
    end = dt.datetime.combine(cfg["end_date"], dt.time.max)
    names = []
    for day_dir in day_dirs:
        lf = pl.scan_parquet(day_dir / "*.parquet")
        if "check_type" not in lf.collect_schema().names():
            raise ValueError(
                "Cleaned data has no `check_type` column. Implement `derive_check_type` "
                "in rejsekort/cleaning.py, wire it into `clean_year`, and rerun cleaning."
            )
        lf = lf.filter(pl.col("event_time").is_between(start, end))
        if cfg["stations"] is not None:
            lf = lf.filter(pl.col(station).is_in(cfg["stations"]))

        out = sparse_dir / day_dir.name
        out.mkdir()
        (
            lf.group_by(
                pl.col(station).alias("station"),
                pl.col("event_time").dt.truncate(every).alias("time"),
                "check_type",
            )
            .agg(pl.col(count).sum().alias("count"))
            .sink_parquet(out / "part-0.parquet")
        )
        names.append(
            lf.group_by(pl.col(station).alias("station"), pl.col("StopPointId").alias("name"))
            .agg(pl.len().alias("n"))
            .collect()
        )
    return pl.concat(names)


def build_zero_shot(cfg: Config) -> Path:
    if not cfg["fill_empty_steps"]:
        raise NotImplementedError("Only fill_empty_steps: true is supported")
    if cfg["start_date"].year != cfg["end_date"].year:
        raise ValueError("start_date and end_date must be in the same year")
    if cfg["start_date"] > cfg["end_date"]:
        raise ValueError(f"start_date {cfg['start_date']} is after end_date {cfg['end_date']}")
    every = _every(cfg["granularity"])
    year = cfg["start_date"].year
    bins = _time_bins(cfg, every)

    out_root = PROCESSED_DIR / EXPERIMENT
    out_root.mkdir(parents=True, exist_ok=True)
    counts_final = out_root / f"counts_{cfg['granularity']}_{cfg['start_date']}_{cfg['end_date']}"
    counts_tmp = tmp_dir_for(counts_final)
    sparse_dir = tmp_dir_for(out_root / "sparse")  # scratch, deleted at the end

    try:
        log.info("Aggregating sparse counts per day")
        names = _aggregate_days(clean_path(year), sparse_dir, cfg, every)
        sparse = pl.scan_parquet(sparse_dir / "*" / "*.parquet")

        check_types = sparse.select(pl.col("check_type").unique().sort()).collect().to_series().to_list()
        stations = sparse.select(pl.col("station").unique().sort()).collect().to_series().to_list()
        check_enum = pl.Enum(check_types)
        batch_size = cfg["station_batch_size"]
        log.info("%d stations, %d time steps, check types %s", len(stations), len(bins), check_types)

        for k in range(0, len(stations), batch_size):
            batch = stations[k : k + batch_size]
            grid = (
                pl.DataFrame({"station": batch}, schema={"station": sparse.collect_schema()["station"]})
                .join(bins.to_frame(), how="cross")
                .join(pl.DataFrame({"check_type": check_types}, schema={"check_type": pl.String}), how="cross")
            )
            # A bin can appear in two day partitions (events just after midnight), so sum again.
            counts = (
                sparse.filter(pl.col("station").is_in(batch))
                .group_by("station", "time", "check_type")
                .agg(pl.col("count").sum())
                .collect()
            )
            dense = (
                grid.join(counts, on=["station", "time", "check_type"], how="left")
                .with_columns(pl.col("count").fill_null(0), pl.col("check_type").cast(check_enum))
                .sort("station", "check_type", "time")
            )
            part = counts_tmp / f"station_batch={k // batch_size}"
            part.mkdir()
            dense.write_parquet(part / "part-0.parquet", compression="zstd")
            log.info("  wrote stations %d-%d of %d", k, k + len(batch), len(stations))

        publish_dir(counts_tmp, counts_final)
        (
            names.group_by("station")
            .agg(pl.col("name").sort_by("n").last())
            .sort("station")
            .write_parquet(out_root / "stations.parquet")
        )
    except BaseException:
        shutil.rmtree(counts_tmp, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(sparse_dir, ignore_errors=True)

    return out_root
