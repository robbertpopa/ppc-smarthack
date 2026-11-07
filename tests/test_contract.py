import pytest
from pydantic import ValidationError

from src.common.config import Settings
from src.common.contract import (
    ActionEvent,
    Forecast,
    GridState,
    Plan,
    SafeCapShare,
    StationConfig,
)
from src.common.mock_data import load_mock


@pytest.mark.parametrize(
    "name,model",
    [
        ("forecast", Forecast),
        ("grid_state", GridState),
        ("plan", Plan),
        ("action_event", ActionEvent),
        ("station", StationConfig),
    ],
)
def test_mocks_validate_and_round_trip(name, model):
    obj = load_mock(name, model)
    assert model.model_validate_json(obj.model_dump_json()) == obj


def test_quantiles_must_not_cross():
    with pytest.raises(ValidationError):
        SafeCapShare(q05=0.5, q10=0.4, q20=0.6, q50=0.7, q90=0.8)


def test_spread_must_match_quantiles():
    data = load_mock("forecast", Forecast).model_dump(mode="json")
    data["spread"] = 0.5
    with pytest.raises(ValidationError):
        Forecast.model_validate(data)


def test_naive_datetimes_are_rejected():
    data = load_mock("forecast", Forecast).model_dump(mode="json")
    data["interval_start"] = "2025-06-21T10:00:00"
    with pytest.raises(ValidationError):
        Forecast.model_validate(data)


def test_unknown_fields_are_rejected():
    data = load_mock("station", StationConfig).model_dump(mode="json")
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        StationConfig.model_validate(data)


def test_settings_defaults_and_env():
    assert Settings.from_env({}).source == "mock"
    env = {"APP_ENV": "cloud", "DEMO_TOKEN": "t", "LOG_URI": "/tmp/x.jsonl"}
    s = Settings.from_env(env)
    assert (s.app_env, s.demo_token, s.log_uri) == ("cloud", "t", "/tmp/x.jsonl")
    assert Settings.from_env({"DEMO_TOKEN": ""}).demo_token is None
