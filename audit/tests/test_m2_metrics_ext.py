"""M2: violations counted where they matter, with their size."""

import numpy as np
import pandas as pd
import pytest

from audit.proposals.metrics_ext import violation_report


def test_easy_intervals_dilute_todays_rate():
    idx = pd.RangeIndex(10)
    safe = pd.Series([1.0] * 5 + [0.5] * 5, index=idx)  # half of the intervals never bind
    applied = pd.Series([0.9] * 5 + [0.6, 0.6, 0.4, 0.4, 0.4], index=idx)
    r = violation_report(applied, safe, kwp_total=100)
    assert r["rate_all"] == pytest.approx(0.2)
    assert r["rate_binding"] == pytest.approx(0.4)  # twice the number reported today
    assert r["n_binding"] == 5


def test_excess_energy_and_size():
    idx = pd.RangeIndex(4)
    safe = pd.Series([0.5, 0.5, 0.5, 0.5], index=idx)
    applied = pd.Series([0.5, 0.6, 0.8, 0.4], index=idx)
    r = violation_report(applied, safe, kwp_total=100)
    assert r["excess_kwh"] == pytest.approx((0.1 + 0.3) * 100 * 0.5)
    assert r["excess_p95_share"] == pytest.approx(np.quantile([0.1, 0.3], 0.95))


def test_a_safe_policy_has_no_excess():
    safe = pd.Series([0.3, 0.7, 1.0])
    r = violation_report(safe - 0.05, safe, kwp_total=50)
    assert r["rate_all"] == 0 and r["excess_kwh"] == 0 and r["excess_p95_share"] == 0
