"""Small filesystem helpers."""

import shutil
from pathlib import Path


def tmp_dir_for(path: Path) -> Path:
    """Fresh, empty sibling directory used to build `path` before publishing it."""
    tmp = path.with_name(path.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    return tmp


def publish_dir(tmp: Path, final: Path) -> None:
    """Replace `final` with the finished `tmp` directory, so readers never see a partial one."""
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
