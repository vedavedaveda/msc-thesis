"""CLI: build one experiment's dataset.

    uv run python -m msc_thesis.data.build zero_shot
    uv run python -m msc_thesis.data.build zero_shot --set start_date=2017-04-01 --set n_stations=100

`--set KEY=VALUE` overrides a config entry; VALUE is parsed as YAML.
"""

import argparse

from msc_thesis.data.builders import REGISTRY
from msc_thesis.data.builders.base import load_config
from msc_thesis.utils.yaml_config import add_override_arg, apply_overrides


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=sorted(REGISTRY))
    add_override_arg(parser)
    args = parser.parse_args()

    cfg = apply_overrides(parser, load_config(args.experiment), args.overrides)

    out_dir = REGISTRY[args.experiment](cfg)
    print(f"Wrote {args.experiment} data to {out_dir}")


if __name__ == "__main__":
    main()
