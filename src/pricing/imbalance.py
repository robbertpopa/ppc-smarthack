"""Imbalance volume, cost and saving. Pure: series in, numbers out.

PPC's imbalance is the gap between the export it expected and what arrived. A better forecast
shrinks the gap. The cost of a gap is an imbalance spread (EUR/MWh) that is not in our data
source, so callers pass scenario values (``SPREADS_EUR_MWH``) or a real series later.
"""

import pandas as pd

STEP_HOURS = 0.5
SPREADS_EUR_MWH = (30.0, 60.0, 120.0)  # scenario values; AFEER's 38-72 EUR/MWh is a cross-check


def volume_mwh(actual_kw: pd.Series, forecast_kw: pd.Series) -> float:
    """Sum of |actual - forecast| over the intervals both have, in MWh."""
    both = pd.concat([actual_kw, forecast_kw], axis=1, join="inner").dropna()
    return float((both.iloc[:, 0] - both.iloc[:, 1]).abs().sum() * STEP_HOURS / 1000)


def saving(
    actual_kw: pd.Series,
    baseline_kw: pd.Series,
    model_kw: pd.Series,
    spread_eur_mwh: float,
) -> dict:
    """Imbalance cost with the baseline forecast, with the model forecast, and the difference.

    Only intervals where all three series have a value are compared, so both forecasts are
    scored on the same intervals.
    """
    frame = pd.concat([actual_kw, baseline_kw, model_kw], axis=1, join="inner").dropna()
    actual, baseline, model = (frame.iloc[:, i] for i in range(3))
    base_mwh = volume_mwh(actual, baseline)
    model_mwh = volume_mwh(actual, model)
    return {
        "spread_eur_mwh": spread_eur_mwh,
        "n_intervals": len(frame),
        "baseline_mwh": base_mwh,
        "model_mwh": model_mwh,
        "baseline_cost_eur": base_mwh * spread_eur_mwh,
        "model_cost_eur": model_mwh * spread_eur_mwh,
        "saving_eur": (base_mwh - model_mwh) * spread_eur_mwh,
    }


def split_saving(saving_eur: float, bonus_share: float) -> tuple[float, float]:
    """(prosumer bonus, what PPC keeps). A negative saving is not shared: PPC bears it."""
    bonus = max(0.0, saving_eur) * bonus_share
    return bonus, saving_eur - bonus
