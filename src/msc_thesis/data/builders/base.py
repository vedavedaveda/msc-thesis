"""Shared contract for experiment-specific dataset builders.

A builder turns the canonical interim tables (data/interim/) into the format one
experiment needs, writes parquet to data/processed/<experiment>/, and returns
that directory.
"""

from pathlib import Path
from typing import Callable

from msc_thesis.utils.yaml_config import Config, load_config

__all__ = ["Builder", "Config", "load_config"]

Builder = Callable[[Config], Path]
