from dataclasses import dataclass


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
