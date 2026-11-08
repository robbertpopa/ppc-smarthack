# tests/test_ui_replay_build.py
import numpy as np
import pandas as pd

from src.ui.replay_build import build_geo, day_payload, policy_block


def test_a_share_above_the_safe_share_marks_every_reading_house_red():
    block = policy_block(0.5, 0.4, np.array([1.0, 2.0, np.nan]), np.array([4.0, 4.0, 4.0]))
    assert block["violation"] is True
    assert block["status"] == "rrn"


def test_a_house_capped_below_its_surplus_is_amber_and_the_rest_green():
    surplus = np.array([3.0, 0.5])
    block = policy_block(0.36, 0.9, surplus, np.array([5.0, 5.0]))  # caps 1.8 and 1.8
    assert block["violation"] is False
    assert block["status"] == "ag"
    assert block["export_kw"] == [1.8, 0.5]
    assert block["export_total_kw"] == 2.3
    assert block["curtailed_total_kw"] == 1.2


def test_a_missing_reading_is_not_counted_as_export():
    block = policy_block(0.5, 0.9, np.array([np.nan, 2.0]), np.array([4.0, 4.0]))
    assert block["export_kw"] == [None, 2.0]
    assert block["export_total_kw"] == 2.0


def test_day_payload_groups_by_sydney_date_and_summarises_both_policies():
    times = pd.DatetimeIndex(
        ["2013-05-01T00:00Z", "2013-05-01T00:30Z", "2013-05-01T23:00Z"], name="interval_start"
    )  # the last one is 2013-05-02 09:00 in Sydney
    table = pd.DataFrame(
        {"safe": [0.9, 0.2, 0.9], "fallback": [0.6, 0.6, 0.36], "abstain": [False, False, True]},
        index=times,
    )
    surplus = pd.DataFrame({"H01": [2.0, 2.0, 2.0], "H02": [0.5, 0.5, 0.5]}, index=times)
    kwp = pd.Series({"H01": 5.0, "H02": 5.0})
    days = day_payload(table, surplus, kwp, fixed=0.36)
    assert sorted(days) == ["2013-05-01", "2013-05-02"]
    first = days["2013-05-01"]
    assert len(first["intervals"]) == 2
    assert first["intervals"][0]["after"]["status"] == "gg"
    assert first["intervals"][1]["after"]["violation"] is True
    assert first["intervals"][1]["before"]["violation"] is True  # 0.36 > 0.2
    assert first["summary"]["after"]["violations"] == 1
    # an abstained interval uses the fixed limit in both views
    assert days["2013-05-02"]["intervals"][0]["after"]["share"] == 0.36


def customers():
    rows = []
    for n in range(1, 13):
        rows.append(
            {
                "customer": str(n),
                "kwp": 4.0,
                "postcode": "2076" if n % 2 else "2259",
                "lat": -33.7 if n % 2 else -33.2,
                "lon": 151.1 + n / 100,
                "locality": "Normanhurst" if n % 2 else "Alison",
            }
        )
    return rows


def test_houses_are_split_into_feeders_in_station_order():
    order = [str(n) for n in range(1, 13)]
    geo = build_geo(order, customers(), per_hood=6, per_node=3)
    kinds = [f["properties"]["kind"] for f in geo["features"]]
    assert kinds.count("neighbourhood") == 2
    assert kinds.count("feeder") == 2
    assert kinds.count("house") == 12
    houses = {
        f["properties"]["house_id"]: f["properties"]
        for f in geo["features"]
        if f["properties"]["kind"] == "house"
    }
    assert houses["1"]["neighbourhood"] == "N1" and houses["6"]["neighbourhood"] == "N1"
    assert houses["7"]["neighbourhood"] == "N2" and houses["12"]["neighbourhood"] == "N2"
    assert houses["1"]["node"] == "N1-1" and houses["4"]["node"] == "N1-2"
    assert geo["meta"]["provenance"] == "assumed"


def test_a_house_without_coordinates_is_an_error():
    import pytest

    with pytest.raises(ValueError, match="no coordinates"):
        build_geo(["1", "99"], customers(), per_hood=2, per_node=1)
