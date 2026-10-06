"""Rejsekort cleaning: ingested parquet -> canonical clean parquet.

Experiment-agnostic. Parses types, drops unusable rows, and adds the derived
columns every experiment builds on. Works one day at a time (the ingested
dataset is partitioned by `RejseDato`), so memory use is bounded by a single day.

Duplicates are rows identical in every raw column. Identical rows always share a
`RejseDato`, so deduplicating within each day removes them all without ever
holding more than one day in memory.

    uv run python -m msc_thesis.data.rejsekort.cleaning --year 2019
"""

import argparse
import datetime as dt
import shutil
from pathlib import Path

import polars as pl

from msc_thesis.data.rejsekort.ingestion import interim_path
from msc_thesis.utils.fs import publish_dir, tmp_dir_for
from msc_thesis.utils.logging import get_logger
from msc_thesis.utils.paths import INTERIM_DIR

log = get_logger(__name__)

# Msgreportdate looks like "2020-02-14T07:32:57" (local time, no timezone).
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"
PARTITION_COL = "RejseDato"


def clean_path(year: int, day: dt.date | None = None) -> Path:
    name = f"clean_{day.isoformat()}" if day else f"clean_{year}"
    return INTERIM_DIR / "rejsekort" / name  # parquet dataset, partitioned by RejseDato


def derive_check_type(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add a `check_type` column ("in" / "out") to the event rows.

    TODO(veda): the rule is unknown until the `Model` and `turtype` codes are
    understood (row order within a `turngl` trip may also matter). Once it is,
    implement it here and call it from `clean_year` after `_clean`.
    """
    raise NotImplementedError("check_type derivation not defined yet")


# Raw columns kept only so duplicates are judged on the full row.
_DEDUPE_ONLY_COLS = ["NyUdførende", "ProduktFamilie"]


def _clean(lf: pl.LazyFrame, year: int) -> pl.LazyFrame:
    # Dedupe first, on the untouched raw row (all columns).
    return lf.unique(maintain_order=False).with_columns(
        pl.col("Msgreportdate").str.to_datetime(TIMESTAMP_FORMAT, strict=False).alias("event_time"),
        # Passengers checked in/out on this event, summed over the three passenger types.
        pl.sum_horizontal(
            pl.col("PassagerAntal1", "PassagerAntal2", "PassagerAntal3").fill_null(0)
        ).alias("passengers"),
    ).filter(
        pl.col("event_time").is_not_null()
        & (pl.col("event_time").dt.year() == year)
        & pl.col("StopPointNr").is_not_null()
    ).drop(_DEDUPE_ONLY_COLS)


def _days(dataset: Path) -> list[str]:
    return sorted(p.name.split("=", 1)[1] for p in dataset.glob(f"{PARTITION_COL}=*"))


def clean_year(
    year: int,
    day: dt.date | None = None,
    in_path: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    in_path = in_path or interim_path(year, day)
    out_path = out_path or clean_path(year, day)
    if not in_path.exists():
        raise FileNotFoundError(f"Ingested dataset not found: {in_path}. Run ingestion first.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir_for(out_path)

    days = _days(in_path)
    log.info("Cleaning %d days from %s -> %s", len(days), in_path, out_path)
    rows_in = rows_out = 0
    try:
        for d in days:
            # Read one partition's files directly: the partition value comes from the folder name.
            day_lf = pl.scan_parquet(in_path / f"{PARTITION_COL}={d}" / "*.parquet")
            rows_in += day_lf.select(pl.len()).collect().item()

            day_dir = tmp_path / f"{PARTITION_COL}={d}"
            day_dir.mkdir()
            _clean(day_lf, year).sink_parquet(day_dir / "part-0.parquet", compression="zstd")
            rows_out += pl.scan_parquet(day_dir / "part-0.parquet").select(pl.len()).collect().item()
    except BaseException:
        shutil.rmtree(tmp_path, ignore_errors=True)
        raise

    publish_dir(tmp_path, out_path)
    log.info("Done: kept %d of %d rows", rows_out, rows_in)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2019)
    parser.add_argument("--day", type=dt.date.fromisoformat, help="clean the single-day ingest (YYYY-MM-DD)")
    args = parser.parse_args()
    clean_year(args.year, args.day)


if __name__ == "__main__":
    main()
