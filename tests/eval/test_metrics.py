import numpy as np
import pandas as pd
import pytest

from src.eval import metrics

# 12:00 to 13:00 in Sydney in January, so every interval is daylight
START = pd.Timestamp("2012-01-10 01:00", tz="UTC")
INDEX = pd.DatetimeIndex(
    [START + pd.Timedelta(minutes=30 * i) for i in range(3)], name="interval_start"
)
KWP = pd.Series({"H1": 2.0, "H2": 4.0})
SURPLUS = pd.DataFrame({"H1": [1.0, 3.0, 0.5], "H2": [2.0, 2.0, 6.0]}, index=INDEX)
LABELS = pd.DataFrame({"interval_start": INDEX, "safe_share": [0.5, 0.25, 0.8]})


def policy(values):
    return pd.Series(values, index=INDEX)


def test_exported_energy_by_hand():
    # share 0.5: caps are 1 and 2 kW -> (1+2) + (1+2) + (0.5+2) = 8.5 kW, times 0.5 h
    assert metrics.exported_kwh(policy([0.5] * 3), SURPLUS, KWP) == pytest.approx(4.25)
    # fixed 0.36: caps 0.72 and 1.44 -> 2.16 + 2.16 + 1.94 = 6.26 kW, times 0.5 h
    assert metrics.exported_kwh(policy([0.36] * 3), SURPLUS, KWP) == pytest.approx(3.13)


def test_evaluate_by_hand():
    result = metrics.evaluate(policy([0.5] * 3), LABELS, SURPLUS, KWP)
    assert result["exported_kwh"] == pytest.approx(4.25)
    assert result["export_index"] == pytest.approx(100 * 4.25 / 3.13)
    assert result["violation_rate"] == pytest.approx(1 / 3)  # 0.5 > 0.25 only
    assert result["n_violations"] == 1 and result["n_intervals"] == 3


def test_fixed_has_index_100_and_oracle_has_no_violation():
    fixed = metrics.evaluate(policy([metrics.FIXED_SHARE] * 3), LABELS, SURPLUS, KWP)
    assert fixed["export_index"] == pytest.approx(100.0)
    oracle = metrics.evaluate(policy(LABELS["safe_share"].to_numpy()), LABELS, SURPLUS, KWP)
    assert oracle["violation_rate"] == 0.0


def test_null_labels_are_excluded_and_counted():
    labels = LABELS.copy()
    labels.loc[1, "safe_share"] = np.nan
    result = metrics.evaluate(policy([0.5] * 3), labels, SURPLUS, KWP)
    assert result["n_intervals"] == 2 and result["n_null_label"] == 1
    assert result["violation_rate"] == 0.0  # the one violation was on the null interval


def test_night_intervals_are_not_scored():
    night = pd.DataFrame(
        {"interval_start": [pd.Timestamp("2012-01-10 14:00", tz="UTC")], "safe_share": [0.3]}
    )
    result = metrics.evaluate(
        pd.Series(0.5, index=pd.DatetimeIndex(night["interval_start"])), night, SURPLUS, KWP
    )
    assert result["n_intervals"] == 0 and np.isnan(result["violation_rate"])


def test_abstention_numbers():
    abstain = policy([True, False, True])
    result = metrics.evaluate(policy([0.36] * 3), LABELS, SURPLUS, KWP, abstain=abstain)
    assert result["abstain_rate"] == pytest.approx(2 / 3)
    assert result["per_day_mean"] == 2 and result["per_day_max"] == 2  # one Sydney day


def test_a_policy_without_a_share_is_an_error():
    with pytest.raises(ValueError, match="no share"):
        metrics.evaluate(policy([0.5, np.nan, 0.5]), LABELS, SURPLUS, KWP)


def test_surplus_from_profiles_uses_the_scales_and_keeps_missing():
    profiles = pd.DataFrame(
        {
            "house_id": ["AG-1"] * 3 + ["AG-2"] * 3,
            "interval_start": list(INDEX) * 2,
            "gc_kw": [1.0, 1.0, 1.0, 0.5, 0.5, np.nan],
            "cl_kw": [np.nan, 0.5, 0.0, np.nan, np.nan, np.nan],
            "gg_kw": [3.0, 3.0, 0.2, 1.0, 1.0, 1.0],
        }
    )
    houses = pd.DataFrame(
        {
            "house_id": ["H1", "H2"],
            "source_house_id": ["AG-1", "AG-2"],
            "load_scale": [1.0, 2.0],
            "pv_scale": [1.0, 1.0],
        }
    )
    out = metrics.surplus_kw(profiles, houses)
    assert list(out["H1"]) == [2.0, 1.5, 0.0]  # no controlled load counts as 0; clipped at 0
    assert out["H2"].iloc[:2].tolist() == [0.0, 0.0]  # 1.0 - 2 * 0.5 = 0
    assert np.isnan(out["H2"].iloc[2])  # missing consumption stays missing


def test_skill_score_is_positive_when_better_than_the_reference():
    from src.eval.metrics import skill_score

    y = np.array([0.5, 0.6, 0.7, 0.4])
    assert skill_score(y, y - 0.05, y + 0.2) > 0
    assert skill_score(y, y + 0.2, y - 0.05) < 0
    assert skill_score(y, y, y) != skill_score(y, y, y)  # reference without loss: NaN
    assert skill_score(y, np.full(4, np.nan), y) != skill_score(y, np.full(4, np.nan), y)


def test_jain_index_is_one_for_equal_shares_and_lower_for_unequal_ones():
    from src.eval.metrics import jain_index

    assert jain_index([0.5, 0.5, 0.5]) == 1.0
    assert jain_index([1.0, 0.0, 0.0, 0.0]) == 0.25  # one house gets everything: 1 / n
    assert 0.25 < jain_index([1.0, 0.5, 0.2, 0.1]) < 1.0
    assert jain_index([float("nan")]) != jain_index([float("nan")])


def test_fairness_compares_the_share_of_exportable_energy_each_house_gets():
    from src.eval.metrics import fairness

    index = pd.date_range("2012-12-20 01:00", periods=4, freq="30min", tz="UTC")  # Sydney midday
    surplus = pd.DataFrame({"a": [2.0] * 4, "b": [2.0] * 4}, index=index)
    labels = pd.DataFrame({"interval_start": index, "safe_share": 0.5})
    share = pd.Series(0.5, index=index)
    assert fairness(share, labels, surplus, pd.Series({"a": 4.0, "b": 4.0})) == 1.0
    # a house with a smaller installed power is held to a smaller limit: it keeps less
    assert fairness(share, labels, surplus, pd.Series({"a": 4.0, "b": 1.0})) < 1.0
    assert fairness(share, labels, None, None) != fairness(share, labels, None, None)
