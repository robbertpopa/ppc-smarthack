"""S1: the grid reader feeds the power flow readings that the ML cleaning removed."""

import numpy as np
import pandas as pd
import pytest

from audit.proposals import parser_parity
from audit.tests.conftest import DATA, RAW_2011, need

SYD = "Australia/Sydney"
DST_DAYS = {pd.Timestamp("2011-10-02"), pd.Timestamp("2012-04-01")}


@pytest.fixture(scope="module")
def raw():
    need(RAW_2011)
    return parser_parity.read_raw(RAW_2011)


@pytest.fixture(scope="module")
def profiles_2011():
    need(DATA / "profiles.parquet")
    p = pd.read_parquet(DATA / "profiles.parquet")
    start = pd.Timestamp("2011-07-01", tz=SYD).tz_convert("UTC")
    return p[p["interval_start"] >= start]


def test_on_a_normal_day_both_readers_agree(raw, profiles_2011):
    customers = list(range(1, 31))
    date = "2011-11-15"
    g_load, g_pv = parser_parity.grid_style_day(raw, date, customers)
    p_load, p_pv = parser_parity.day_from_profiles(profiles_2011, date, customers)
    assert g_load.shape == p_load.shape == (48, 30)
    assert parser_parity.differences(g_load, p_load) == 0
    assert parser_parity.differences(g_pv, p_pv) == 0  # so the fix is a drop-in


def test_over_limit_generation_reaches_the_power_flow(raw, profiles_2011):
    p = profiles_2011
    nulled = p[p["gg_kw"].isna() & p["gc_kw"].notna()].copy()
    local = nulled["interval_start"].dt.tz_convert(SYD)
    nulled["date"] = local.dt.tz_localize(None).dt.normalize()
    nulled = nulled[~nulled["date"].isin(DST_DAYS)]
    assert len(nulled) > 0, "expected readings removed by the 1.2 x kWp rule"
    row = nulled.iloc[0]
    customer = int(row["house_id"][3:])
    g_load, g_pv = parser_parity.grid_style_day(raw, row["date"], [customer])
    slot = int(
        (row["interval_start"].tz_convert(SYD) - pd.Timestamp(row["date"], tz=SYD))
        / pd.Timedelta(minutes=30)
    )
    kwp = float(p.loc[p["house_id"] == row["house_id"], "kwp"].iloc[0])
    print(
        f"\n{row['house_id']} {row['date'].date()} slot {slot}: grid feeds {g_pv[slot, 0]:.2f} kW "
        f"for {kwp} kWp; profiles have NaN. Readings nulled by the rule in 2011-12: {len(nulled)}"
    )
    assert g_pv[slot, 0] > 1.2 * kwp
    p_load, p_pv = parser_parity.day_from_profiles(p, row["date"], [customer])
    assert np.isnan(p_pv[slot, 0])


def test_the_two_sides_name_houses_differently():
    # src/grid/ausgrid.py:58 uses str(Customer); profiles and station_houses use AG-0001
    from audit.proposals.label_adapter import ausgrid_id

    assert ausgrid_id(3) == "AG-0003" != str(3)
