import pandas as pd

from src.pricing.config import PricingConfig
from src.pricing.tariff import DEFAULT, hourly_price_series


def settle(
    exported_kwh: pd.Series,
    wholesale_eur_mwh: pd.Series,
    monthly_avg_eur_mwh: pd.Series,
    adder_eur_mwh: pd.Series,
    cfg: PricingConfig = DEFAULT,
) -> dict:
    """What a prosumer is paid for the exported energy, and what PPC's side of it is worth.

    ``regulated_eur``: today, the monthly average on every kWh. ``hourly_eur``: the hourly
    price (day-ahead minus fee, not below the floor). ``paid_eur``: hourly plus the solar adder.
    ``value_eur``: the day-ahead value of the same energy, what PPC does not have to buy.
    Intervals without a price are dropped and counted. All inputs share one index.
    """
    index = exported_kwh.index
    wholesale = wholesale_eur_mwh.reindex(index)
    monthly = monthly_avg_eur_mwh.reindex(index)
    adder = adder_eur_mwh.reindex(index)
    ok = wholesale.notna() & monthly.notna() & adder.notna()
    kwh = exported_kwh[ok]
    regulated = float((kwh * monthly[ok]).sum()) / 1000
    hourly = float((kwh * hourly_price_series(wholesale[ok], cfg)).sum()) / 1000
    extra = float((kwh * adder[ok]).sum()) / 1000
    value = float((kwh * wholesale[ok]).sum()) / 1000
    return {
        "exported_kwh": float(kwh.sum()),
        "n_without_price": int((~ok).sum()),
        "regulated_eur": regulated,
        "hourly_eur": hourly,
        "adder_eur": extra,
        "paid_eur": hourly + extra,
        "value_eur": value,
        "ppc_margin_regulated_eur": value - regulated,
        "ppc_margin_paid_eur": value - hourly - extra,
    }
