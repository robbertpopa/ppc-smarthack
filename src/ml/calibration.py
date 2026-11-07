"""Is the model as sure as it says? Coverage per quantile and the drift between periods."""

import numpy as np


def quantile_coverage(y, pred: np.ndarray, quantiles) -> dict[str, float]:
    """Share of intervals where the true safe share is below each predicted quantile.

    A calibrated model has coverage close to the quantile itself (about 5% for ``q05``).
    """
    y = np.asarray(y, dtype=float)
    return {str(q): float(np.mean(y < pred[:, i])) for i, q in enumerate(quantiles)}


def drift(validation_rate: float, test_rate: float) -> dict[str, float]:
    """Violation rate on validation against test. Report it, do not hide it.

    In exploration the rate drifted from 1.3 to 1.8% on validation to 2.3 to 3.5% on test.
    """
    return {
        "validation": validation_rate,
        "test": test_rate,
        "difference": test_rate - validation_rate,
        "ratio": test_rate / validation_rate if validation_rate > 0 else float("inf"),
    }
