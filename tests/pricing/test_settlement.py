import numpy as np
import pandas as pd
import pytest

from src.pricing.config import PricingConfig
from src.pricing.settlement import settle


def test_settlement_by_hand():
    idx = pd.date_range("2025-01-01", periods=3, freq="30min", tz="UTC")
    kwh = pd.Series([1000.0, 2000.0, 4000.0], index=idx)
    wholesale = pd.Series([100.0, 200.0, np.nan], index=idx)
    monthly = pd.Series(150.0, index=idx)
    adder = pd.Series(40.0, index=idx)
    out = settle(kwh, wholesale, monthly, adder, PricingConfig(fee_eur_mwh=30.0))
    assert out["exported_kwh"] == 3000.0 and out["n_without_price"] == 1
    assert out["regulated_eur"] == pytest.approx(3 * 150.0)
    assert out["hourly_eur"] == pytest.approx(1 * 70.0 + 2 * 170.0)
    assert out["adder_eur"] == pytest.approx(3 * 40.0)
    assert out["paid_eur"] == pytest.approx(out["hourly_eur"] + out["adder_eur"])
    assert out["value_eur"] == pytest.approx(1 * 100.0 + 2 * 200.0)
    assert out["ppc_margin_regulated_eur"] == pytest.approx(500.0 - 450.0)
    assert out["ppc_margin_paid_eur"] == pytest.approx(500.0 - out["paid_eur"])


def test_empty_series_settles_to_zero():
    idx = pd.DatetimeIndex([], tz="UTC")
    empty = pd.Series([], index=idx, dtype=float)
    out = settle(empty, empty, empty, empty)
    assert out["exported_kwh"] == 0.0 and out["paid_eur"] == 0.0
