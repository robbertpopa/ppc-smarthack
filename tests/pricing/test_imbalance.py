import pandas as pd
import pytest

from src.pricing import imbalance


def series(values):
    idx = pd.date_range("2025-06-21", periods=len(values), freq="30min", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def test_volume_is_the_absolute_gap_in_mwh():
    actual, forecast = series([1000, 2000, 3000]), series([1500, 2000, 2000])
    # |500| + 0 + |1000| = 1500 kW * 0.5 h = 750 kWh = 0.75 MWh
    assert imbalance.volume_mwh(actual, forecast) == pytest.approx(0.75)


def test_saving_is_zero_for_equal_forecasts_and_positive_for_a_better_one():
    actual = series([1000, 2000, 3000, 2000])
    baseline = series([2000, 1000, 3000, 3000])
    same = imbalance.saving(actual, baseline, baseline, 60.0)
    assert same["saving_eur"] == 0.0
    better = imbalance.saving(actual, baseline, actual, 60.0)
    assert better["model_mwh"] == 0.0
    assert better["baseline_mwh"] == pytest.approx((1000 + 1000 + 0 + 1000) * 0.5 / 1000)
    assert better["saving_eur"] == pytest.approx(better["baseline_cost_eur"])
    assert better["baseline_cost_eur"] == pytest.approx(better["baseline_mwh"] * 60.0)


def test_only_common_intervals_count():
    actual = series([1000, 1000, 1000])
    baseline = series([0, 0, 0])
    model = series([0, 0, 0]).iloc[1:]
    out = imbalance.saving(actual, baseline, model, 10.0)
    assert out["n_intervals"] == 2


def test_the_bonus_is_a_share_of_a_positive_saving_only():
    assert imbalance.split_saving(100.0, 0.5) == (50.0, 50.0)
    assert imbalance.split_saving(-40.0, 0.5) == (0.0, -40.0)
