from dataclasses import dataclass

# The grid injection tariff (TG) that PPC's MaxControl offer deducts from the 15-minute spot
# price it pays for injected energy: 0.00363 lei/kWh, about 0.7 EUR/MWh at 5.2 lei/EUR.
MAXCONTROL_TG_EUR_MWH = 0.7


@dataclass(frozen=True)
class PricingConfig:
    """Placeholders: none of these values is claimed as correct (see the spec)."""

    fee_eur_mwh: float = 30.0
    floor_eur_mwh: float = 0.0
    bonus_share: float = 0.5

    def __post_init__(self):
        if self.fee_eur_mwh < 0 or self.floor_eur_mwh < 0:
            raise ValueError("fee and floor must not be negative")
        if not 0 <= self.bonus_share <= 1:
            raise ValueError("bonus_share must be between 0 and 1")
