"""CLI: build one experiment's dataset.

    uv run python -m msc_thesis.data.build zero_shot
"""

import argparse

from msc_thesis.data.builders import REGISTRY
from msc_thesis.data.builders.base import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=sorted(REGISTRY))
    args = parser.parse_args()

    out_dir = REGISTRY[args.experiment](load_config(args.experiment))
    print(f"Wrote {args.experiment} data to {out_dir}")


if __name__ == "__main__":
    main()
