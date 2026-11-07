import hashlib

import numpy as np
import pandas as pd
import pytest

from src.eval import error_analysis, plots
from src.eval import run as eval_run
from src.ml import labels
from src.ml.split import TEST_START

FAST = [{"max_iter": 30, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}]
TABLES = ("hour", "sun_band", "day_type", "weekend", "season", "binding")


def write_profiles(root):
    data = root / "data"
    lab, houses = labels.load("A"), labels.load_station_houses("A")
    frames = [
        pd.DataFrame(
            {
                "house_id": source_id,
                "interval_start": lab["interval_start"],
                "gc_kw": lab["load_kw"] / len(houses),
                "cl_kw": float("nan"),
                "gg_kw": lab["pv_kw"] / len(houses),
                "kwp": kwp,
            }
        )
        for source_id, kwp in zip(houses["source_house_id"], houses["kwp"], strict=True)
    ]
    pd.concat(frames, ignore_index=True).to_parquet(data / "profiles.parquet")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("analysis")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    write_profiles(root)
    yield root
    mp.undo()


@pytest.fixture(scope="module")
def summary(env):
    return eval_run.run(["A"], "one", allow_mock=True, error_analysis=True, grid=FAST)


def out(run_id="one"):
    return eval_run.eval_dir(run_id)


def test_the_outputs_exist(summary):
    for name in ("error_analysis.md", "slides_numbers.md", "attempts_PT-A.csv"):
        assert (out() / name).exists(), name
    for table in TABLES:
        assert (out() / f"error_by_{table}_PT-A.csv").exists(), table
    for png in ("violation_by_hour", "risk_coverage", "band_clear", "band_cloudy"):
        data = (out() / f"{png}_PT-A.png").read_bytes()
        assert data.startswith(b"\x89PNG") and len(data) > 1000


def test_breakdown_counts_add_up_to_the_test_intervals(summary):
    total = summary["scenarios"]["PT-A"]["rows"]["fixed"]["n_intervals"]
    for table in TABLES:
        frame = pd.read_csv(out() / f"error_by_{table}_PT-A.csv")
        assert frame["n_intervals"].sum() == total, table


def test_tables_are_byte_identical_on_a_rerun(summary):
    names = [f"error_by_{t}_PT-A.csv" for t in TABLES]
    names += ["attempts_PT-A.csv", "error_analysis.md", "slides_numbers.md", "table.csv"]
    before = {n: hashlib.sha256((out() / n).read_bytes()).hexdigest() for n in names}
    eval_run.run(["A"], "one", allow_mock=True, error_analysis=True, grid=FAST)
    assert before == {n: hashlib.sha256((out() / n).read_bytes()).hexdigest() for n in names}


def test_every_slide_number_is_found_verbatim_in_its_table(summary):
    lines = (out() / "slides_numbers.md").read_text().splitlines()
    rows = [
        line.strip("|").split("|")
        for line in lines
        if line.startswith("| ") and "Number" not in line
    ]
    rows = [[cell.strip() for cell in row] for row in rows]
    assert len(rows) >= 6
    for what, station, value, file, row in rows:
        text = (out() / file).read_text()
        assert value in text, (what, value, file)
        lines = text.splitlines()
        if file == "table.csv":  # the station is a column of the shared table
            lines = [line for line in lines if line.startswith(station + ",")]
        assert any(row in line and value in line for line in lines), (what, row)


def test_the_report_states_the_rules_and_the_limits(summary):
    text = (out() / "error_analysis.md").read_text()
    assert text.startswith("# MOCK – NOT A RESULT")
    assert "median clear day" in text and "median cloudy day" in text
    assert "## Limits" in text and "simulated" in text and "SimBench" in text
    assert "What we tried (validation only)" in text


def test_attempts_use_the_reference_and_never_the_test_period(env, summary):
    tried = pd.read_csv(out() / "attempts_PT-A.csv")
    assert tried["attempt"].iloc[0].startswith("reference")
    assert not tried["improves_validation"].iloc[0]
    assert {"limit = q10", "without the lag features", "plus a cloud-ratio feature"} <= set(
        tried["attempt"]
    )


def test_the_clear_sky_scale_comes_from_before_the_test_period(env):
    lab = labels.load("A")
    scale = error_analysis.day_types(lab)[2]
    changed = lab.copy()
    test = changed["interval_start"] >= TEST_START.tz_localize("Australia/Sydney")
    changed.loc[test, "pv_kw"] = 0.0
    assert error_analysis.day_types(changed)[2] == scale
    kind = error_analysis.day_types(changed)[0]
    assert (kind[kind.index >= TEST_START.tz_localize(None)] == "cloudy").mean() > 0.9


def test_the_illustrated_days_are_the_median_ones():
    days = pd.date_range("2013-01-01", periods=5)
    ratio = pd.Series([0.9, 0.5, 0.7, 0.8, 0.6], index=days)
    index = pd.DatetimeIndex(
        [d.tz_localize("Australia/Sydney") + pd.Timedelta(hours=12) for d in days]
    )
    df = pd.DataFrame({"day_type": "clear"}, index=index.tz_convert("UTC"))
    assert error_analysis._pick_day(df, ratio, "clear") == days[2]  # ratio 0.7 is the median
    assert error_analysis._pick_day(df, ratio, "cloudy") is None


def test_breakdown_keeps_every_interval_even_with_unknown_bins():
    df = pd.DataFrame(
        {
            "binding": ["voltage", "unknown", "unknown", "none"],
            "violation": [True, False, False, False],
            "abstain": [False, True, False, False],
            "residual": [-0.1, 0.2, 0.0, 0.1],
            "export_applied": [1.0, 2.0, 2.0, 1.0],
            "export_fixed": [1.0, 1.0, 1.0, 1.0],
        }
    )
    table = error_analysis.breakdown(df, "binding")
    assert table["n_intervals"].sum() == 4
    unknown = table.set_index("bin").loc["unknown"]
    assert unknown["export_index"] == pytest.approx(200.0) and unknown["abstain_rate"] == 0.5


def test_plots_are_written_without_version_metadata(tmp_path):
    curve = pd.DataFrame({"coverage": [0.1, 0.5, 1.0], "risk": [0.0, 0.01, 0.05]})
    plots.risk_coverage(curve, tmp_path / "a.png")
    plots.risk_coverage(curve, tmp_path / "b.png")
    assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()
    assert b"matplotlib" not in (tmp_path / "a.png").read_bytes()
    assert np.isfinite(0)
