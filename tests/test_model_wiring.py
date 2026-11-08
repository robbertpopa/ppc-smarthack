import importlib
from datetime import datetime, timezone

import pytest

pytest.importorskip("pandapower", reason="needs the sim extra")

from src.agent.wiring import build_service
from src.common.config import Settings
from src.ml import forecast_pv_load, labels, train

predict_module = importlib.import_module("src.ml.predict")
FAST = [{"max_iter": 40, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}]


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("wiring")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    train.train("A", grid=FAST)
    forecast_pv_load.train("A", horizons=(60,), params=FAST[0])
    forecast_pv_load.clear_cache()
    predict_module.clear_cache()
    yield root
    mp.undo()


def test_model_source_runs_the_real_model_and_guard(env):
    service = build_service(Settings(source="model", scenario="A", log_uri=str(env / "a.jsonl")))
    moment = datetime(2012, 5, 10, 1, 0, tzinfo=timezone.utc)
    plan = service.propose(moment)
    assert plan.pt_id == "PT-A"
    assert plan.guard is not None and plan.guard.v_max_pu is not None
    assert "grid state did not converge" not in plan.reasons


def test_the_plan_carries_the_hotspot_and_grounded_factors(env):
    service = build_service(Settings(source="model", scenario="A", log_uri=str(env / "b.jsonl")))
    moment = datetime(2012, 5, 10, 1, 0, tzinfo=timezone.utc)
    state = service.source.grid_state("PT-A", moment)
    assert state.converged and 20 < state.trafo_hotspot_c < 200


def test_hotspot_rises_with_load():
    from src.agent.model_wiring import hotspot_c

    assert hotspot_c([0.2] * 10) < hotspot_c([0.2] * 5 + [1.4] * 5)
    assert hotspot_c([]) is None


def test_a_day_without_readings_abstains_on_the_input_checks(env):
    service = build_service(Settings(source="model", scenario="A", log_uri=str(env / "c.jsonl")))
    outside = datetime(2025, 6, 21, 2, 0, tzinfo=timezone.utc)  # no labels history at all
    plan = service.propose(outside)
    assert plan.abstain and plan.source == "fallback_static"
    assert {"missing_net_now", "stale_input"} <= set(plan.reasons)


def test_a_normal_day_in_the_label_period_has_no_input_flags(env):
    service = build_service(Settings(source="model", scenario="A", log_uri=str(env / "d.jsonl")))
    moment = datetime(2012, 5, 10, 1, 0, tzinfo=timezone.utc)
    assert service.source.input_checks("PT-A", moment) == []


def test_night_is_not_a_live_reason_to_abstain():
    from src.agent.model_wiring import live_input_flags

    night = {"net_now": 0.1, "share_last": 1.0, "net_lag_1": 0.1, "sun_elev_T": -20.0}
    assert live_input_flags(night) == []


def _weather(celsius: float):
    import pandas as pd

    time = pd.date_range("2012-04-01", "2012-07-01", freq="1h", tz="UTC")
    return pd.DataFrame(
        {"time": time, "ghi_wm2": 0.0, "t2m_c": celsius, "available_at": time + pd.Timedelta("1h")}
    )


def test_ambient_uses_the_newest_hour_known_at_each_time():
    import pandas as pd

    from src.agent.model_wiring import AMBIENT_C, ambient_at

    time = pd.to_datetime(["2012-05-01 00:00", "2012-05-01 01:00"], utc=True)
    weather = pd.DataFrame(
        {
            "time": time,
            "ghi_wm2": 0.0,
            "t2m_c": [10.0, 30.0],
            "available_at": time + pd.Timedelta("1h"),
        }
    )
    asked = pd.to_datetime(
        ["2012-05-01 00:59", "2012-05-01 01:00", "2012-05-01 02:30", "2012-05-01 03:00"], utc=True
    )
    # an hour is known only when it is over: 10 from 01:00, 30 from 02:00
    assert ambient_at(weather, asked) == [AMBIENT_C, 10.0, 30.0, 30.0]
    assert ambient_at(None, asked) == [AMBIENT_C] * 4
    nan = weather.assign(t2m_c=float("nan"))
    assert ambient_at(nan, asked) == [AMBIENT_C] * 4  # a missing value is not 0


def test_hotspot_takes_one_ambient_per_step():
    from src.agent.model_wiring import hotspot_c

    ratios = [0.8] * 6
    assert hotspot_c(ratios, [35.0] * 6) > hotspot_c(ratios) > hotspot_c(ratios, [5.0] * 6)
    assert hotspot_c(ratios, 20.0) == hotspot_c(ratios)
    with pytest.raises(ValueError, match="ambient"):
        hotspot_c(ratios, [20.0])


def test_hotspot_follows_measured_temperature_and_falls_back_without_it(env, monkeypatch):
    moment = datetime(2012, 5, 10, 1, 0, tzinfo=timezone.utc)

    def hotspot(log):
        service = build_service(Settings(source="model", scenario="A", log_uri=str(env / log)))
        return service.source.grid_state("PT-A", moment).trafo_hotspot_c

    plain = hotspot("d.jsonl")  # no weather file in this data folder: 20 C assumed
    monkeypatch.setattr("src.ml.weather.load", lambda ids=None: _weather(38.0))
    hot = hotspot("e.jsonl")
    monkeypatch.setattr("src.ml.weather.load", lambda ids=None: _weather(20.0))
    assert hotspot("f.jsonl") == pytest.approx(plain)
    assert hot > plain
