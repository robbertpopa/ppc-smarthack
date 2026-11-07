import numpy as np
import pandas as pd
import pytest

from src.eval import robustness
from src.ml import features, labels


def profiles(n_houses=35, days=3):
    index = pd.date_range("2011-01-10 00:00", periods=48 * days, freq="30min", tz="UTC")
    rng = np.random.default_rng(0)
    rows = []
    for h in range(n_houses):
        sun = np.clip(np.sin((index.hour + index.minute / 60 - 20) / 24 * 2 * np.pi), 0, None)
        rows.append(
            pd.DataFrame(
                {
                    "house_id": f"AG-{h + 1:04d}",
                    "interval_start": index,
                    "gc_kw": 0.4 + 0.2 * rng.random(len(index)),
                    "cl_kw": np.nan if h % 2 else 0.2,
                    "gg_kw": (1.5 + 0.2 * h / n_houses) * sun,
                    "kwp": 2.0,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


@pytest.fixture(scope="module")
def station():
    prof = profiles()
    lab, houses = labels.make_mock_with_houses(prof, "A")
    return lab, houses, robustness.readings(prof, houses)


def test_clean_aggregates_equal_the_label_file(station):
    lab, houses, data = station
    totals = robustness.aggregate(data, len(houses)).reindex(
        pd.DatetimeIndex(lab["interval_start"])
    )
    assert np.allclose(totals["load_kw"], lab["load_kw"], atol=1e-9)
    assert np.allclose(totals["pv_kw"], lab["pv_kw"], atol=1e-9)


def test_corruption_is_deterministic_per_seed_and_differs_between_seeds(station):
    data = station[2]
    for variant in robustness.VARIANTS:
        first, again = robustness.corrupt(data, variant, 0), robustness.corrupt(data, variant, 0)
        assert first.equals(again)
        assert not first.equals(robustness.corrupt(data, variant, 1)) or variant == "censored"


def test_corruption_touches_only_inputs(station):
    lab, houses, data = station
    before_labels, before_data = lab.copy(), data.copy()
    for variant in robustness.VARIANTS:
        out = robustness.corrupted_labels(lab, robustness.corrupt(data, variant), houses)
        assert out["safe_share"].equals(lab["safe_share"])  # the target is never touched
        assert out["interval_start"].equals(lab["interval_start"])
    assert lab.equals(before_labels) and data.equals(before_data)


def test_missing_20_removes_about_a_fifth_and_never_makes_zeros(station):
    data = station[2]
    out = robustness.corrupt(data, "missing_20")
    assert out["gg_kw"].isna().mean() == pytest.approx(0.2, abs=0.02)
    assert ((out["gg_kw"] == 0) & (data["gg_kw"] != 0)).sum() == 0  # no NaN became 0


def test_missing_readings_stay_missing_through_the_feature_frame(station):
    lab, houses, data = station
    bad = robustness.corrupted_labels(lab, robustness.corrupt(data, "missing_20"), houses)
    clean_frame, bad_frame = features.build_frame(lab), features.build_frame(bad)
    assert bad_frame["net_now"].isna().sum() >= clean_frame["net_now"].isna().sum()
    assert (bad_frame["net_now"] == 0).sum() == (clean_frame["net_now"] == 0).sum()


def test_totals_are_scaled_up_and_nan_below_half_the_houses():
    base = pd.DataFrame(
        {
            "interval_start": [pd.Timestamp("2012-01-10 01:00", tz="UTC")] * 4,
            "gc_kw": [1.0] * 4,
            "cl_kw": [0.0] * 4,
            "gg_kw": [2.0] * 4,
            "load_scale": 1.0,
            "pv_scale": 1.0,
        }
    )
    one_gone = base.copy()
    one_gone.loc[0, ["gc_kw", "gg_kw"]] = np.nan
    assert robustness.aggregate(one_gone, 4).iloc[0].tolist() == pytest.approx([4.0, 8.0])
    three_gone = base.copy()
    three_gone.loc[:2, ["gc_kw", "gg_kw"]] = np.nan
    assert robustness.aggregate(three_gone, 4).iloc[0].isna().all()
    exactly_half = base.copy()
    exactly_half.loc[:1, ["gc_kw", "gg_kw"]] = np.nan
    assert robustness.aggregate(exactly_half, 4).iloc[0].tolist() == pytest.approx([4.0, 8.0])


def test_noise_is_centred_and_never_negative(station):
    data = station[2]
    out = robustness.corrupt(data, "noise_30")
    assert (out[["gc_kw", "gg_kw"]].dropna() >= 0).all().all()
    ratio = out["gg_kw"].sum() / data["gg_kw"].sum()
    assert ratio == pytest.approx(1.0, abs=0.05)
    assert not out["gg_kw"].equals(data["gg_kw"])


def test_censoring_caps_the_visible_export_at_the_fixed_limit(station):
    data = station[2]
    out = robustness.corrupt(data, "censored")
    load = data["load_scale"] * (data["gc_kw"] + data["cl_kw"].fillna(0))
    seen = out["pv_scale"] * out["gg_kw"] - load
    assert (seen.clip(lower=0) <= 0.36 * data["kwp"] + 1e-9).all()
    real = data["pv_scale"] * data["gg_kw"] - load
    untouched = real <= 0.36 * data["kwp"]
    assert np.allclose(out.loc[untouched, "gg_kw"], data.loc[untouched, "gg_kw"])
    assert out["gg_kw"].sum() < data["gg_kw"].sum()  # sunny hours are under-reported


def test_unknown_variant_is_rejected(station):
    with pytest.raises(ValueError, match="unknown variant"):
        robustness.corrupt(station[2], "fog")


def test_net_only_check_passes_and_catches_gross_features(monkeypatch):
    assert robustness.net_only_check() is True
    monkeypatch.setattr(features, "FEATURES", [*features.FEATURES, "gg_kw_now"])
    with pytest.raises(AssertionError, match="gross"):
        robustness.net_only_check()
