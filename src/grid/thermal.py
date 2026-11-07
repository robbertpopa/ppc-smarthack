import math
from dataclasses import dataclass

NORMAL_AGEING_HOTSPOT_C = 98.0
CYCLIC_HOTSPOT_LIMIT_C = 120.0
CYCLIC_TOP_OIL_LIMIT_C = 105.0
CYCLIC_LOAD_RATIO_LIMIT = 1.5


@dataclass(frozen=True)
class ThermalParams:
    rated_top_oil_rise_k: float = 55.0
    rated_hot_spot_gradient_k: float = 23.0
    loss_ratio: float = 5.0
    oil_exponent: float = 0.8
    winding_exponent: float = 1.6
    k11: float = 1.0
    k21: float = 1.0
    k22: float = 2.0
    oil_time_const_min: float = 180.0
    winding_time_const_min: float = 4.0


DEFAULT_PARAMS = ThermalParams()


@dataclass(frozen=True)
class ThermalState:
    top_oil_c: float
    winding_rise_k: float
    winding_cooling_k: float

    @property
    def hotspot_c(self) -> float:
        return self.top_oil_c + self.winding_rise_k - self.winding_cooling_k


def _check(load_ratio: float, dt_min: float | None = None) -> None:
    if not math.isfinite(load_ratio) or load_ratio < 0:
        raise ValueError(f"load ratio must be a finite number >= 0, got {load_ratio}")
    if dt_min is not None and (not math.isfinite(dt_min) or dt_min <= 0):
        raise ValueError(f"time step must be a finite number > 0, got {dt_min}")


def steady_state(
    load_ratio: float, ambient_c: float, params: ThermalParams = DEFAULT_PARAMS
) -> ThermalState:
    _check(load_ratio)
    p = params
    oil_rise = p.rated_top_oil_rise_k * (
        (1 + p.loss_ratio * load_ratio**2) / (1 + p.loss_ratio)
    ) ** p.oil_exponent
    winding = p.rated_hot_spot_gradient_k * load_ratio**p.winding_exponent
    return ThermalState(
        top_oil_c=ambient_c + oil_rise,
        winding_rise_k=p.k21 * winding,
        winding_cooling_k=(p.k21 - 1) * winding,
    )


def _relax(current: float, target: float, dt_min: float, time_const_min: float) -> float:
    return target + (current - target) * math.exp(-dt_min / time_const_min)


def step(
    state: ThermalState,
    load_ratio: float,
    ambient_c: float,
    dt_min: float = 30.0,
    params: ThermalParams = DEFAULT_PARAMS,
) -> ThermalState:
    _check(load_ratio, dt_min)
    p = params
    target = steady_state(load_ratio, ambient_c, p)
    return ThermalState(
        top_oil_c=_relax(state.top_oil_c, target.top_oil_c, dt_min, p.k11 * p.oil_time_const_min),
        winding_rise_k=_relax(
            state.winding_rise_k,
            target.winding_rise_k,
            dt_min,
            p.k22 * p.winding_time_const_min,
        ),
        winding_cooling_k=_relax(
            state.winding_cooling_k,
            target.winding_cooling_k,
            dt_min,
            p.oil_time_const_min / p.k22,
        ),
    )


def relative_ageing_rate(hotspot_c: float) -> float:
    return 2.0 ** ((hotspot_c - NORMAL_AGEING_HOTSPOT_C) / 6.0)


def headroom(
    state: ThermalState,
    ambient_c: float,
    dt_min: float = 30.0,
    hotspot_limit_c: float = NORMAL_AGEING_HOTSPOT_C,
    top_oil_limit_c: float = CYCLIC_TOP_OIL_LIMIT_C,
    max_ratio: float = CYCLIC_LOAD_RATIO_LIMIT,
    params: ThermalParams = DEFAULT_PARAMS,
) -> float:
    def fits(ratio: float) -> bool:
        after = step(state, ratio, ambient_c, dt_min, params)
        return after.hotspot_c <= hotspot_limit_c and after.top_oil_c <= top_oil_limit_c

    if fits(max_ratio):
        return max_ratio
    if not fits(0.0):
        return 0.0
    low, high = 0.0, max_ratio
    for _ in range(40):
        mid = (low + high) / 2
        low, high = (mid, high) if fits(mid) else (low, mid)
    return low
