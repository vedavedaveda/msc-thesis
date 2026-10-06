"""Shared contract for experiment-specific dataset builders.

A builder turns the canonical interim tables (data/interim/) into the format one
experiment needs, writes parquet to data/processed/<experiment>/, and returns
that directory.
"""

from pathlib import Path
from typing import Any, Callable

import yaml

from msc_thesis.utils.paths import CONFIGS_DIR

Config = dict[str, Any]
Builder = Callable[[Config], Path]


def load_config(name: str) -> Config:
    """Load configs/<name>.yaml."""
    with open(CONFIGS_DIR / f"{name}.yaml") as f:
        return yaml.safe_load(f)
