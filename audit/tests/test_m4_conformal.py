"""M4: a per-hour shift of q05 brings its coverage back at the edges of the day."""

import numpy as np
import pandas as pd
import pytest

from audit.proposals import conformal
from audit.tests.conftest import REPO, need


def test_synthetic_overconfident_edges_are_fixed():
    rng = np.random.default_rng(0)
    n = 120000
    hour = rng.integers(6, 18, n)
    y = rng.uniform(0.3, 0.9, n)
    true_q05 = 0.3 + 0.05 * 0.6
    bias = np.where((hour <= 7) | (hour >= 16), 0.10, 0.0)  # overconfident at the edges
    q05 = np.full(n, true_q05) + bias
    cal, use = slice(0, n // 2), slice(n // 2, n)
    before = conformal.coverage_by_group(q05[use], y[use], hour[use])
    shifts = conformal.fit_shift(q05[cal], y[cal], hour[cal])
    fixed = conformal.apply_shift(q05[use], hour[use], shifts)
    after = conformal.coverage_by_group(fixed, y[use], hour[use])
    assert before.loc[[6, 7, 16, 17]].min() > 0.15
    assert np.all(np.abs(after - 0.05) < 0.02)


def test_unknown_group_falls_back_to_the_global_shift():
    shifts = {"__all__": 0.1, 9: 0.0}
    assert conformal.apply_shift([0.5, 0.5], [9, 23], shifts).tolist() == [0.5, 0.4]


def test_on_the_saved_model_validation_halves(labels_a):
    """Calibrate on the first half of validation, score on the second (mock labels)."""
    need(REPO / "artifacts" / "models" / "safe-cap-qgb-v1" / "PT-A" / "metadata.json")
    from src.ml import features, model_io, train
    from src.ml.split import split

    models, _ = model_io.load(train.MODEL_VERSION, "PT-A")
    rows = split(train.training_rows(labels_a))["val"].reset_index(drop=True)
    q05 = train.predict_quantiles(models, rows[features.FEATURES])[:, 0]
    y = rows["safe_share"].to_numpy()
    hour = pd.DatetimeIndex(rows["target_start"]).tz_convert("Australia/Sydney").hour.to_numpy()
    half = len(rows) // 2
    shifts = conformal.fit_shift(q05[:half], y[:half], hour[:half], min_n=20)
    fixed = conformal.apply_shift(q05[half:], hour[half:], shifts)
    before = float(np.mean(y[half:] < q05[half:] - 1e-6))
    after = float(np.mean(y[half:] < fixed - 1e-6))
    print(f"\nsecond half of validation: q05 violations {before:.3f} -> {after:.3f}")
    assert after < before
    assert after == pytest.approx(0.05, abs=0.03)
