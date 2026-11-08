# tests/eval/test_score_dataset.py
import numpy as np
import pandas as pd

from src.eval.metrics import FIXED_SHARE
from src.eval.score_dataset import model_limits
from src.ml import features, train
from src.ml import labels as labels_io


class Constant:
    def __init__(self, value):
        self.value = value

    def predict(self, X):
        return np.full(len(X), self.value)


def rows():
    return train.training_rows(labels_io.make_mock(None, "A")).iloc[2000:2200]


def meta(tau):
    return {
        "features": features.FEATURES,
        "abstention": {"tau": tau, "reachable": True},
        "offset": {"gamma": 0.01, "alpha": 0.02, "c_start": 0.0},
    }


def models():
    return {q: Constant(v) for q, v in zip(train.QUANTILES, (0.2, 0.25, 0.3, 0.5, 0.9))}


def test_a_wide_spread_abstains_and_falls_back_to_the_fixed_limit():
    frame, pred = model_limits(models(), meta(tau=0.5), rows())  # spread 0.7 > 0.5
    assert frame["abstain"].all()
    assert (frame["fallback"] == FIXED_SHARE).all()
    assert pred.shape == (len(frame), 5)


def test_without_abstention_the_fallback_is_the_offset_limit():
    frame, _ = model_limits(models(), meta(tau=0.9), rows())  # spread 0.7 <= 0.9
    kept = ~frame["abstain"]
    assert kept.any()
    assert (frame.loc[kept, "fallback"] == frame.loc[kept, "limit"]).all()
    assert frame.index.is_monotonic_increasing
    assert isinstance(frame.index, pd.DatetimeIndex)
