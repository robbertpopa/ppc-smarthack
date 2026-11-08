from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.common.config import Settings
from src.pricing import prices
from src.pricing.source import MOCK_CURVE_EUR_MWH, PriceSource, mock_source, price_source_for


def year(y=2025):
    idx = pd.date_range(f"{y}-01-01", f"{y + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    hour = idx.tz_convert("Europe/Bucharest").hour
    price = np.where((hour >= 10) & (hour < 16), 40.0, 140.0)
    return pd.Series(price, index=idx)


def test_mock_source_follows_the_bucharest_clock():
    noon_bucharest = datetime(2025, 6, 21, 9, 0, tzinfo=timezone.utc)  # 12:00 in summer
    assert mock_source().wholesale(noon_bucharest) == MOCK_CURVE_EUR_MWH[12]
    assert mock_source().mock is True


def test_real_prices_win_over_the_profile_when_the_hour_is_known():
    series = year()
    series.loc["2025-06-21 10:00:00+00:00"] = 77.0
    source = PriceSource(prices.profile(series), series)
    assert source.wholesale(datetime(2025, 6, 21, 10, 30, tzinfo=timezone.utc)) == 77.0
    other_year = datetime(2012, 6, 21, 10, 30, tzinfo=timezone.utc)
    assert source.wholesale(other_year) is not None  # falls back to the (month, hour) profile
    assert source.mock is False


def test_the_adder_is_positive_when_midday_is_cheap():
    source = PriceSource(prices.profile(year()))
    assert source.adder(datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)) > 30
    assert mock_source().adder(datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)) > 0


def test_day_curve_has_24_utc_hours():
    curve = mock_source().day_curve(datetime(2025, 6, 21, 13, 0, tzinfo=timezone.utc))
    assert len(curve) == 24 and curve[0]["ts"].startswith("2025-06-21T00:00:00")
    assert all(c["wholesale_eur_mwh"] is not None for c in curve)


def test_settings_pick_mock_or_data(tmp_path):
    assert price_source_for(Settings(source="mock", data_dir=str(tmp_path))).mock is True
    assert price_source_for(Settings(source="model", data_dir=str(tmp_path))).mock is True
    prices.save(year(), prices.prices_path(str(tmp_path)))
    assert price_source_for(Settings(source="model", data_dir=str(tmp_path))).mock is False


def test_a_partial_year_is_refused(tmp_path):
    prices.save(year()[:2000], prices.prices_path(str(tmp_path)))
    with pytest.raises(ValueError):
        price_source_for(Settings(source="model", data_dir=str(tmp_path)))
