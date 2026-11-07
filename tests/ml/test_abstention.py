import json
import math

import numpy as np
import pandas as pd
import pytest

from src.ml import abstention, calibration, model_io, train

N = 100
KWP = pd.Series({"H1": 4.0})


def intervals(n=N):
    """Eight midday half hours per Sydney day, all with the sun up."""
    days = [
        pd.Timestamp("2012-01-10 01:00", tz="UTC") + pd.Timedelta(days=d) for d in range(n // 8 + 1)
    ]
    return pd.DatetimeIndex(
        [d + pd.Timedelta(minutes=30 * i) for d in days for i in range(8)][:n],
        name="interval_start",
    )


def case(safe, spread=None, q05=0.5):
    """Validation inputs with a known answer. `safe` is the label per interval."""
    index = intervals()
    spread = pd.Series(np.linspace(0, 1, N) if spread is None else spread, index=index)
    labels = pd.DataFrame({"interval_start": index, "safe_share": safe})
    surplus = pd.DataFrame({"H1": 10.0}, index=index)
    return spread, pd.Series(q05, index=index), labels, surplus


def risky_when_unsure():
    """q05 = 0.5 is unsafe (safe share 0.4) exactly where the spread is above 0.7."""
    spread = np.linspace(0, 1, N)
    return case(np.where(spread > 0.7, 0.4, 0.6))


def brute_force(spread, q05, labels, surplus, target):
    rows = []
    for tau in abstention.candidates(spread):
        applied, abstain = abstention._policy(spread, q05, tau, None)
        rows.append(abstention._row(float(tau), applied, abstain, labels, surplus, KWP))
    return [r for r in rows if r["violation_rate"] <= target]


def test_direction_the_largest_feasible_threshold_is_chosen():
    spread, q05, labels, surplus = risky_when_unsure()
    result = abstention.choose_threshold(spread, q05, labels, surplus, KWP, target=0.02)
    feasible = brute_force(spread, q05, labels, surplus, 0.02)
    assert result["reachable"] and result["tau"] == max(r["tau"] for r in feasible)
    assert result["abstain_rate"] <= min(r["abstain_rate"] for r in feasible)
    assert result["violation_rate"] <= 0.02
    assert 0.25 < result["abstain_rate"] < 0.35  # about the 30% with spread above 0.7, not 43.5%


def test_a_looser_target_never_abstains_more():
    spread, q05, labels, surplus = risky_when_unsure()
    tight = abstention.choose_threshold(spread, q05, labels, surplus, KWP, target=0.0)
    loose = abstention.choose_threshold(spread, q05, labels, surplus, KWP, target=0.5)
    assert loose["abstain_rate"] <= tight["abstain_rate"]
    assert loose["abstain_rate"] == 0.0  # q05 violates in only 30% of intervals


def test_unreachable_target_means_always_abstain():
    spread, q05, labels, surplus = case(safe=0.1)  # even the fixed 0.36 is unsafe
    result = abstention.choose_threshold(spread, q05, labels, surplus, KWP, target=0.02)
    assert result["tau"] == -math.inf and result["reachable"] is False
    assert result["abstain_rate"] == 1.0


def test_flagged_intervals_abstain_whatever_the_spread():
    spread, q05, labels, surplus = case(safe=0.6)
    flagged = pd.Series(False, index=spread.index)
    flagged.iloc[:10] = True
    result = abstention.choose_threshold(spread, q05, labels, surplus, KWP, 0.5, flagged=flagged)
    assert result["abstain_rate"] == pytest.approx(0.10)


def test_risk_coverage_curve_is_monotone_in_coverage():
    spread, q05, labels, surplus = risky_when_unsure()
    curve = abstention.risk_coverage(spread, q05, labels, surplus, KWP)
    assert curve["coverage"].is_monotonic_increasing
    assert curve["coverage"].iloc[-1] == 1.0 and curve["coverage"].iloc[0] < 0.05
    assert curve["risk"].dropna().iloc[0] == 0.0  # the most selective point has no violation


CLEAN = {
    "net_now": 0.3, "net_lag_1": 0.28, "net_lag_2": 0.25, "net_lag_3": 0.2,
    "share_last": 0.6, "sun_elev_T": 40.0,
}  # fmt: skip


def test_quality_flags_clean_input_is_empty():
    assert abstention.quality_flags(CLEAN) == []


@pytest.mark.parametrize(
    ("change", "flag"),
    [
        ({"net_now": None}, "missing_net_now"),
        ({"net_now": float("nan")}, "missing_net_now"),
        ({"share_last": None}, "missing_share_last"),
        ({"net_now": 3.5}, "out_of_range_net"),
        ({"net_lag_2": -2.5}, "out_of_range_net"),
        ({"sun_elev_T": -4.0}, "night"),
        ({"sun_elev_T": 0.0}, "night"),
        ({"net_now": None, "net_lag_1": None, "net_lag_2": None}, "stale_input"),
    ],
)
def test_quality_flags_each_case(change, flag):
    assert flag in abstention.quality_flags({**CLEAN, **change})


def test_one_missing_reading_is_not_stale():
    assert "stale_input" not in abstention.quality_flags({**CLEAN, "net_now": None})


def test_calibration_helpers():
    y = np.array([0.1, 0.5, 0.9, 0.3])
    pred = np.tile([0.2, 0.6], (4, 1))
    assert calibration.quantile_coverage(y, pred, (0.05, 0.5)) == {"0.05": 0.25, "0.5": 0.75}
    drift = calibration.drift(0.02, 0.03)
    assert drift["difference"] == pytest.approx(0.01) and drift["ratio"] == pytest.approx(1.5)


def test_training_stores_the_threshold_and_threshold_reads_it(tmp_path, monkeypatch):
    from src.ml import labels

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ARTIFACT_URI", str(tmp_path / "artifacts"))
    monkeypatch.setenv("VIOLATION_TARGET", "0.05")
    labels.main(["mock", "--scenario", "A"])
    report = train.train(
        "A",
        grid=[{"max_iter": 30, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}],
    )
    info = report["abstention"]
    assert info["violation_target"] == 0.05 and info["violation_rate_with_fallback"] <= 0.05
    path = model_io.model_dir(train.MODEL_VERSION, "PT-A")
    assert (path / "risk_coverage.csv").exists()
    json.loads((path / "metadata.json").read_text(), parse_constant=lambda c: pytest.fail(c))
    assert abstention.threshold("PT-A") == pytest.approx(info["tau"])
    meta = model_io.load_metadata(train.MODEL_VERSION, "PT-A")
    assert (
        meta["abstention"]["reachable"] is True and meta["abstention"]["violation_target"] == 0.05
    )


def test_threshold_is_minus_infinity_when_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_URI", str(tmp_path))
    out = model_io.model_dir("safe-cap-qgb-v1", "PT-X")
    out.mkdir(parents=True)
    (out / "metadata.json").write_text(
        json.dumps({"abstention": {"reachable": False, "tau": None}})
    )
    assert abstention.threshold("PT-X") == -math.inf
