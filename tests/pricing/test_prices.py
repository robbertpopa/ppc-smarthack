import numpy as np
import pandas as pd
import pytest

from src.pricing import prices


def payload(day, rows, unit="EUR/MWh"):
    return {
        "unit": unit,
        "hours": [
            {"ts": f"{day}T{h:02d}:00:00.000Z", "price": p, "currency": "EUR"} for h, p in rows
        ],
    }


def fake_year(year=2025):
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz="UTC", inclusive="left")
    return pd.Series(np.arange(len(idx), dtype=float) % 100, index=idx)


def test_parse_drops_duplicates_and_checks_unit():
    series = prices.parse_response(payload("2024-01-01", [(0, 1.0), (1, 2.0), (1, 3.0), (5, 4.0)]))
    assert list(series) == [1.0, 3.0, 4.0] and str(series.index.tz) == "UTC"
    with pytest.raises(ValueError):
        prices.parse_response(payload("2024-01-01", [], unit="RON/MWh"))
    with pytest.raises(ValueError):
        prices.parse_response({})


def test_http_get_sends_a_token_and_a_user_agent(monkeypatch):
    seen = {}

    class Reply:
        def read(self):
            return b'{"hours": []}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        seen["request"] = request
        return Reply()

    monkeypatch.setattr(prices.urllib.request, "urlopen", fake_urlopen)
    assert prices.http_get("https://example.test/p", "tok") == {"hours": []}
    assert seen["request"].get_header("Authorization") == "Bearer tok"
    assert seen["request"].get_header("User-agent") == prices.USER_AGENT


def test_fetch_year_and_round_trip(tmp_path):
    full = fake_year()

    def get(url, token):
        assert token == "t" and "zone=RO" in url
        lo = pd.Timestamp(url.split("from=")[1].split("&")[0], tz="UTC")
        hi = pd.Timestamp(url.split("to=")[1], tz="UTC")
        part = full[(full.index >= lo) & (full.index <= hi)]
        rows = [{"ts": t.isoformat(), "price": float(p)} for t, p in part.items()]
        return {"unit": "EUR/MWh", "hours": rows}

    got = prices.fetch_year(2025, "t", get)
    assert len(got) == len(full) and got.index.is_unique
    path = tmp_path / "pzu" / "ro.parquet"
    prices.save(got, path)
    loaded = prices.load(path)
    assert len(loaded) == len(full) and loaded.isna().sum() == 0


def test_load_fills_short_gaps_only(tmp_path):
    full = fake_year()
    holes = full.drop(full.index[10:12]).drop(full.index[100:106])
    path = tmp_path / "ro.parquet"
    prices.save(holes, path)
    loaded = prices.load(path)
    assert loaded.iloc[10:12].notna().all()
    assert loaded.iloc[100:103].notna().all() and loaded.iloc[103:106].isna().all()


def test_missing_file_says_how_to_fetch(tmp_path):
    with pytest.raises(FileNotFoundError, match="prices fetch"):
        prices.load(tmp_path / "none.parquet")


def test_cli_needs_the_token(monkeypatch):
    monkeypatch.delenv("EUENERGY_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="EUENERGY_TOKEN"):
        prices.main(["fetch", "--year", "2025"])


def test_profile_covers_every_month_and_hour():
    table = prices.profile(fake_year())
    assert table.shape == (288,) and list(table.index.names) == ["month", "hour"]
    with pytest.raises(ValueError):
        prices.profile(fake_year()[:2000])


def test_align_pairs_opposite_seasons_and_local_hours():
    table = prices.profile(fake_year())
    winter = pd.Timestamp("2012-07-01 12:00", tz="Australia/Sydney")
    summer = pd.Timestamp("2013-01-15 12:30", tz="Australia/Sydney")
    when = pd.DatetimeIndex([winter, summer]).tz_convert("UTC")
    out = prices.align(when, table)
    assert out.iloc[0] == table.loc[(1, 12)]  # Sydney July -> Bucharest January
    assert out.iloc[1] == table.loc[(7, 12)]  # Sydney January -> Bucharest July
    assert list(out.index) == list(when)


def test_monthly_average_and_its_alignment():
    table = prices.profile(fake_year())
    monthly = prices.monthly_average(table)
    assert monthly.shape == (12,) and monthly.loc[3] == pytest.approx(table.loc[3].mean())
    when = pd.DatetimeIndex([pd.Timestamp("2012-07-01 12:00", tz="Australia/Sydney")])
    aligned = prices.align_monthly(when.tz_convert("UTC"), monthly)
    assert aligned.iloc[0] == monthly.loc[1]
