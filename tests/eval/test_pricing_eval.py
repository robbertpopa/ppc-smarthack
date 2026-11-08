import json

import numpy as np
import pandas as pd
import pytest

from src.eval import pricing_eval
from src.pricing import prices


def duck_year(year=2025):
    """A year of prices: cheap at midday, dear in the evening, so the adder and shifting pay."""
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    hour = idx.tz_convert("Europe/Bucharest").hour
    evening = np.where((hour >= 18) & (hour < 22), 220.0, 120.0)
    price = np.where((hour >= 10) & (hour < 16), 40.0, evening)
    return pd.Series(price, index=idx)


def make(days=4):
    idx = pd.date_range("2013-01-14", periods=48 * days, freq="30min", tz="UTC")
    hour = idx.tz_convert("Australia/Sydney").hour
    sun = np.where((hour >= 9) & (hour < 16), 8.0, 0.0)
    surplus = pd.DataFrame({"H1": sun, "H2": sun * 0.5, "H3": sun}, index=idx)
    kwp = pd.Series({"H1": 10.0, "H2": 5.0, "H3": 10.0})
    abstain = pd.Series(False, index=idx)
    abstain.iloc[:48] = True  # the first day falls back to the fixed limit
    share = pd.Series(0.5, index=idx).where(~abstain, 0.36)
    ctx = {"surplus": surplus, "kwp": kwp}
    result = {"scored": {"fallback": share, "abstain": abstain}}
    return ctx, result


@pytest.fixture(scope="module")
def table():
    return prices.profile(duck_year())


def test_block_shape_and_signs(table):
    ctx, result = make()
    block = pricing_eval.compute(ctx, result, table)
    assert block["battery_houses"] == ["H1"]  # ceil(0.3 * 3) = 1, first in sorted order
    names = [r["name"] for r in block["rows"]]
    assert names[0].startswith("Older contract today") and names[-1].startswith("Proposed")
    today, maxcontrol, maxcontrol_battery, hourly, adder, proposed = block["rows"]
    assert today["prosumer_vs_today_pct"] == 0.0 and today["ppc_improvement_eur"] == 0.0
    assert today["ppc_margin_eur"] < 0  # PPC pays the monthly average for cheap midday energy
    # MaxControl already pays the spot price: PPC's margin on the energy is about zero, and a
    # battery lets the prosumer earn the evening price
    assert abs(maxcontrol["ppc_margin_eur"]) < abs(today["ppc_margin_eur"]) / 10
    assert maxcontrol["prosumer_eur"] < today["prosumer_eur"]
    assert maxcontrol_battery["prosumer_eur"] > maxcontrol["prosumer_eur"]
    assert hourly["prosumer_eur"] < today["prosumer_eur"]  # no adder: the prosumer loses
    assert adder["prosumer_eur"] > hourly["prosumer_eur"]
    assert proposed["prosumer_eur"] > adder["prosumer_eur"]  # the battery adds revenue
    assert proposed["ppc_improvement_eur"] > 0
    assert [s["fee_eur_mwh"] for s in block["sensitivity"]] == [0, 10, 20, 30, 40, 50]
    json.dumps(block, allow_nan=False)


def test_a_higher_fee_moves_value_from_prosumer_to_ppc(table):
    ctx, result = make()
    s = pricing_eval.compute(ctx, result, table)["sensitivity"]
    assert s[0]["prosumer_eur"] > s[-1]["prosumer_eur"]
    assert s[0]["ppc_improvement_eur"] < s[-1]["ppc_improvement_eur"]


def test_no_surplus_table_gives_none(table):
    ctx, result = make()
    assert pricing_eval.compute({**ctx, "surplus": None}, result, table) is None


def test_markdown_is_written(tmp_path, table):
    ctx, result = make()
    block = pricing_eval.compute(ctx, result, table)
    pricing_eval.write(tmp_path, "PT-A", block, "MOCK, NOT A RESULT")
    text = (tmp_path / "pricing_PT-A.md").read_text()
    assert text.startswith("# MOCK, NOT A RESULT") and "euenergy.live" in text
    assert "MaxControl" in text and "battery response" in text and "Fee sensitivity" in text


def test_summer_day_chart_is_written(tmp_path, table):
    pytest.importorskip("matplotlib")
    ctx, result = make()
    path = pricing_eval.day_chart(ctx, result, table, tmp_path, "PT-A")
    assert path.name == "pricing_day_PT-A.png" and path.stat().st_size > 1000


def test_chart_needs_a_summer_day(tmp_path, table):
    pytest.importorskip("matplotlib")
    ctx, result = make()
    shift = pd.Timedelta(days=120)  # mid-May: Sydney autumn
    surplus = ctx["surplus"]
    moved_ctx = {"surplus": surplus.set_axis(surplus.index + shift), "kwp": ctx["kwp"]}
    moved = {"scored": {k: v.set_axis(v.index + shift) for k, v in result["scored"].items()}}
    assert pricing_eval.day_chart(moved_ctx, moved, table, tmp_path, "PT-A") is None
