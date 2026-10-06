"""Filesystem locations. Import from here, never hardcode data paths."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

CONFIGS_DIR = PROJECT_ROOT / "configs"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"

# Server-side location of the encrypted Rejsekort archives and their password file.
ENCRYPTED_DIR = Path("/mnt/raid/data_sortedmob/RKD/RawFiles/encrypted")
PASS_FILE = Path.home() / ".rkd_pass"


def processed_dir(experiment: str) -> Path:
    """Output folder for one experiment's model-ready data (created if missing)."""
    path = PROCESSED_DIR / experiment
    path.mkdir(parents=True, exist_ok=True)
    return path
