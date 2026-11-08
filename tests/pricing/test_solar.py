import numpy as np
import pandas as pd
import pytest

from src.pricing import prices, solar


def table_from(hourly_by_month):
    index = pd.MultiIndex.from_product([range(1, 13), range(24)], names=["month", "hour"])
    return pd.Series([hourly_by_month(m, h) for m, h in index], index=index, dtype=float)


def test_weights_sum_to_one_and_peak_at_midday():
    for month in (1, 6, 12):
        w = solar.solar_weights(month)
        assert w.sum() == pytest.approx(1.0) and (w >= 0).all()
        assert 12 <= int(np.argmax(w)) <= 14
        assert w[:4].sum() == 0 and w[-3:].sum() == 0  # night
    assert solar.solar_weights(6).nonzero()[0].size > solar.solar_weights(12).nonzero()[0].size


def test_flat_prices_give_no_adder():
    adder = solar.monthly_adder(table_from(lambda m, h: 100.0))
    assert adder.shape == (12,) and np.allclose(adder, 0.0)


def test_cheap_midday_gives_a_positive_adder_and_dear_midday_none():
    duck = table_from(lambda m, h: 30.0 if 10 <= h < 16 else 150.0)
    assert (solar.monthly_adder(duck) > 30).all()
    inverted = table_from(lambda m, h: 200.0 if 10 <= h < 16 else 100.0)
    assert (solar.monthly_adder(inverted) == 0.0).all()  # floored at zero


def test_adder_on_the_price_year_helper():
    idx = pd.date_range("2025-01-01", "2026-01-01", freq="h", tz="UTC", inclusive="left")
    series = pd.Series(100.0, index=idx)
    assert (solar.monthly_adder(prices.profile(series)) == 0).all()
