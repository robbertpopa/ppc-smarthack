from src.agent.explain import add_factors, build_explanation, grounded
from src.ml.explain import LABELS

FACTORS = {
    "figures": [
        {"name": "net_now", "value": 0.4231, "effect": -0.081},
        {"name": "sun_elev_T", "value": 55.6, "effect": 0.032},
    ],
    "similar": [{"safe_share": 0.31}, {"safe_share": 0.44}, {"safe_share": 0.52}],
    "missing": ["net_lag_3"],
}


def base():
    return build_explanation(
        source="model", share=0.3, static_share=0.36, spread=0.1, threshold=0.3, grid_state=None
    )


def test_factors_are_added_and_every_number_is_a_figure():
    out = add_factors(base(), FACTORS, LABELS)
    assert "Main factors" in out.text and "lowers the cautious limit by 8 points" in out.text
    assert "similar past cases" in out.text and grounded(out)


def test_no_factors_leaves_the_explanation_unchanged():
    assert add_factors(base(), None, LABELS) == base()
    assert add_factors(base(), {"figures": []}, LABELS) == base()
