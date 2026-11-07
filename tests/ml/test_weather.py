import json

import pandas as pd
import pytest

from src.ml import geo, weather

GEO = """Customer,Generator Capacity,Postcode,lat,lon,localities
1,3.78,2076,-33.71,151.11,"Normanhurst, Wahroonga"
2,1.62,2259,-33.20,151.39,"Alison, Bushells Ridge"
3,1.0,2259,-33.20,151.39,"Alison, Bushells Ridge"
"""


def answer(year, fill=None):
    """What the API sends back for one year: every parameter, every hour."""
    hours = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", inclusive="left")
    keys = [h.strftime("%Y%m%d%H") for h in hours]
    values = {p: {k: float(i) for i, k in enumerate(keys)} for p in weather.PARAMETERS}
    if fill:
        values[fill][keys[0]] = weather.FILL_VALUE
    return json.dumps({"properties": {"parameter": values}}).encode()


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference" / geo.GEO_FILE).write_text(GEO)
    return tmp_path


def test_one_row_per_postcode(data_root):
    table = weather.postcodes()
    assert list(table["postcode"]) == ["2076", "2259"]
    assert list(table["houses"]) == [1, 2]


def test_url_asks_for_utc_and_one_year():
    url = weather.request_url(-33.7, 151.1, 2011)
    assert "start=20110101" in url and "end=20111231" in url
    assert "time-standard=utc" in url and "format=json" in url
    assert "ALLSKY_SFC_SW_DWN,ALLSKY_SFC_SW_DIFF" in url


def test_check_answer_rejects_a_short_year():
    weather.check_answer(answer(2012), 2012)  # leap year: 8784 hours
    with pytest.raises(ValueError, match="wrong length"):
        weather.check_answer(answer(2011), 2012)


def test_fill_value_becomes_missing(tmp_path):
    path = tmp_path / "x.json"
    path.write_bytes(answer(2010, fill="ALLSKY_KT"))
    frame = weather.read_raw(path)
    assert frame.index[0] == pd.Timestamp("2010-01-01 00:00", tz="UTC")
    assert pd.isna(frame["ALLSKY_KT"].iloc[0]) and frame["ALLSKY_KT"].iloc[1] == 1.0
    assert not frame["T2M"].isna().any()


def test_fetch_is_resumable_and_build_joins(data_root, monkeypatch):
    calls = []

    def fake(lat, lon, year):
        calls.append((lat, year))
        return answer(year)

    monkeypatch.setattr(weather, "fetch_year", fake)
    with pytest.raises(FileNotFoundError, match="not downloaded"):
        weather.build(2010, 2011)
    assert weather.fetch(2010, 2011, workers=2) == 0
    assert len(calls) == 4  # 2 postcodes x 2 years
    assert weather.fetch(2010, 2011, workers=2) == 0
    assert len(calls) == 4  # nothing asked twice
    out = weather.build(2010, 2011)
    assert len(out) == 2 * (8760 * 2)
    assert weather.weather_path().exists()
    one = out[out["postcode"] == "2076"]
    assert one["time_utc"].is_unique and one["time_utc"].is_monotonic_increasing


def test_a_failed_request_is_reported_not_cached(data_root, monkeypatch, capsys):
    def fake(lat, lon, year):
        raise RuntimeError("down")

    monkeypatch.setattr(weather, "fetch_year", fake)
    assert weather.fetch(2010, 2010, workers=1) == 1
    assert not list(weather.raw_dir().glob("*.json"))
    assert "FAILED" in capsys.readouterr().err
