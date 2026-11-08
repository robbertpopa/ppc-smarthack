import inspect
import math

import numpy as np
import pandas as pd
import pytest

from src.grid.battery import step
from src.pricing.battery import BatteryParams, battery_houses, dispatch

FEE = 30.0


def frame(days=2, surplus_kw=6.0, cap_kw=4.0):
    idx = pd.date_range("2025-06-21 00:00", periods=48 * days, freq="30min", tz="Australia/Sydney")
    idx = idx.tz_convert("UTC")
    hour = idx.tz_convert("Australia/Sydney").hour
    surplus = pd.Series(np.where((hour >= 9) & (hour < 16), surplus_kw, 0.0), index=idx)
    price = pd.Series(np.where((hour >= 18) & (hour < 22), 200.0, 40.0), index=idx)
    cap = pd.Series(cap_kw, index=idx)
    active = pd.Series(True, index=idx)
    return price, surplus, cap, active


def plain(surplus, cap):
    return np.minimum(surplus, cap)


def test_defaults_match_the_grid_battery_model():
    defaults = {k: v.default for k, v in inspect.signature(step).parameters.items()}
    p = BatteryParams()
    assert (p.capacity_kwh, p.min_soc_kwh) == (defaults["capacity_kwh"], defaults["min_soc_kwh"])
    assert p.max_power_kw == defaults["max_power_kw"]
    assert p.roundtrip_efficiency == defaults["roundtrip_efficiency"]


def test_never_exceeds_cap_or_power_and_is_empty_each_night():
    price, surplus, cap, active = frame()
    out = dispatch(price, surplus, cap, active, FEE)
    assert (out["export_kw"] <= cap + 1e-9).all()
    assert out["battery_kw"].abs().max() <= 5.0 + 1e-9
    day = out.index.tz_convert("Australia/Sydney").date
    charged = out["battery_kw"].clip(lower=0).groupby(day).sum() * 0.5
    sold = (-out["battery_kw"]).clip(lower=0).groupby(day).sum() * 0.5
    assert (charged > 0).all()
    assert np.allclose(sold, 0.9 * charged)  # everything stored is sold, minus the loss
    assert (charged * math.sqrt(0.9) <= 9.0 + 1e-6).all()  # within the usable 9 kWh


def test_stores_at_midday_and_sells_in_the_evening():
    price, surplus, cap, active = frame()
    out = dispatch(price, surplus, cap, active, FEE)
    assert (out["battery_kw"][surplus > 0] > 0).any()
    evening = out[price > 100]
    assert (evening["battery_kw"] < 0).any() and (evening["export_kw"] > 0).any()


def test_earns_more_than_no_battery_and_keeps_energy_balance():
    price, surplus, cap, active = frame()
    out = dispatch(price, surplus, cap, active, FEE)
    base = plain(surplus, cap) * 0.5
    with_battery = out["export_kw"] * 0.5
    assert (with_battery * price).sum() > (base * price).sum()
    assert with_battery.sum() <= surplus.sum() * 0.5 + 1e-9


def test_stores_what_the_cap_would_waste_even_at_a_low_evening_price():
    price, surplus, cap, active = frame(days=1, surplus_kw=6.0, cap_kw=2.0)
    price[:] = 40.0
    price[(price.index.tz_convert("Australia/Sydney").hour >= 18)] = 80.0
    out = dispatch(price, surplus, cap, active, FEE)
    assert out["export_kw"].sum() * 0.5 > plain(surplus, cap).sum() * 0.5


def test_idle_when_the_agent_fell_back_and_when_nothing_pays():
    price, surplus, cap, active = frame()
    out = dispatch(price, surplus, cap, active & False, FEE)
    assert (out["battery_kw"] == 0).all()
    assert np.allclose(out["export_kw"], plain(surplus, cap))
    flat = price * 0 + 100.0
    idle = dispatch(flat, surplus, pd.Series(10.0, index=price.index), active, FEE)
    assert (idle["battery_kw"] == 0).all()  # round-trip loss makes shifting a loss


def test_inputs_must_share_an_index_and_houses_are_a_fixed_choice():
    price, surplus, cap, active = frame()
    with pytest.raises(ValueError):
        dispatch(price, surplus.iloc[1:], cap, active, FEE)
    assert battery_houses(["H03", "H01", "H02", "H04"]) == ["H01", "H02"]
