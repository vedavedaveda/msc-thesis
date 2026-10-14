"""Rejsekort ingestion: encrypted server archive -> interim parquet.

Streams the archive (decrypt -> untar -> CSV) in chunks, keeps only the columns
and rows we need, and writes each chunk into a parquet dataset partitioned by
`RejseDato` (one folder per day). Nothing decrypted is written to disk and the
full year is never held in memory.

    uv run python -m msc_thesis.data.rejsekort.ingestion --year 2019
    uv run python -m msc_thesis.data.rejsekort.ingestion --year 2019 --day 2019-03-05
    uv run python -m msc_thesis.data.rejsekort.ingestion --year 2019 --start 2019-03-04 --end 2019-03-11
"""

import argparse
import datetime as dt
import shlex
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from msc_thesis.utils.fs import publish_dir, tmp_dir_for
from msc_thesis.utils.logging import get_logger
from msc_thesis.utils.paths import ENCRYPTED_DIR, INTERIM_DIR, PASS_FILE

log = get_logger(__name__)

ARCHIVE_TEMPLATE = "DTU_SJAELLAND_{year}.tar.gz.aes-256-cbc"
ENCODING = "ISO-8859-1"
CHUNK_ROWS = 2_000_000

REGION_COL = "TakstOmraade"
REGION_VALUE = "Hovedstadsområdet"

# Raw columns we keep, with their stored types. Integer columns are nullable so the
# parquet schema stays identical across chunks.
SCHEMA = pa.schema(
    [
        ("Msgreportdate", pa.string()),
        ("PassagerAntal1", pa.int64()),
        ("PassagerAntal2", pa.int64()),
        ("PassagerAntal3", pa.int64()),
        ("Passagertype1", pa.float64()),
        ("Passagertype2", pa.float64()),
        ("Passagertype3", pa.float64()),
        ("RuteId", pa.string()),
        ("RejseDato", pa.string()),
        ("StopPointNr", pa.int64()),
        ("StopPointId", pa.string()),
        ("ContractorId", pa.string()),
        # Event code per row, e.g. "Fi", "Cc". Mapped to check-in/out in stop_timeseries.
        ("Model", pa.string()),
        ("turtype", pa.string()),  # trip pattern, e.g. "FiCc"
        ("ModalKomb", pa.string()),
        # Not used downstream, but kept so cleaning can detect duplicates on the full raw row.
        ("NyUdførende", pa.string()),
        ("ProduktFamilie", pa.string()),
        ("turngl", pa.int64()),
        ("Kortnr_Kryp", pa.string()),
        (REGION_COL, pa.string()),
    ]
)

_PANDAS_DTYPES = {
    field.name: (
        "Int64" if pa.types.is_integer(field.type)
        else "float64" if pa.types.is_floating(field.type)
        else "str"
    )
    for field in SCHEMA
}

# RejseDato format, e.g. "14FEB2020".
_REJSEDATO_FORMAT = "%d%b%Y"


def span_name(year: int, start: dt.date | None = None, end: dt.date | None = None) -> str:
    """Dataset name suffix: the year, one day, or an inclusive day range."""
    if start is None:
        return str(year)
    if end is None or end == start:
        return start.isoformat()
    return f"{start.isoformat()}_{end.isoformat()}"


def interim_path(year: int, start: dt.date | None = None, end: dt.date | None = None) -> Path:
    # parquet dataset, partitioned by RejseDato
    return INTERIM_DIR / "rejsekort" / f"rejsekort_{span_name(year, start, end)}"


def _day_strings(start: dt.date, end: dt.date | None) -> set[str]:
    """RejseDato values for the inclusive range [start, end]."""
    end = end or start
    if end < start:
        raise ValueError(f"end ({end}) is before start ({start})")
    n_days = (end - start).days + 1
    return {(start + dt.timedelta(days=i)).strftime(_REJSEDATO_FORMAT).upper() for i in range(n_days)}


def _open_stream(archive: Path, pass_file: Path) -> subprocess.Popen:
    """Decrypt + decompress into a pipe; nothing is written to disk."""
    cmd = (
        f"openssl enc -d -aes-256-cbc -salt -pbkdf2 "
        f"-in {shlex.quote(str(archive))} -pass file:{shlex.quote(str(pass_file))} | tar xzO"
    )
    return subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _filter_chunk(chunk: pd.DataFrame, days: set[str] | None) -> pd.DataFrame:
    chunk = chunk[chunk[REGION_COL] == REGION_VALUE]
    if days is not None:
        chunk = chunk[chunk["RejseDato"].str.upper().isin(days)]
    return chunk


def ingest_year(
    year: int,
    start: dt.date | None = None,
    end: dt.date | None = None,
    source_dir: Path = ENCRYPTED_DIR,
    pass_file: Path = PASS_FILE,
    out_path: Path | None = None,
) -> Path:
    """Ingest one year's archive into an interim parquet dataset; optionally keep only
    the journey dates in [start, end] (inclusive; `end` defaults to `start`).

    The archive is a single compressed stream, so a date range still reads the whole
    file; it only shrinks the output (useful for quick end-to-end tests).
    """
    archive = source_dir / ARCHIVE_TEMPLATE.format(year=year)
    if not archive.exists():
        raise FileNotFoundError(f"Archive not found: {archive}")
    if not pass_file.exists():
        raise FileNotFoundError(f"Password file not found: {pass_file}")

    days = _day_strings(start, end) if start else None
    out_path = out_path or interim_path(year, start, end)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir_for(out_path)

    log.info("Ingesting %s%s -> %s", archive.name, f" ({len(days)} days from {start})" if days else "", out_path)

    proc = _open_stream(archive, pass_file)
    rows_in = rows_out = 0
    try:
        reader = pd.read_csv(
            proc.stdout,
            encoding=ENCODING,
            usecols=list(SCHEMA.names),
            dtype=_PANDAS_DTYPES,
            chunksize=CHUNK_ROWS,
            low_memory=False,
        )
        for i, chunk in enumerate(reader):
            rows_in += len(chunk)
            chunk = _filter_chunk(chunk, days)
            rows_out += len(chunk)
            if len(chunk):
                pq.write_to_dataset(
                    pa.Table.from_pandas(chunk, schema=SCHEMA, preserve_index=False),
                    tmp_path,
                    partition_cols=["RejseDato"],
                    basename_template=f"chunk{i:05d}-{{i}}.parquet",
                    compression="zstd",
                )
            log.info("  read %d rows, kept %d", rows_in, rows_out)
        stderr = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"Decrypt/untar failed (wrong password or corrupt archive?): {stderr}")
    except BaseException as exc:
        proc.kill()
        proc.wait()
        shutil.rmtree(tmp_path, ignore_errors=True)
        if isinstance(exc, pd.errors.EmptyDataError):
            stderr = proc.stderr.read().decode(errors="replace")
            raise RuntimeError(f"No data from archive (wrong password?): {stderr}") from exc
        raise

    if rows_out == 0:
        shutil.rmtree(tmp_path, ignore_errors=True)
        raise ValueError(f"No rows kept ({rows_in} read). Check REGION_COL/REGION_VALUE and the day format.")

    publish_dir(tmp_path, out_path)
    log.info("Done: kept %d of %d rows", rows_out, rows_in)
    return out_path


def add_span_args(parser: argparse.ArgumentParser) -> None:
    """--day, or --start/--end (inclusive): restrict to some journey dates, for testing."""
    parser.add_argument("--day", type=dt.date.fromisoformat, help="a single day (YYYY-MM-DD)")
    parser.add_argument("--start", type=dt.date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--end", type=dt.date.fromisoformat, help="last day, inclusive (YYYY-MM-DD)")


def parse_span(parser: argparse.ArgumentParser, args: argparse.Namespace) -> tuple[dt.date | None, dt.date | None]:
    if args.day and (args.start or args.end):
        parser.error("use either --day or --start/--end")
    if args.end and not args.start:
        parser.error("--end needs --start")
    if args.day:
        return args.day, args.day
    return args.start, args.end or args.start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2019)
    add_span_args(parser)
    args = parser.parse_args()
    ingest_year(args.year, *parse_span(parser, args))


if __name__ == "__main__":
    main()
