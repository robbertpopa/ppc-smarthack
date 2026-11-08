"""S2: src.ml and src.eval import each other, and serving pulls in the training code."""

from audit.proposals import import_graph as ig
from audit.tests.conftest import REPO


def graph():
    return ig.module_graph(REPO / "src")


def test_today_ml_and_eval_form_one_package_cycle():
    found = ig.cycles(ig.package_graph(graph()))
    assert any({"src.ml", "src.eval"} <= c for c in found), found


def test_today_the_serving_path_reaches_training_and_evaluation():
    reach = ig.closure(graph(), "src.ml.predict")
    assert "src.ml.train" in reach
    assert "src.eval.metrics" in reach
    print("\nsrc.ml.predict reaches:", sorted(reach))


def test_the_proposed_moves_remove_both_problems():
    new = ig.rewire(graph(), ig.PROPOSED_MOVES, ig.PROPOSED_REDIRECT)
    pkg_cycles = ig.cycles(ig.package_graph(new))
    assert not any({"src.ml", "src.eval"} <= c for c in pkg_cycles), pkg_cycles
    reach = ig.closure(new, "src.ml.predict")
    assert "src.ml.train" not in reach
    assert not any(m.startswith("src.eval") for m in reach)


def test_the_graph_sees_imports_inside_functions():
    # src/ml/predict.py imports src.ml.train inside predict(): it must still be an edge
    assert "src.ml.train" in graph()["src.ml.predict"]
