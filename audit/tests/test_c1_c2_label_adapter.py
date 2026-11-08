"""C1, C2: real power-flow output can reach training once it goes through the adapter."""

import numpy as np
import pandas as pd
import pytest

from audit.proposals import label_adapter, label_contract
from src.ml import features, train
from src.ml import labels as labels_io

KWP = {"3": 2.0, "36": 1.5}


def grid_records(starts, shares):
    """Dicts exactly as src/grid/labels.py:77-87 appends them."""
    return [
        {
            "pt_id": "PT-synthetic-400kVA",
            "interval_start": t.isoformat().replace("+00:00", "Z"),
            "safe_cap_share": s,
            "provenance": "simulated",
            "n_houses": 2,
            "pv_scale": 1.0,
            "transformer_kva": 400,
            "source": "Ausgrid 2012-2013; synthetic radial 400 kVA",
        }
        for t, s in zip(starts, shares, strict=True)
    ]


def readings(starts, rng):
    rows = []
    for t in starts:
        for h in KWP:
            rows.append(
                {
                    "interval_start": t,
                    "house_id": h,
                    "load_kw": rng.uniform(0.2, 1),
                    "pv_kw": rng.uniform(0, KWP[h]),
                }
            )
    return pd.DataFrame(rows)


def daytime(days: int):
    """Sydney 09:00-15:00 local (summer) for a few days of January 2011, as UTC."""
    out = []
    for d in range(days):
        day = pd.Timestamp("2011-01-10", tz="Australia/Sydney") + pd.Timedelta(days=d)
        out += list(pd.date_range(day + pd.Timedelta(hours=9), periods=12, freq="30min"))
    return pd.DatetimeIndex(out).tz_convert("UTC")


def test_grid_output_as_written_today_is_rejected():
    raw = pd.DataFrame(grid_records(daytime(1)[:2], [0.5, None]))
    with pytest.raises(ValueError, match="missing columns"):
        labels_io.validate(raw)


def test_adapter_output_passes_the_ml_loader_and_the_contract():
    rng = np.random.default_rng(0)
    starts = daytime(1)[:4]
    out = label_adapter.to_ml_labels(
        grid_records(starts, [0.4, None, 1.0, 0.7]), readings(starts, rng), KWP, "PT-X", "grid@test"
    )
    assert list(out.columns) == list(labels_io.COLUMNS)
    assert out["converged"].tolist() == [True, False, True, True]
    assert out.loc[2, "binding"] == "none" and pd.isna(out.loc[1, "binding"])
    assert np.allclose(out["net_kw"], out["load_kw"] - out["pv_kw"])
    assert label_contract.check_frame(out) == []


def test_adapted_labels_reach_the_training_rows():
    rng = np.random.default_rng(1)
    starts = daytime(3)
    shares = rng.uniform(0.3, 1.0, len(starts)).round(3).tolist()
    out = label_adapter.to_ml_labels(
        grid_records(starts, shares), readings(starts, rng), KWP, "PT-X", "grid@test"
    )
    rows = train.training_rows(out)
    assert len(rows) > 0
    assert rows[features.FEATURES].notna().any().all()  # every feature is computed somewhere


def test_station_houses_ids_match_profiles(station_profiles):
    houses = label_adapter.station_houses("PT-X", {"3": 1.0, "36": 1.5})
    assert houses["source_house_id"].tolist() == ["AG-0003", "AG-0036"]
    assert set(houses["source_house_id"]) <= set(station_profiles["house_id"])
