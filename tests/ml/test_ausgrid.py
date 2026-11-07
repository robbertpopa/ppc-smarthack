"""Parsing and cleaning of the Ausgrid files, on tiny in-test CSVs (both formats)."""

import numpy as np
import pandas as pd
import pytest

from src.ml import ausgrid, data

LABELS = [f"{(k * 30 // 60) % 24}:{k * 30 % 60:02d}" for k in range(1, 49)]  # 0:30 ... 23:30, 0:00


def write_csv(path, rows, new_format=False):
    """rows: dicts with cust, cat, date, optional kwp/post/quality and ``values`` {label: kWh}."""
    head = ["Customer", "Generator Capacity", "Postcode", "Consumption Category", "date", *LABELS]
    title = '"title row, not data"' + "," * (len(head) - 1)
    lines = [title, ",".join(head + (["Row Quality"] if new_format else []))]
    for r in rows:
        values = {label: "0" for label in LABELS}
        values.update({k: ("" if v is None else str(v)) for k, v in r.get("values", {}).items()})
        fields = [
            str(r["cust"]),
            str(r.get("kwp", 2.0)),
            r.get("post", "2076"),
            r["cat"],
            r["date"],
        ]
        fields += [values[label] for label in LABELS]
        if new_format:
            fields.append(r.get("quality", ""))
        lines.append(",".join(fields))
    path.write_text(("\r\n" if new_format else "\n").join(lines) + "\r\n")
    return path


def day(date, cat="GC", value=0.4, **kw):
    return {"cust": 1, "cat": cat, "date": date, "values": {label: value for label in LABELS}, **kw}


def one_house(tmp_path, rows, new_format=True):
    write_csv(tmp_path / "file.csv", rows, new_format)
    return ausgrid.build_profiles(tmp_path)


def test_old_format_labels_are_interval_ends(tmp_path):
    rows = [
        {
            "cust": 7,
            "cat": "GC",
            "date": "1-Jul-10",
            "values": {"0:30": 1.0, "12:00": 0.5, "0:00": 2.0},
        }
    ]
    long = ausgrid.parse_file(write_csv(tmp_path / "old.csv", rows))

    at = long.set_index("interval_start")["kwh"]
    assert len(long) == 48 and long["house_id"].iloc[0] == "AG-0007"
    assert at[pd.Timestamp("2010-07-01 00:00")] == 1.0  # column 0:30 is 00:00-00:30
    assert at[pd.Timestamp("2010-07-01 11:30")] == 0.5  # column 12:00 is 11:30-12:00
    assert (
        at[pd.Timestamp("2010-07-01 23:30")] == 2.0
    )  # column 0:00 is the LAST interval of the day


def test_new_format_has_quality_and_slash_dates(tmp_path):
    rows = [day("1/07/2011", quality="NA"), day("2/07/2011")]
    long = ausgrid.parse_file(write_csv(tmp_path / "new.csv", rows, new_format=True))

    assert long["interval_start"].min() == pd.Timestamp("2011-07-01 00:00")
    assert long["interval_start"].max() == pd.Timestamp("2011-07-02 23:30")
    assert (long["quality"] == "NA").sum() == 48  # "NA" stays a flag, not a missing value
    assert long["quality"].isna().sum() == 48


def test_old_format_has_no_quality(tmp_path):
    long = ausgrid.parse_file(write_csv(tmp_path / "old.csv", [day("1-Jul-10")]))
    assert long["quality"].isna().all()


def test_format_is_detected_from_the_header_not_the_name(tmp_path):
    write_csv(tmp_path / "a.csv", [day("1-Jul-10")])
    write_csv(tmp_path / "zzz data.csv", [day("1/07/2011")], new_format=True)
    (tmp_path / "monthly.csv").write_text(
        "Customer ID,Netwk Bill Rate Type,Consumption Month,Sum\n1,SC,01.2007,31\n"
    )

    profiles = ausgrid.build_profiles(tmp_path)

    assert [p.name for p in data.half_hourly_csvs(tmp_path)] == ["a.csv", "zzz data.csv"]
    assert len(profiles) == 96


def test_unrecognised_date_format_fails_loudly(tmp_path):
    with pytest.raises(ValueError, match="date format"):
        ausgrid.parse_file(write_csv(tmp_path / "x.csv", [day("2011-07-01")]))


def test_kwh_becomes_kw_and_time_is_utc(tmp_path):
    profiles = one_house(tmp_path, [day("1/07/2011", value=0.5)])

    first = profiles.iloc[0]
    assert first["gc_kw"] == 1.0  # 0.5 kWh in half an hour = 1 kW
    assert first["interval_start"] == pd.Timestamp("2011-06-30 14:00", tz="UTC")  # 00:00 AEST (+10)
    assert str(profiles["interval_start"].dt.tz) == "UTC"
    assert not profiles.duplicated(["house_id", "interval_start"]).any()


def test_missing_stays_missing(tmp_path):
    profiles = one_house(
        tmp_path, [day("1/07/2011", value=None)]
    )  # every cell empty; no CL, no GG rows

    assert profiles["gc_kw"].isna().all()
    assert profiles["cl_kw"].isna().all() and profiles["gg_kw"].isna().all()  # not 0


def test_spring_forward_day_has_46_intervals(tmp_path):
    rows = [day("2/10/2011", value=0.4)]
    rows[0]["values"].update({"2:30": 0, "3:00": 0})  # filler for the hour that does not exist
    profiles = one_house(tmp_path, rows)

    assert len(profiles) == 46
    steps = profiles["interval_start"].diff().dropna().unique()
    assert list(steps) == [pd.Timedelta(minutes=30)]  # no gap and no overlap in UTC
    assert profiles["interval_start"].iloc[0] == pd.Timestamp(
        "2011-10-01 14:00", tz="UTC"
    )  # 00:00 AEST
    assert profiles["gc_kw"].notna().all() and (profiles["gc_kw"] == 0.8).all()
    assert profiles.attrs["rules"]["dst_nonexistent_hour_dropped"] == 2


def test_fall_back_day_has_50_intervals_with_the_merged_hour_null(tmp_path):
    rows = [day("1/04/2012", value=0.4)]
    rows[0]["values"].update({"2:30": 0.8, "3:00": 0.8})  # the repeated hour arrives summed
    profiles = one_house(tmp_path, rows)

    assert len(profiles) == 50
    assert list(profiles["interval_start"].diff().dropna().unique()) == [pd.Timedelta(minutes=30)]
    assert profiles["interval_start"].iloc[0] == pd.Timestamp(
        "2012-03-31 13:00", tz="UTC"
    )  # 00:00 AEDT
    assert profiles["gc_kw"].isna().sum() == 4  # 02:00-03:00 happens twice, 2 intervals each
    assert (profiles["gc_kw"].dropna() == 0.8).all()
    assert profiles.attrs["rules"]["dst_repeated_hour_nulled"] == 2


def test_cleaning_rules_are_counted(tmp_path):
    rows = [
        day("1/07/2011", "GC", value=0.4),
        day("1/07/2011", "GC", value=0.4),  # exact duplicate of the row above
        day("2/07/2011", "GG", value=0.0, kwp=2.0),
    ]
    rows[0]["values"]["1:00"] = -0.1  # negative reading
    rows[2]["values"].update(
        {"12:00": 1.5, "12:30": 1.0}
    )  # 3 kW and 2 kW against 2 kWp (limit 2.4)
    profiles = one_house(tmp_path, rows)
    rules = profiles.attrs["rules"]

    assert rules["duplicate_readings_dropped"] == 48
    assert rules["negative_to_null"] == 1
    assert rules["gg_above_limit_to_null"] == 1
    assert (
        profiles["gc_kw"].isna().sum() == 1 + 48
    )  # the negative one, and the day with no GC row (2 Jul)
    gg = profiles.set_index("interval_start")["gg_kw"]
    assert np.isnan(
        gg[pd.Timestamp("2011-07-02 01:30", tz="UTC")]
    )  # column 12:00 = 11:30 AEST, over the limit
    assert (
        gg[pd.Timestamp("2011-07-02 02:00", tz="UTC")] == 2.0
    )  # column 12:30 = 12:00 AEST, under, kept


def test_non_actual_flag_covers_all_categories_of_that_day(tmp_path):
    rows = [
        day("1/07/2011", "GC", quality=""),
        day("1/07/2011", "GG", quality="NA"),
        day("2/07/2011", "GC"),
    ]
    profiles = one_house(tmp_path, rows)

    flagged = profiles[profiles["quality"] == "NA"]
    assert len(flagged) == 48
    assert flagged["interval_start"].max() < pd.Timestamp(
        "2011-07-01 14:00", tz="UTC"
    )  # only 1 July
    assert profiles["quality"].isna().sum() == 48


def test_generation_matches_raw_sum_to_rounding(tmp_path):
    rows = [day("1/07/2011", "GG", value=0.3), day("2/07/2011", "GG", value=0.1)]
    rows[1]["values"]["12:00"] = 9.0  # removed by the over-limit rule
    profiles = one_house(tmp_path, rows)

    (check,) = ausgrid.generation_check(tmp_path, profiles)
    removed = profiles.attrs["rules"]["gg_kwh_removed"]
    assert check["raw_gg_kwh"] == pytest.approx(48 * 0.3 + 47 * 0.1 + 9.0)
    assert check["raw_gg_kwh"] == pytest.approx(check["profile_gg_kwh"] + removed)


def test_profiles_command_writes_parquet(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    data.ausgrid_dir().mkdir(parents=True)
    write_csv(
        data.ausgrid_dir() / "f.csv", [day("1-Jul-10", "GG", value=0.2), day("1-Jul-10", "GC")]
    )

    out = data.profiles()

    table = pd.read_parquet(out)
    assert list(table.columns) == ausgrid.OUTPUT_COLUMNS
    assert str(table["interval_start"].dt.tz) == "UTC"
    assert table["gg_kw"].iloc[0] == pytest.approx(0.4)
