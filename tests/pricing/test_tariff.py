import numpy as np
import pandas as pd
import pytest

from src.pricing.config import PricingConfig
from src.pricing.tariff import hourly_price, hourly_price_series


def test_hourly_price_is_wholesale_minus_fee_with_a_floor():
    cfg = PricingConfig(fee_eur_mwh=30.0, floor_eur_mwh=0.0)
    assert hourly_price(100.0, cfg) == 70.0
    assert hourly_price(20.0, cfg) == 0.0  # fee would push it below zero: floor applies
    assert hourly_price(-50.0, cfg) == 0.0
    assert hourly_price(20.0, PricingConfig(fee_eur_mwh=30.0, floor_eur_mwh=5.0)) == 5.0


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        hourly_price(float("nan"))
    for bad in ({"fee_eur_mwh": -1}, {"floor_eur_mwh": -1}, {"bonus_share": 1.5}):
        with pytest.raises(ValueError):
            PricingConfig(**bad)


def test_series_matches_scalar_and_keeps_gaps():
    wholesale = pd.Series([100.0, -5.0, np.nan, 20.0])
    out = hourly_price_series(wholesale)
    assert out.iloc[0] == hourly_price(100.0) and out.iloc[1] == 0.0
    assert np.isnan(out.iloc[2]) and out.iloc[3] == 0.0
