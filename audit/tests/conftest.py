"""Shared fixtures for the audit tests. Data-dependent tests skip when the local data is absent.

    .venv/bin/python -m pytest audit/tests -q

Nothing here reads the sealed 2012-13 file or the test period.
"""

from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
RAW_2011 = DATA / "raw" / "ausgrid" / "Solar home 2011-2012.csv"


@pytest.fixture(autouse=True)
def _repo_env(monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(DATA))
    monkeypatch.setenv("ARTIFACT_URI", str(REPO / "artifacts"))
    from src.ml import model_io

    model_io.clear_caches()


def need(path: Path):
    if not path.exists():
        pytest.skip(f"needs local data: {path.relative_to(REPO)}")


@pytest.fixture(scope="session")
def labels_a():
    need(DATA / "labels" / "A" / "labels.parquet")
    return (
        pd.read_parquet(DATA / "labels" / "A" / "labels.parquet")
        .sort_values("interval_start")
        .reset_index(drop=True)
    )


@pytest.fixture(scope="session")
def houses_a():
    need(DATA / "labels" / "A" / "station_houses.parquet")
    return pd.read_parquet(DATA / "labels" / "A" / "station_houses.parquet")


@pytest.fixture(scope="session")
def station_profiles(houses_a):
    need(DATA / "profiles.parquet")
    return pd.read_parquet(
        DATA / "profiles.parquet",
        columns=["interval_start", "house_id", "gc_kw", "cl_kw", "gg_kw"],
        filters=[("house_id", "in", houses_a["source_house_id"].tolist())],
    )
