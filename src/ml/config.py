"""Locations for the ML code, read from the environment (docs/10-cloud.md).

Thin wrappers over ``src.common.config.Settings`` (owned by P1), so there is one
source of truth for ``DATA_DIR`` and ``ARTIFACT_URI`` and no absolute path in code.
"""

import os
from pathlib import Path

from src.common.config import Settings

SYDNEY = "Australia/Sydney"


def data_dir() -> Path:
    """Root for raw data, profiles and labels. Default ``./data``."""
    return Path(Settings.from_env().data_dir)


def profiles_path() -> Path:
    """The cleaned per-house profiles written by ``python -m src.ml.data profiles``."""
    return data_dir() / "profiles.parquet"


def artifact_uri() -> str:
    """Where models and evaluation outputs go: a path or an ``s3://`` URI."""
    return Settings.from_env().artifact_uri


def violation_target() -> float:
    """Share of daylight intervals that may violate the safe limit on validation (task 08).

    ``VIOLATION_TARGET``, default 0.02: the level the exploration reached with a fallback.
    The team confirms the number; it is stored in every model's metadata.
    """
    return float(os.environ.get("VIOLATION_TARGET", "0.02"))


def crew_cases_per_day() -> int:
    """How many "not sure" cases a crew can check per day (``CREW_CASES_PER_DAY``)."""
    return int(os.environ.get("CREW_CASES_PER_DAY", "20"))
