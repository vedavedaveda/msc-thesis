"""Registry of dataset builders, one per experiment data format.

To add a format: write a `build_<name>(cfg) -> Path` in its own module,
add a configs/<name>.yaml, and register it below.
"""

from msc_thesis.data.builders.base import Builder
from msc_thesis.data.builders.zero_shot import build_zero_shot

REGISTRY: dict[str, Builder] = {
    "zero_shot": build_zero_shot,
}
