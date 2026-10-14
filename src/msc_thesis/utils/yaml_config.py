"""YAML configs in configs/ and the `--set KEY=VALUE` overrides shared by the CLIs."""

import argparse
from typing import Any

import yaml

from msc_thesis.utils.paths import CONFIGS_DIR

Config = dict[str, Any]


def load_config(name: str) -> Config:
    """Load configs/<name>.yaml."""
    with open(CONFIGS_DIR / f"{name}.yaml") as f:
        return yaml.safe_load(f)


def add_override_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE",
                        help="override a config entry; VALUE is parsed as YAML")


def apply_overrides(parser: argparse.ArgumentParser, cfg: Config, overrides: list[str]) -> Config:
    """Apply `--set KEY=VALUE` items to `cfg` in place; unknown keys are a usage error."""
    for item in overrides:
        key, sep, value = item.partition("=")
        if not sep or key not in cfg:
            parser.error(f"--set expects KEY=VALUE with a key from the config ({sorted(cfg)}), got {item!r}")
        cfg[key] = yaml.safe_load(value)
    return cfg
