"""M2: violation numbers that are not diluted by easy intervals and that count severity.

To sit next to ``src.eval.metrics.evaluate``: same inputs (applied share and safe share on
the scored intervals), extra outputs.
"""

import numpy as np
import pandas as pd

EPS = 1e-6
STEP_HOURS = 0.5


def violation_report(applied: pd.Series, safe: pd.Series, kwp_total: float) -> dict:
    """``rate_all`` (today's number), ``rate_binding`` (only where the grid limits export,
    ``safe < 1``), the energy exported above the safe limit and the p95 of the excess."""
    applied, safe = applied.align(safe, join="inner")
    excess = (applied - safe).clip(lower=0)
    violated = applied > safe + EPS
    binding = safe < 1 - EPS
    over = excess[violated]
    return {
        "n": int(len(safe)),
        "n_binding": int(binding.sum()),
        "rate_all": float(violated.mean()) if len(safe) else float("nan"),
        "rate_binding": float(violated[binding].mean()) if binding.any() else float("nan"),
        "excess_kwh": float(excess.sum() * kwp_total * STEP_HOURS),
        "excess_p95_share": float(np.quantile(over, 0.95)) if len(over) else 0.0,
    }
