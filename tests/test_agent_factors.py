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


def test_the_offset_is_its_own_factor_with_grounded_numbers():
    lowered = {**FACTORS, "offset": {"c": 0.043, "points": 4, "lowers": True}}
    out = add_factors(base(), lowered, LABELS)
    assert "online offset lowers the limit by 4 points because recent limits were too high" in (
        out.text
    )
    assert any(f.name == "offset_points" and f.value == 4 for f in out.figures) and grounded(out)
    raised = {**FACTORS, "offset": {"c": -0.02, "points": 2, "lowers": False}}
    text = add_factors(base(), raised, LABELS).text
    assert "raises the limit by 2 points because recent limits were all safe" in text
    assert "online offset" not in add_factors(base(), {**FACTORS, "offset": None}, LABELS).text
