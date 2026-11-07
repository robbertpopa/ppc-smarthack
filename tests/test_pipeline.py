from src.common import pipeline


def test_steps_train_forecast_then_evaluate_once():
    commands = pipeline.steps(["A", "B"], "cloud")
    modules = [c[2] for c in commands]
    assert modules == [
        "src.ml.train", "src.ml.forecast_pv_load",
        "src.ml.train", "src.ml.forecast_pv_load",
        "src.eval.run",
    ]  # fmt: skip
    assert commands[-1][-2:] == ["--run-id", "cloud"]


def test_no_labels_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert pipeline.main(["--dry-run"]) == 2
    assert "no labels" in capsys.readouterr().err
