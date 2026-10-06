"""Builder for the zero-shot Chronos-2 experiment.

Reads canonical interim tables, writes Chronos-2-ready parquet to
data/processed/zero_shot/.
"""

from pathlib import Path

from msc_thesis.data.builders.base import Config
from msc_thesis.utils.paths import processed_dir


def build_zero_shot(cfg: Config) -> Path:
    out_dir = processed_dir("zero_shot")
    # TODO: read INTERIM_DIR tables, shape per cfg, write parquet to out_dir.
    raise NotImplementedError("zero_shot builder not implemented yet")
