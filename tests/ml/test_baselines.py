import numpy as np
import pandas as pd
import pytest

from src.ml import baselines

STEP = pd.Timedelta(minutes=30)


def labels_for(times, shares):
    return pd.DataFrame({"interval_start": pd.DatetimeIndex(times), "safe_share": shares})


@pytest.fixture
def two_days():
    index = pd.date_range("2012-01-10 00:00", periods=96, freq="30min", tz="UTC")
    return labels_for(index, np.linspace(0.1, 0.9, 96))


def test_fixed_is_constant(two_days):
    assert (baselines.apply("fixed", two_days) == 0.36).all()


def test_last_known_is_the_interval_ending_at_the_decision_time(two_days):
    got = baselines.apply("last_known", two_days)
    # target row 10: decision 60 min earlier, last interval started 90 min before the target
    assert got.iloc[10] == two_days["safe_share"].iloc[7]
    assert (got.iloc[:3] == 0.36).all()  # no history yet: fallback


def test_same_hour_yesterday_looks_back_24_hours(two_days):
    got = baselines.apply("same_hour_yesterday", two_days)
    assert got.iloc[60] == two_days["safe_share"].iloc[12]
    assert (got.iloc[:48] == 0.36).all()


def test_missing_history_falls_back_instead_of_closing_the_gap(two_days):
    gap = two_days.drop(index=7)
    got = baselines.apply("last_known", gap).set_axis(gap["interval_start"])
    assert got.loc[two_days["interval_start"].iloc[10]] == 0.36


def test_a_null_share_in_history_also_falls_back(two_days):
    two_days.loc[7, "safe_share"] = np.nan
    assert baselines.apply("last_known", two_days).iloc[10] == 0.36


def test_oracle_is_the_label_itself_and_keeps_nulls(two_days):
    two_days.loc[5, "safe_share"] = np.nan
    got = baselines.apply("oracle", two_days)
    assert np.isnan(got.iloc[5]) and got.iloc[6] == two_days["safe_share"].iloc[6]


def test_unknown_name_is_rejected(two_days):
    with pytest.raises(ValueError, match="unknown baseline"):
        baselines.apply("magic", two_days)


def test_table_has_a_row_per_baseline_and_fixed_is_100():
    start = pd.Timestamp("2012-01-10 01:00", tz="UTC")
    index = pd.date_range(start, periods=6, freq="30min")
    labels = labels_for(index, [0.5, 0.5, 0.4, 0.4, 0.6, 0.6])
    surplus = pd.DataFrame({"H1": [2.0] * 6}, index=pd.DatetimeIndex(index, name="interval_start"))
    out = baselines.table(labels, surplus, pd.Series({"H1": 4.0}))
    assert list(out.index) == list(baselines.NAMES)
    assert out.loc["fixed", "export_index"] == pytest.approx(100.0)
    assert out.loc["oracle", "violation_rate"] == 0.0
