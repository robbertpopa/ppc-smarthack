"""M3: with the night readings added, the morning rows get their inputs back."""

import numpy as np
import pandas as pd
import pytest

from audit.proposals import full_day_net
from src.ml import abstention, features
from src.ml.split import daylight

START, END = pd.Timestamp("2011-01-01", tz="UTC"), pd.Timestamp("2011-04-01", tz="UTC")


@pytest.fixture(scope="module")
def quarter(labels_a, houses_a, station_profiles):
    labels = labels_a[(labels_a["interval_start"] >= START) & (labels_a["interval_start"] < END)]
    inputs = full_day_net.station_inputs(station_profiles, houses_a)
    inputs = inputs[(inputs.index >= START) & (inputs.index < END)]
    return labels.reset_index(drop=True), inputs


def _morning_gaps(labels, original_starts):
    frame = features.build_frame(labels)
    frame["interval_start"] = frame["target_start"]
    keep = daylight(frame) & frame["target_start"].isin(original_starts).to_numpy()
    rows = frame[keep]
    flagged = np.mean(
        [bool(abstention.quality_flags(r)) for r in rows[features.FEATURES].to_dict("records")]
    )
    return (
        float(rows["net_now"].isna().mean()),
        float(rows["share_last"].isna().mean()),
        float(flagged),
    )


def test_station_inputs_match_the_labels_where_both_exist(quarter):
    labels, inputs = quarter
    joined = labels.set_index("interval_start")[["load_kw", "pv_kw"]].join(inputs.add_suffix("_p"))
    joined = joined.dropna()
    assert len(joined) > 0.95 * len(labels)
    assert np.allclose(joined["load_kw"], joined["load_kw_p"])
    assert np.allclose(joined["pv_kw"], joined["pv_kw_p"])


def test_full_day_inputs_close_the_morning_gap(quarter):
    labels, inputs = quarter
    extended = full_day_net.with_full_day(labels, inputs)  # validates the schema too
    before = _morning_gaps(labels, labels["interval_start"])
    after = _morning_gaps(extended, labels["interval_start"])
    print(
        f"\nnet_now NaN {before[0]:.3f} -> {after[0]:.3f}; share_last NaN {before[1]:.3f} -> "
        f"{after[1]:.3f}; abstained by input checks {before[2]:.3f} -> {after[2]:.3f}"
    )
    assert before[0] > 0.05
    assert after[0] < 0.01
    assert after[2] < before[2] / 2


def test_added_rows_never_claim_a_share_where_pv_was_produced(quarter):
    labels, inputs = quarter
    extended = full_day_net.with_full_day(labels, inputs)
    added = extended[extended["provenance"] == "measured"]
    assert (added.loc[added["safe_share"].notna(), "pv_kw"] <= 0).all()
    assert added.loc[added["pv_kw"] > 0, "safe_share"].isna().all()
