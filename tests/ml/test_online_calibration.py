import math

import numpy as np
import pandas as pd
import pytest

from src.eval.metrics import FIXED_SHARE
from src.ml import online_calibration as oc

KWP = pd.Series({"H1": 4.0})
STEP = pd.Timedelta(minutes=30)


def frame(safe, q05=0.5, abstain=None):
    """Eight midday half hours per Sydney day; decided 60 min ahead, known 30 min after."""
    n = len(safe)
    days = [
        pd.Timestamp("2012-01-10 01:00", tz="UTC") + pd.Timedelta(days=d) for d in range(n // 8 + 1)
    ]
    index = pd.DatetimeIndex(
        [d + i * STEP for d in days for i in range(8)][:n], name="interval_start"
    )
    out = pd.DataFrame(
        {
            "q05": q05,
            "safe_share": np.asarray(safe, dtype=float),
            "decision_time": index - 2 * STEP,
            "available_at": index + STEP,
        },
        index=index,
    )
    if abstain is not None:
        out["abstain"] = np.asarray(abstain, dtype=bool)
    return out


def labels_of(df):
    return pd.DataFrame({"interval_start": df.index, "safe_share": df["safe_share"].to_numpy()})


def surplus_of(df):
    return pd.DataFrame({"H1": 10.0}, index=df.index)


# --- the Offset itself ---------------------------------------------------------------


def test_every_miss_raises_the_offset_and_lowers_the_limit():
    offset = oc.Offset(gamma=0.01, alpha=0.02)
    limits = []
    for _ in range(20):
        limit = offset.apply(0.5)
        limits.append(limit)
        offset.update(limit, safe_share=0.1)  # the limit was too high
    assert offset.c > 0
    assert limits == sorted(limits, reverse=True) and limits[-1] < limits[0]


def test_no_miss_lowers_the_offset_slowly():
    offset = oc.Offset(gamma=0.01, alpha=0.02)
    offset.update(0.5, safe_share=0.1)  # one miss: c = 0.01 * 0.98
    after_miss = offset.c
    for _ in range(10):
        offset.update(0.5, safe_share=0.9)  # safe
    assert offset.c < after_miss
    assert offset.c == pytest.approx(after_miss - 10 * 0.01 * 0.02)


def test_the_offset_stays_inside_its_bounds():
    up = oc.Offset(gamma=0.5, alpha=0.02)
    down = oc.Offset(gamma=0.5, alpha=0.02)
    for _ in range(100):
        up.update(0.5, 0.0)
        down.update(0.5, 1.0)
    assert up.c == oc.C_MAX == 0.30
    assert down.c == oc.C_MIN == -0.05


def test_the_limit_is_clipped_to_zero_one():
    offset = oc.Offset(gamma=0.1, alpha=0.02, c=0.30)
    assert offset.apply(0.1) == 0.0
    assert oc.Offset(gamma=0.1, alpha=0.02, c=-0.05).apply(0.99) == 1.0


def test_a_miss_needs_more_than_the_tolerance():
    offset = oc.Offset(gamma=0.1, alpha=0.02)
    assert offset.update(0.5, 0.5 - 1e-9) is False  # inside 1e-6: not a miss
    assert offset.update(0.5, 0.4) is True


def test_an_unknown_label_changes_nothing():
    offset = oc.Offset(gamma=0.1, alpha=0.02, c=0.1)
    assert offset.update(0.5, float("nan")) is False
    assert offset.c == 0.1


def test_to_dict_from_dict_round_trip():
    offset = oc.Offset(gamma=0.003, alpha=0.02, c=0.0421)
    again = oc.Offset.from_dict(offset.to_dict())
    assert again == offset and again.to_dict() == offset.to_dict()


# --- the replay ----------------------------------------------------------------------


def test_replay_with_all_misses_lowers_the_limit_over_time():
    df = frame([0.0] * 40)
    result = oc.replay(df, gamma=0.01, alpha=0.02)
    assert (result.limit.diff().dropna() <= 1e-12).all()
    assert result.limit.iloc[-1] < result.limit.iloc[0]
    assert result.c_final > 0


def test_replay_with_no_misses_lets_the_limit_rise():
    df = frame([1.0] * 40)
    result = oc.replay(df, gamma=0.01, alpha=0.02)
    assert result.limit.iloc[-1] > result.limit.iloc[0]
    assert result.c_final < 0


def test_replay_never_uses_a_label_before_it_is_available():
    df = frame([0.9] * 40)
    base = oc.replay(df, gamma=0.05, alpha=0.02)
    changed = df.copy()
    k = 10
    changed.iloc[k, changed.columns.get_loc("safe_share")] = 0.0  # a miss in interval k
    other = oc.replay(changed, gamma=0.05, alpha=0.02)
    known_from = df["available_at"].iloc[k]
    early = df["decision_time"] < known_from
    assert early.any() and (~early).any()
    pd.testing.assert_series_equal(base.limit[early], other.limit[early])
    assert (other.limit[~early] < base.limit[~early]).any()  # and it is used afterwards


def test_replay_is_deterministic_and_independent_of_row_order():
    df = frame(np.where(np.arange(40) % 5 == 0, 0.0, 0.9))
    one = oc.replay(df, gamma=0.03, alpha=0.02)
    shuffled = oc.replay(df.sample(frac=1, random_state=0), gamma=0.03, alpha=0.02)
    pd.testing.assert_series_equal(one.limit, shuffled.limit.sort_index())
    assert one.c_final == shuffled.c_final


def test_abstained_intervals_do_not_move_the_offset():
    df = frame([0.0] * 40, abstain=[True] * 40)
    result = oc.replay(df, gamma=0.1, alpha=0.02)
    assert result.c_final == 0.0
    assert (result.limit == 0.5).all()


def test_replay_starts_from_the_given_offset():
    df = frame([0.9] * 8)
    assert oc.replay(df, gamma=0.0, alpha=0.02, c0=0.2).limit.iloc[0] == pytest.approx(0.3)


def test_a_label_known_before_its_own_decision_is_an_error():
    df = frame([0.5] * 8)
    df["available_at"] = df["decision_time"] - STEP
    with pytest.raises(ValueError, match="available_at"):
        oc.replay(df, gamma=0.01, alpha=0.02)


# --- choosing gamma ------------------------------------------------------------------


def regime_shift():
    """Safe at 0.6 for 80 intervals, then at 0.3: a fixed q05 of 0.5 starts to violate."""
    return frame([0.6] * 80 + [0.3] * 80)


def test_choose_gamma_returns_the_best_feasible_gamma_and_ties_go_to_the_smaller():
    df = regime_shift()
    gammas = (0.001, 0.003, 0.01, 0.03)
    chosen = oc.choose_gamma(df, labels_of(df), surplus_of(df), KWP, alpha=0.5, gammas=gammas)
    table = chosen["table"]
    assert list(table["gamma"]) == list(gammas)
    feasible = table[table["violation_rate"] <= 0.5]
    best = feasible["export_index"].max()
    assert chosen["reachable"] is True
    assert chosen["gamma"] == feasible[feasible["export_index"] == best]["gamma"].min()
    assert chosen["violation_rate"] <= 0.5


def test_choose_gamma_reports_unreachable_instead_of_relaxing_alpha():
    df = frame([0.0] * 80)  # every positive limit violates
    chosen = oc.choose_gamma(df, labels_of(df), surplus_of(df), KWP, alpha=0.02)
    table = chosen["table"]
    assert chosen["reachable"] is False and chosen["alpha"] == 0.02
    assert chosen["violation_rate"] == table["violation_rate"].min()
    assert (
        chosen["gamma"]
        == table[table["violation_rate"] == table["violation_rate"].min()]["gamma"].min()
    )


def test_choose_gamma_scores_abstained_intervals_with_the_fixed_limit():
    df = frame([FIXED_SHARE] * 40, abstain=[True] * 40)
    chosen = oc.choose_gamma(df, labels_of(df), surplus_of(df), KWP, alpha=0.02)
    assert chosen["violation_rate"] == 0.0 and chosen["reachable"] is True
    assert chosen["c_final"] == 0.0


def test_choose_gamma_default_grid_is_the_four_gammas_of_the_brief():
    assert oc.GAMMAS == (0.001, 0.003, 0.01, 0.03)
    assert math.isclose(oc.C_MAX, 0.30) and math.isclose(oc.C_MIN, -0.05)
