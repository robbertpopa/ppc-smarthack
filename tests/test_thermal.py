import math

import pytest

from src.grid.thermal import (
    CYCLIC_LOAD_RATIO_LIMIT,
    DEFAULT_PARAMS,
    ThermalParams,
    headroom,
    relative_ageing_rate,
    steady_state,
    step,
)


def test_rated_load_at_20c_gives_the_98c_reference_hot_spot():
    state = steady_state(1.0, 20.0)
    assert state.top_oil_c == pytest.approx(75.0)
    assert state.hotspot_c == pytest.approx(98.0)


def test_steady_state_grows_with_load_and_ambient():
    assert steady_state(1.2, 20.0).hotspot_c > steady_state(1.0, 20.0).hotspot_c
    assert steady_state(1.0, 30.0).hotspot_c == pytest.approx(108.0)
    assert steady_state(0.0, 20.0).hotspot_c == pytest.approx(20.0 + 55.0 * (1 / 6) ** 0.8)


def test_top_oil_covers_63_percent_of_the_gap_in_one_time_constant():
    start = steady_state(0.5, 20.0)
    target = steady_state(1.0, 20.0)
    after = step(start, 1.0, 20.0, dt_min=DEFAULT_PARAMS.oil_time_const_min)
    gap = target.top_oil_c - start.top_oil_c
    assert after.top_oil_c - start.top_oil_c == pytest.approx(gap * (1 - math.exp(-1)))


def test_winding_follows_a_load_change_with_the_winding_time_constant():
    start = steady_state(0.5, 20.0)
    after = step(start, 1.0, 20.0, dt_min=30.0)
    target = steady_state(1.0, 20.0).winding_rise_k
    tau = DEFAULT_PARAMS.k22 * DEFAULT_PARAMS.winding_time_const_min
    expected = target + (start.winding_rise_k - target) * math.exp(-30.0 / tau)
    assert after.winding_rise_k == pytest.approx(expected)
    assert after.winding_rise_k > 0.97 * target


def test_two_half_steps_equal_one_step():
    start = steady_state(0.4, 15.0)
    once = step(start, 1.3, 25.0, dt_min=30.0)
    twice = step(step(start, 1.3, 25.0, dt_min=15.0), 1.3, 25.0, dt_min=15.0)
    assert twice.hotspot_c == pytest.approx(once.hotspot_c)
    assert twice.top_oil_c == pytest.approx(once.top_oil_c)


def test_long_hold_reaches_steady_state():
    state = steady_state(0.3, 10.0)
    for _ in range(48 * 3):
        state = step(state, 1.1, 10.0)
    assert state.hotspot_c == pytest.approx(steady_state(1.1, 10.0).hotspot_c, abs=1e-6)


def euler_reference(start, load_ratio, ambient_c, minutes, params, dt=0.001):
    p = params
    target = steady_state(load_ratio, ambient_c, p)
    oil, w1, w2 = start.top_oil_c, start.winding_rise_k, start.winding_cooling_k
    for _ in range(int(minutes / dt)):
        oil += dt * (target.top_oil_c - oil) / (p.k11 * p.oil_time_const_min)
        w1 += dt * (target.winding_rise_k - w1) / (p.k22 * p.winding_time_const_min)
        w2 += dt * (target.winding_cooling_k - w2) / (p.oil_time_const_min / p.k22)
    return oil + w1 - w2


def test_exact_step_matches_a_fine_numerical_integration_of_the_equations():
    params = ThermalParams(k21=2.0, k22=1.8)
    start = steady_state(0.6, 18.0, params)
    exact = step(start, 1.4, 22.0, dt_min=30.0, params=params).hotspot_c
    numeric = euler_reference(start, 1.4, 22.0, 30.0, params)
    assert exact == pytest.approx(numeric, abs=0.01)


def test_ageing_rate_doubles_every_six_degrees_above_98c():
    assert relative_ageing_rate(98.0) == pytest.approx(1.0)
    assert relative_ageing_rate(104.0) == pytest.approx(2.0)
    assert relative_ageing_rate(86.0) == pytest.approx(0.25)


def test_no_headroom_above_rated_at_the_reference_condition():
    state = steady_state(1.0, 20.0)
    assert headroom(state, 20.0) == pytest.approx(1.0, abs=1e-3)


def test_cold_transformer_can_carry_more_than_the_fixed_100_percent():
    state = steady_state(0.4, 20.0)
    ratio = headroom(state, 20.0)
    assert 1.0 < ratio <= CYCLIC_LOAD_RATIO_LIMIT
    assert step(state, ratio, 20.0).hotspot_c <= 98.0 + 1e-6


def test_headroom_shrinks_when_it_is_hotter_and_when_the_unit_is_already_warm():
    cold = steady_state(0.4, 20.0)
    assert headroom(cold, 35.0) < headroom(cold, 20.0)
    assert headroom(steady_state(1.0, 20.0), 20.0) < headroom(cold, 20.0)


def test_headroom_is_capped_and_never_negative():
    assert headroom(steady_state(0.0, -10.0), -10.0) == CYCLIC_LOAD_RATIO_LIMIT
    assert headroom(steady_state(1.5, 40.0), 40.0) == 0.0


def test_a_higher_limit_allows_more_load():
    state = steady_state(0.8, 25.0)
    assert headroom(state, 25.0, hotspot_limit_c=120.0) > headroom(state, 25.0)


@pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf")])
def test_load_ratio_must_be_a_finite_number_of_at_least_zero(bad):
    with pytest.raises(ValueError):
        steady_state(bad, 20.0)
    with pytest.raises(ValueError):
        step(steady_state(1.0, 20.0), bad, 20.0)


@pytest.mark.parametrize("bad", [0.0, -5.0, float("nan")])
def test_time_step_must_be_positive(bad):
    with pytest.raises(ValueError):
        step(steady_state(1.0, 20.0), 1.0, 20.0, dt_min=bad)
