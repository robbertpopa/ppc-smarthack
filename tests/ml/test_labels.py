import numpy as np
import pandas as pd
import pytest

from src.ml import labels
from src.ml.config import data_dir


def tiny_profiles(n_houses=35, days=3):
    """A few days of profiles for more houses than a mock station needs."""
    index = pd.date_range("2011-01-10 00:00", periods=48 * days, freq="30min", tz="UTC")
    rows = []
    for h in range(n_houses):
        sun = np.clip(np.sin((index.hour + index.minute / 60 - 20) / 24 * 2 * np.pi), 0, None)
        rows.append(
            pd.DataFrame(
                {
                    "house_id": f"AG-{h + 1:04d}",
                    "interval_start": index,
                    "gc_kw": 0.4 + 0.01 * h,
                    "cl_kw": np.nan if h % 2 else 0.2,
                    "gg_kw": 1.5 * sun,
                    "kwp": 2.0,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


@pytest.fixture
def mock():
    return labels.make_mock(tiny_profiles(), "A")


def test_mock_passes_validation_and_is_flagged_mock(mock):
    labels.validate(mock)
    assert labels.is_mock(mock)
    assert (mock["pt_id"] == "PT-A").all()
    assert mock["safe_share"].between(0.05, 1).all()


def test_mock_is_deterministic_and_seed_dependent():
    profiles = tiny_profiles()
    assert labels.make_mock(profiles, "A", seed=0).equals(labels.make_mock(profiles, "A", seed=0))
    assert not labels.make_mock(profiles, "A", seed=0).equals(
        labels.make_mock(profiles, "A", seed=1)
    )


def test_mock_without_profiles_uses_a_synthetic_station():
    mock = labels.make_mock(None, "B")
    labels.validate(mock)
    assert (mock["pt_id"] == "PT-B").all()
    assert mock["interval_start"].min() >= pd.Timestamp("2010-06-30", tz="UTC")


def test_mock_marks_missing_totals_as_not_converged():
    profiles = tiny_profiles()
    noon = pd.Timestamp("2011-01-10 02:00", tz="UTC")  # midday in Sydney, sun is up
    profiles.loc[profiles["interval_start"] == noon, "gg_kw"] = np.nan  # every house missing
    mock = labels.make_mock(profiles, "A")
    labels.validate(mock)
    row = mock[mock["interval_start"] == noon].iloc[0]
    assert pd.isna(row["safe_share"]) and not row["converged"] and pd.isna(row["pv_kw"])
    assert mock["converged"].sum() == len(mock) - 1


def test_mock_station_houses_match_the_labels(mock):
    _, houses = labels.make_mock_with_houses(tiny_profiles(), "A")
    assert list(houses.columns) == list(labels.HOUSE_COLUMNS)
    assert len(houses) == labels.MOCK_HOUSES
    assert houses["kwp"].sum() == pytest.approx(mock["kwp_total"].iloc[0])


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError, match="unknown scenario"):
        labels.make_mock(None, "Z")


def test_validate_rejects_a_duplicate_row(mock):
    with pytest.raises(ValueError, match="duplicate"):
        labels.validate(pd.concat([mock, mock.iloc[:1]], ignore_index=True))


def test_validate_rejects_a_share_above_one(mock):
    mock.loc[0, "safe_share"] = 1.2
    with pytest.raises(ValueError, match="outside"):
        labels.validate(mock)


def test_validate_rejects_a_naive_timestamp(mock):
    mock["interval_start"] = mock["interval_start"].dt.tz_localize(None)
    with pytest.raises(ValueError, match="interval_start must be a UTC"):
        labels.validate(mock)


def test_validate_rejects_a_local_timestamp(mock):
    mock["interval_start"] = mock["interval_start"].dt.tz_convert("Australia/Sydney")
    with pytest.raises(ValueError, match="UTC"):
        labels.validate(mock)


def test_validate_rejects_a_number_on_a_non_converged_row(mock):
    mock.loc[0, "converged"] = False
    with pytest.raises(ValueError, match="converged is false"):
        labels.validate(mock)


def test_validate_lists_every_problem(mock):
    mock.loc[0, "safe_share"] = 1.2
    mock.loc[1, "binding"] = "wind"
    mock.loc[2, "available_at"] += pd.Timedelta(hours=1)
    with pytest.raises(ValueError) as err:
        labels.validate(mock)
    for part in ("outside", "binding", "available_at"):
        assert part in str(err.value)


def test_validate_reports_missing_columns(mock):
    with pytest.raises(ValueError, match="missing columns"):
        labels.validate(mock.drop(columns=["pt_id"]))


def test_is_mock_is_false_for_real_labels(mock):
    mock["source_ref"] = "grid/labels.py@abc1234"
    assert not labels.is_mock(mock)


def test_cli_writes_a_mock_file_and_load_reads_it(tmp_path, monkeypatch, capsys):
    pytest.importorskip("pyarrow")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    tiny_profiles().to_parquet(tmp_path / "profiles.parquet")
    labels.main(["mock", "--scenario", "A"])
    assert "MOCK" in capsys.readouterr().out
    loaded = labels.load("A")
    assert labels.is_mock(loaded)
    assert loaded["interval_start"].is_monotonic_increasing
    assert len(labels.load_station_houses("A")) == labels.MOCK_HOUSES
    assert data_dir() == tmp_path


def test_load_names_the_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="labels.parquet"):
        labels.load("A")
