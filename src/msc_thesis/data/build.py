"""CLI: build one experiment's dataset.

    uv run python -m msc_thesis.data.build zero_shot
    uv run python -m msc_thesis.data.build zero_shot --set start_date=2019-01-01 --set end_date=2019-06-30

`--set KEY=VALUE` overrides a config entry; VALUE is parsed as YAML.
"""

import argparse

import yaml

from msc_thesis.data.builders import REGISTRY
from msc_thesis.data.builders.base import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=sorted(REGISTRY))
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args()

    cfg = load_config(args.experiment)
    for item in args.overrides:
        key, sep, value = item.partition("=")
        if not sep or key not in cfg:
            parser.error(f"--set expects KEY=VALUE with a key from the config ({sorted(cfg)}), got {item!r}")
        cfg[key] = yaml.safe_load(value)

    out_dir = REGISTRY[args.experiment](cfg)
    print(f"Wrote {args.experiment} data to {out_dir}")


if __name__ == "__main__":
    main()
