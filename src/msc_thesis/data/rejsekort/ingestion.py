"""Rejsekort ingestion: encrypted server archive -> interim parquet.

Streams the archive (decrypt -> untar -> CSV) in chunks, keeps only the columns
and rows we need, and appends each chunk to a parquet file. Nothing decrypted is
written to disk and the full year is never held in memory.

    uv run python -m msc_thesis.data.rejsekort.ingestion --year 2019
    uv run python -m msc_thesis.data.rejsekort.ingestion --year 2019 --day 2019-03-05
"""

import argparse
import datetime as dt
import shlex
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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
        # Event code per row, e.g. "Fi", "Cc". Not yet mapped to check-in/out:
        # TODO(veda): derive `Check_type` in cleaning once the codes are understood.
        ("Model", pa.string()),
        ("turtype", pa.string()),  # trip pattern, e.g. "FiCc"
        ("ModalKomb", pa.string()),
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


def interim_path(year: int, day: dt.date | None = None) -> Path:
    name = f"rejsekort_{day.isoformat()}" if day else f"rejsekort_{year}"
    return INTERIM_DIR / "rejsekort" / f"{name}.parquet"


def _open_stream(archive: Path, pass_file: Path) -> subprocess.Popen:
    """Decrypt + decompress into a pipe; nothing is written to disk."""
    cmd = (
        f"openssl enc -d -aes-256-cbc -salt -pbkdf2 "
        f"-in {shlex.quote(str(archive))} -pass file:{shlex.quote(str(pass_file))} | tar xzO"
    )
    return subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _filter_chunk(chunk: pd.DataFrame, day_str: str | None) -> pd.DataFrame:
    chunk = chunk[chunk[REGION_COL] == REGION_VALUE]
    if day_str is not None:
        chunk = chunk[chunk["RejseDato"].str.upper() == day_str]
    return chunk


def ingest_year(
    year: int,
    day: dt.date | None = None,
    source_dir: Path = ENCRYPTED_DIR,
    pass_file: Path = PASS_FILE,
    out_path: Path | None = None,
) -> Path:
    """Ingest one year's archive into interim parquet; optionally keep one day only.

    The archive is a single compressed stream, so `day` still reads the whole file;
    it only shrinks the output (useful for quick end-to-end tests).
    """
    archive = source_dir / ARCHIVE_TEMPLATE.format(year=year)
    if not archive.exists():
        raise FileNotFoundError(f"Archive not found: {archive}")
    if not pass_file.exists():
        raise FileNotFoundError(f"Password file not found: {pass_file}")

    out_path = out_path or interim_path(year, day)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".parquet.tmp")
    day_str = day.strftime(_REJSEDATO_FORMAT).upper() if day else None

    log.info("Ingesting %s%s -> %s", archive.name, f" (day {day})" if day else "", out_path)

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
        with pq.ParquetWriter(tmp_path, SCHEMA, compression="zstd") as writer:
            for chunk in reader:
                rows_in += len(chunk)
                chunk = _filter_chunk(chunk, day_str)
                rows_out += len(chunk)
                writer.write_table(pa.Table.from_pandas(chunk, schema=SCHEMA, preserve_index=False))
                log.info("  read %d rows, kept %d", rows_in, rows_out)
        stderr = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"Decrypt/untar failed (wrong password or corrupt archive?): {stderr}")
    except BaseException as exc:
        proc.kill()
        proc.wait()
        tmp_path.unlink(missing_ok=True)
        if isinstance(exc, pd.errors.EmptyDataError):
            stderr = proc.stderr.read().decode(errors="replace")
            raise RuntimeError(f"No data from archive (wrong password?): {stderr}") from exc
        raise

    if rows_out == 0:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(f"No rows kept ({rows_in} read). Check REGION_COL/REGION_VALUE and the day format.")

    tmp_path.replace(out_path)
    log.info("Done: kept %d of %d rows", rows_out, rows_in)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2019)
    parser.add_argument("--day", type=dt.date.fromisoformat, help="keep a single day (YYYY-MM-DD), for testing")
    args = parser.parse_args()
    ingest_year(args.year, args.day)


if __name__ == "__main__":
    main()
