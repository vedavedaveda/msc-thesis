"""Rejsekort cleaning: ingested parquet -> canonical clean parquet.

Experiment-agnostic. Parses types, drops unusable rows, and adds the derived
columns every experiment builds on. Works one day at a time (the ingested
dataset is partitioned by `RejseDato`), so memory use is bounded by a single day.

Duplicates are rows identical in every raw column. Identical rows always share a
`RejseDato`, so deduplicating within each day removes them all without ever
holding more than one day in memory.

    uv run python -m msc_thesis.data.rejsekort.cleaning --year 2019
    uv run python -m msc_thesis.data.rejsekort.cleaning --year 2019 --start 2019-03-04 --end 2019-03-11
"""

import argparse
import datetime as dt
import shutil
from pathlib import Path

import polars as pl

from msc_thesis.data.rejsekort.ingestion import add_span_args, interim_path, parse_span, span_name
from msc_thesis.utils.fs import publish_dir, tmp_dir_for
from msc_thesis.utils.logging import get_logger
from msc_thesis.utils.paths import INTERIM_DIR

log = get_logger(__name__)

# Msgreportdate looks like "2020-02-14T07:32:57" (local time, no timezone).
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"
PARTITION_COL = "RejseDato"


def clean_path(year: int, start: dt.date | None = None, end: dt.date | None = None) -> Path:
    # parquet dataset, partitioned by RejseDato
    return INTERIM_DIR / "rejsekort" / f"clean_{span_name(year, start, end)}"


# Raw columns kept only so duplicates are judged on the full row.
_DEDUPE_ONLY_COLS = ["NyUdførende", "ProduktFamilie"]


def _clean(lf: pl.LazyFrame, year: int) -> pl.LazyFrame:
    # Dedupe first, on the untouched raw row (all columns).
    # Msgreportdate is the only time column; it is treated as the tap time.
    return lf.unique(maintain_order=False).with_columns(
        pl.col("Msgreportdate").str.to_datetime(TIMESTAMP_FORMAT, strict=False).alias("event_time"),
    ).filter(
        pl.col("event_time").is_not_null()
        & (pl.col("event_time").dt.year() == year)
        & pl.col("StopPointNr").is_not_null()
    ).drop(_DEDUPE_ONLY_COLS)


def _days(dataset: Path) -> list[str]:
    return sorted(p.name.split("=", 1)[1] for p in dataset.glob(f"{PARTITION_COL}=*"))


def clean_year(
    year: int,
    start: dt.date | None = None,
    end: dt.date | None = None,
    in_path: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    in_path = in_path or interim_path(year, start, end)
    out_path = out_path or clean_path(year, start, end)
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
    add_span_args(parser)  # must match the ingestion run being cleaned
    args = parser.parse_args()
    clean_year(args.year, *parse_span(parser, args))


if __name__ == "__main__":
    main()
