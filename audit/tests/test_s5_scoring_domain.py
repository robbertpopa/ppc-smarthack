"""S5: two definitions of the scored intervals; the grid one drops daylight with export."""

import numpy as np
import pandas as pd

from audit.proposals import full_day_net, scoring_domain


def test_grid_filter_drops_daylight_intervals_with_pv(houses_a, station_profiles):
    inputs = full_day_net.station_inputs(station_profiles, houses_a).dropna()
    start = pd.Series(inputs.index, index=inputs.index)
    pv = inputs["pv_kw"]
    ml = scoring_domain.ml_domain(start)
    grid = scoring_domain.grid_domain(start, pv)
    lost = ml & ~grid & (pv.to_numpy() > 0)
    energy_lost = float(pv[lost].sum() / pv.sum())
    local_hours = start[lost].dt.tz_convert("Australia/Sydney").dt.hour.value_counts().sort_index()
    print(
        f"\ndaylight intervals with PV that the grid filter never labels: {int(lost.sum())} "
        f"({lost.sum() / (ml & (pv.to_numpy() > 0)).sum():.2%}), {energy_lost:.3%} of PV energy; "
        f"local hours {local_hours.to_dict()}"
    )
    assert lost.sum() > 0
    unified = scoring_domain.domain(start, pv)
    assert (unified | ~ml).all()  # contains the ML definition
    assert unified[pv.to_numpy() > 0].all()  # and every interval that can export


def test_both_definitions_agree_on_a_winter_noon():
    t = pd.Series(pd.to_datetime(["2011-06-21 02:00"], utc=True))  # 12:00 Sydney
    assert scoring_domain.ml_domain(t)[0]
    assert scoring_domain.grid_domain(t, pd.Series([5.0]))[0]
    assert not np.any(scoring_domain.grid_domain(t, pd.Series([0.0])))
