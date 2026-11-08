"""M1: walk-forward validation over a whole year and a threshold that holds in every month.

Today one fixed validation window (April to June 2012) chooses the hyper-parameters and
``tau``. Here every month of 2011-07 .. 2012-06 is a validation fold, trained on
everything before it (expanding window), and ``tau`` is the highest one whose violation
rate stays under the target in (by default) every fold, not only on average.
"""

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd

from src.ml.split import TEST_START, local_date


def monthly_folds(first="2011-07-01", end=TEST_START) -> list[dict]:
    """``[{"val_start", "val_end"}]`` per month (Sydney dates, ``val_end`` exclusive).

    Training of a fold is every row before ``val_start``.
    """
    starts = pd.date_range(pd.Timestamp(first), pd.Timestamp(end), freq="MS", inclusive="left")
    return [{"val_start": s, "val_end": s + pd.offsets.MonthBegin(1)} for s in starts]


def fold_masks(interval_start: pd.Series, fold: dict) -> tuple[np.ndarray, np.ndarray]:
    date = local_date(interval_start)
    train = (date < fold["val_start"]).to_numpy()
    val = ((date >= fold["val_start"]) & (date < fold["val_end"])).to_numpy()
    return train, val


def robust_tau(
    candidates: Sequence[float],
    violation_rate: Callable[[float, int], float],
    n_folds: int,
    target: float,
    quantile: float = 1.0,
) -> dict:
    """Highest ``tau`` whose per-fold violation rates have their ``quantile`` <= ``target``.

    ``violation_rate(tau, fold)`` scores one threshold on one validation fold.
    ``quantile=1.0`` means every fold must meet the target. Returns ``tau=-inf`` (always
    abstain) when none does, like ``src.ml.abstention.pick``.
    """
    best = {"tau": -np.inf, "reachable": False, "per_fold": None}
    for tau in sorted(candidates):
        rates = np.array([violation_rate(tau, k) for k in range(n_folds)])
        if np.quantile(rates, quantile) <= target:
            best = {"tau": float(tau), "reachable": True, "per_fold": rates.tolist()}
    return best
