"""Locations for the ML code, read from the environment (docs/10-cloud.md).

Thin wrappers over ``src.common.config.Settings`` (owned by P1), so there is one
source of truth for ``DATA_DIR`` and ``ARTIFACT_URI`` and no absolute path in code.
"""

from pathlib import Path

from src.common.config import Settings


def data_dir() -> Path:
    """Root for raw data, profiles and labels. Default ``./data``."""
    return Path(Settings.from_env().data_dir)


def artifact_uri() -> str:
    """Where models and evaluation outputs go: a path or an ``s3://`` URI."""
    return Settings.from_env().artifact_uri
