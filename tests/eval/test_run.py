import hashlib
import json

import pandas as pd
import pytest

from src.eval import run as eval_run
from src.ml import labels
from src.ml.config import artifact_uri

FAST = [{"max_iter": 30, "learning_rate": 0.1, "max_leaf_nodes": 15, "min_samples_leaf": 40}]
TEST_START = pd.Timestamp("2012-06-30 14:00", tz="UTC")  # 2012-07-01 00:00 in Sydney


def write_profiles(root):
    """Profiles that add up to the mock station, so export numbers exist."""
    data = root / "data"
    lab = labels.load("A")
    houses = labels.load_station_houses("A")
    frames = []
    for source_id, kwp in zip(houses["source_house_id"], houses["kwp"], strict=True):
        frames.append(
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
        )
    pd.concat(frames, ignore_index=True).to_parquet(data / "profiles.parquet")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("eval")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(root / "data"))
    mp.setenv("ARTIFACT_URI", str(root / "artifacts"))
    labels.main(["mock", "--scenario", "A"])
    write_profiles(root)
    path = root / "data" / "labels" / "A" / "labels.parquet"
    original = path.read_bytes()
    yield root
    path.write_bytes(original)
    mp.undo()


@pytest.fixture(scope="module")
def first(env):
    return eval_run.run(["A"], "one", allow_mock=True, grid=FAST)


def digest(run_id, name):
    return hashlib.sha256((eval_run.eval_dir(run_id) / name).read_bytes()).hexdigest()


def test_mock_labels_are_refused_without_the_flag(env):
    with pytest.raises(eval_run.MockLabelsError, match="--allow-mock"):
        eval_run.run(["A"], "refused", grid=FAST)
    with pytest.raises(SystemExit, match="--allow-mock"):
        eval_run.main(["--scenario", "A", "--run-id", "refused"])


def test_outputs_are_stamped_mock(first):
    assert first["mock"] is True and first["title"] == "MOCK – NOT A RESULT"
    text = (eval_run.eval_dir("one") / "table.md").read_text()
    assert text.startswith("# MOCK – NOT A RESULT")
    assert "Fixed limit" in text and "Model + fallback" in text and "Safe maximum (oracle)" in text


def test_two_runs_are_byte_identical(env, first):
    names = ("table.csv", "table.md", "summary.json", "calibration.csv", "risk_coverage_PT-A.csv")
    before = {name: digest("one", name) for name in names}
    eval_run.run(["A"], "one", allow_mock=True, grid=FAST)  # same run id, retrained from scratch
    assert before == {name: digest("one", name) for name in names}


def test_fixed_is_100_and_oracle_never_violates(first):
    rows = first["scenarios"]["PT-A"]["rows"]
    assert rows["fixed"]["export_index"] == 100.0
    assert rows["oracle"]["violation_rate"] == 0.0
    assert rows["fixed"]["abstain_rate"] is None
    assert rows["model_fallback"]["abstain_rate"] is not None
    assert set(eval_run.KEYS) <= set(rows)


def test_only_the_test_period_is_scored(env, monkeypatch):
    seen = []
    real = eval_run.evaluate

    def spy(share, lab, *args, **kwargs):
        seen.append((lab["interval_start"].min(), lab["interval_start"].max()))
        return real(share, lab, *args, **kwargs)

    monkeypatch.setattr(eval_run, "evaluate", spy)
    eval_run.run(["A"], "spy", allow_mock=True, robustness=False, grid=FAST)
    assert len(seen) == 6
    assert all(
        low >= TEST_START and high <= pd.Timestamp("2013-06-30 14:00", tz="UTC")
        for low, high in seen
    )


def test_summary_shape_for_the_comparison_panel(first):
    entry = first["scenarios"]["PT-A"]
    assert {"rows", "threshold", "calibration_drift", "labels_sha256", "source_ref"} <= set(entry)
    assert set(entry["rows"]["model_fallback"]) >= {
        "export_index",
        "violation_rate",
        "abstain_rate",
    }
    on_disk = json.loads((eval_run.eval_dir("one") / "summary.json").read_text())
    assert on_disk == json.loads(json.dumps(first))
    assert "/tmp" not in (eval_run.eval_dir("one") / "summary.json").read_text()


def test_calibration_has_validation_and_test_coverage(first):
    cal = pd.read_csv(eval_run.eval_dir("one") / "calibration.csv")
    assert list(cal.columns) == ["quantile", "coverage_validation", "coverage_test", "station"]
    assert len(cal) == 5


def test_saved_models_must_match_the_labels(env, first):
    from src.ml import train

    train.train("A", grid=FAST)  # the deployed model
    eval_run.run(["A"], "artifacts", use_artifacts=True, allow_mock=True)  # same labels: fine
    path = env / "data" / "labels" / "A" / "labels.parquet"
    original = path.read_bytes()
    labels.main(["mock", "--scenario", "A", "--seed", "1"])  # different labels, same station
    try:
        with pytest.raises(ValueError, match="other labels"):
            eval_run.run(["A"], "bad", use_artifacts=True, allow_mock=True)
    finally:
        path.write_bytes(original)


def test_profiles_without_the_test_year_give_a_clear_error(env):
    short = pd.read_parquet(env / "data" / "profiles.parquet")
    keep = short["interval_start"] < TEST_START
    short[keep].to_parquet(env / "data" / "profiles.parquet")
    try:
        with pytest.raises(ValueError, match="include-held-out"):
            eval_run.run(["A"], "nocover", allow_mock=True, grid=FAST)
    finally:
        write_profiles(env)


def test_outputs_live_under_artifact_uri(first):
    assert str(eval_run.eval_dir("one")).startswith(artifact_uri())


def test_robustness_rows_are_in_every_output(first):
    rows = first["scenarios"]["PT-A"]["rows"]
    for key in ("robust_control", "robust_missing_20", "robust_noise_30", "robust_censored"):
        assert {"violation_rate", "delta_violation_rate", "delta_abstain_rate"} <= set(rows[key])
    notes = first["scenarios"]["PT-A"]["robustness"]
    assert notes["net_only"] is True and "extra_flagged_by_input_checks" in notes["missing_20"]
    text = (eval_run.eval_dir("one") / "table.md").read_text()
    assert "20% of readings missing" in text and "censored production" in text
    assert "robust" not in (eval_run.eval_dir("one") / "table.csv").read_text().splitlines()[0]
    assert "30% noise on readings" in (eval_run.eval_dir("one") / "table.csv").read_text()


def test_the_clean_rows_do_not_change_with_robustness(env, first):
    eval_run.run(["A"], "plain", allow_mock=True, robustness=False, grid=FAST)
    clean = first["scenarios"]["PT-A"]["rows"]
    plain = json.loads((eval_run.eval_dir("plain") / "summary.json").read_text())["scenarios"][
        "PT-A"
    ]
    for key in eval_run.KEYS:
        assert clean[key] == plain["rows"][key]


def test_the_evaluation_does_not_overwrite_the_served_model(env):
    from src.ml import model_io, train

    train.train("A", grid=FAST)  # the model the API would serve
    served = model_io.model_dir(train.MODEL_VERSION, "PT-A") / "metadata.json"
    before = served.read_bytes()
    eval_run.run(["A"], "own-models", allow_mock=True, robustness=False, grid=FAST)
    assert served.read_bytes() == before
    assert (eval_run.eval_dir("own-models") / "models" / "PT-A" / "metadata.json").exists()


def test_profiles_are_required_unless_a_mock_run_allows_going_without(env, monkeypatch, tmp_path):
    lab = labels.load("A")
    houses = labels.load_station_houses("A")
    test = lab[lab["interval_start"] >= TEST_START]
    monkeypatch.setenv("DATA_DIR", str(tmp_path))  # an empty data folder: no profiles.parquet
    with pytest.raises(FileNotFoundError, match="profiles"):
        eval_run._surplus(test, houses, mock=False, allow_mock=False)
    with pytest.raises(FileNotFoundError, match="profiles"):
        eval_run._surplus(test, houses, mock=True, allow_mock=False)
    assert eval_run._surplus(test, houses, mock=True, allow_mock=True) == (None, None, None)


def test_profiles_must_cover_every_scored_interval_not_just_one(env):
    path = env / "data" / "profiles.parquet"
    full = pd.read_parquet(path)
    half = full[full["interval_start"] < pd.Timestamp("2012-12-31", tz="UTC")]
    half.to_parquet(path)
    try:
        with pytest.raises(ValueError, match="does not cover .* of .* scored test intervals"):
            eval_run.run(["A"], "partial", allow_mock=True, grid=FAST)
    finally:
        full.to_parquet(path)


def test_counts_are_whole_numbers_in_the_markdown_table(first):
    lines = (eval_run.eval_dir("one") / "table.md").read_text().splitlines()
    row = next(line for line in lines if "| Model + fallback |" in line)
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[-1].isdigit() and cells[-2].isdigit()  # intervals and flagged per day (max)


def test_the_control_rebuild_equals_the_clean_row(first):
    scenario = first["scenarios"]["PT-A"]
    control, clean = scenario["rows"]["robust_control"], scenario["rows"]["model_fallback"]
    for column in ("violation_rate", "abstain_rate", "export_index", "n_intervals"):
        assert control[column] == pytest.approx(clean[column], abs=1e-6), column
    gap = scenario["robustness"]["control_vs_clean"]
    assert all(abs(value) < 1e-6 for value in gap.values())  # nothing leaks into the deltas


def test_scoring_with_the_short_look_back_gives_the_same_rows(env, first):
    from src.ml import features, model_io, train

    labels_full = labels.load("A")
    models, meta = model_io.load_dir(eval_run.eval_dir("one") / "models" / "PT-A")
    ctx = {"models": models, "meta": meta}
    short = eval_run.score_model(ctx, labels_full)
    full = train.training_rows(labels_full)
    full_test = full[full["target_start"] >= pd.Timestamp("2012-06-30 14:00", tz="UTC")]
    assert len(short["rows"]) == len(
        full_test[full_test["target_start"] <= short["rows"]["target_start"].max()]
    )
    merged = short["rows"].merge(full_test, on="target_start", suffixes=("_short", "_full"))
    for name in features.FEATURES:
        a, b = merged[f"{name}_short"], merged[f"{name}_full"]
        assert ((a == b) | (a.isna() & b.isna())).all(), name


def test_the_control_is_not_scored_again_when_the_rebuilt_totals_are_the_label_totals(
    env, monkeypatch
):
    from src.eval import robustness

    ctx = eval_run._prepare("A", "ctx", True, False, FAST)
    clean = eval_run.policies(ctx)
    calls = []
    real = eval_run.score_model
    monkeypatch.setattr(eval_run, "score_model", lambda c, lab: calls.append(1) or real(c, lab))
    out = robustness.run_variants(ctx, clean)
    assert len(calls) == 3 and out["notes"]["control_rescored"] is False  # the variants only
    assert (
        out["rows"]["robust_control"]["violation_rate"]
        == clean["rows"]["model_fallback"]["violation_rate"]
    )

    # if the rebuild really differs, the control is scored and the deltas are taken against it
    ctx["profiles"] = ctx["profiles"].assign(gg_kw=ctx["profiles"]["gg_kw"] * 1.2)
    calls.clear()
    out = robustness.run_variants(ctx, clean)
    assert len(calls) == 4 and out["notes"]["control_rescored"] is True
