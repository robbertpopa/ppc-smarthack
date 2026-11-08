import math

import pandas as pd

from src.pricing.config import PricingConfig

DEFAULT = PricingConfig()


def hourly_price(wholesale_eur_mwh: float, cfg: PricingConfig = DEFAULT) -> float:
    """What PPC pays for one MWh in an hour: day-ahead price minus the fee, not below the floor."""
    if not math.isfinite(wholesale_eur_mwh):
        raise ValueError("the wholesale price must be a finite number")
    return max(cfg.floor_eur_mwh, wholesale_eur_mwh - cfg.fee_eur_mwh)


def hourly_price_series(wholesale_eur_mwh: pd.Series, cfg: PricingConfig = DEFAULT) -> pd.Series:
    """Same rule over a series; a missing price stays missing."""
    return (wholesale_eur_mwh - cfg.fee_eur_mwh).clip(lower=cfg.floor_eur_mwh)
