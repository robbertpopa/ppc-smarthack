"""M1: monthly walk-forward folds and a threshold that holds in every month."""

import numpy as np
import pandas as pd

from audit.proposals import walk_forward
from src.ml.split import TEST_START, local_date

SEASON = {
    12: "summer",
    1: "summer",
    2: "summer",
    3: "autumn",
    4: "autumn",
    5: "autumn",
    6: "winter",
    7: "winter",
    8: "winter",
    9: "spring",
    10: "spring",
    11: "spring",
}


def test_twelve_chronological_folds_before_the_test_year():
    folds = walk_forward.monthly_folds()
    assert len(folds) == 12
    assert all(a["val_end"] == b["val_start"] for a, b in zip(folds, folds[1:], strict=False))
    assert folds[-1]["val_end"] == TEST_START


def test_every_fold_has_training_and_validation_rows_and_all_seasons_are_validated(labels_a):
    seasons = set()
    for fold in walk_forward.monthly_folds():
        tr, va = walk_forward.fold_masks(labels_a["interval_start"], fold)
        assert tr.sum() > 0 and va.sum() > 0
        assert not (tr & va).any()
        last_train = local_date(labels_a["interval_start"][tr]).max()
        assert last_train < fold["val_start"]  # no row of the month is in its own training
        seasons.add(SEASON[fold["val_start"].month])
    assert seasons == {"summer", "autumn", "winter", "spring"}  # today: only autumn/winter


def test_robust_tau_holds_in_the_worst_month_where_the_mean_would_not():
    # violation rate grows with tau; month 0 ("summer") is three times worse than the rest
    def rate(tau, fold):
        return tau * (0.3 if fold == 0 else 0.1)

    taus = np.linspace(0, 0.5, 51)
    robust = walk_forward.robust_tau(taus, rate, n_folds=12, target=0.02)
    mean_based = max(t for t in taus if np.mean([rate(t, k) for k in range(12)]) <= 0.02)
    assert robust["reachable"]
    assert max(robust["per_fold"]) <= 0.02
    assert robust["tau"] < mean_based
    assert rate(mean_based, 0) > 0.02  # what the average-based choice does in summer


def test_unreachable_target_means_always_abstain():
    out = walk_forward.robust_tau([0.1, 0.2], lambda t, k: 0.5, n_folds=3, target=0.02)
    assert out == {"tau": -np.inf, "reachable": False, "per_fold": None}


def test_fold_masks_use_sydney_dates():
    # 2011-07-31 15:00 UTC is already 1 August in Sydney: it belongs to the August fold
    ts = pd.Series(pd.to_datetime(["2011-07-31 15:00"], utc=True))
    july, august = walk_forward.monthly_folds()[:2]
    assert not walk_forward.fold_masks(ts, july)[1][0]
    assert walk_forward.fold_masks(ts, august)[1][0]
