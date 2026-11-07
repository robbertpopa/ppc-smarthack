import re

from src.common.contract import Explanation, Figure, GridState

NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _pct(x: float) -> int:
    return round(x * 100)


def build_explanation(
    *,
    source: str,
    share: float,
    static_share: float,
    spread: float | None,
    threshold: float,
    grid_state: GridState | None,
    reason: str | None = None,
) -> Explanation:
    figures = [Figure(name="static_limit_pct", value=_pct(static_share))]
    if source == "model":
        assert spread is not None
        figures += [
            Figure(name="export_limit_pct", value=_pct(share)),
            Figure(name="uncertainty_pct", value=_pct(spread)),
            Figure(name="threshold_pct", value=_pct(threshold)),
        ]
        text = (
            f"Each house may export up to {_pct(share)}% of its installed power. "
            f"The model's uncertainty is {_pct(spread)}%, below the {_pct(threshold)}% threshold, "
            f"so its cautious estimate replaces the fixed {_pct(static_share)}% limit."
        )
    elif spread is not None and spread > threshold:
        figures += [
            Figure(name="uncertainty_pct", value=_pct(spread)),
            Figure(name="threshold_pct", value=_pct(threshold)),
        ]
        text = (
            f"The model's uncertainty is {_pct(spread)}%, above the {_pct(threshold)}% threshold. "
            f"The fixed {_pct(static_share)}% limit applies and a person reviews the case."
        )
    else:
        text = (
            f"{reason or 'The inputs are not reliable'}. "
            f"The fixed {_pct(static_share)}% limit applies and a person reviews the case."
        )
    if grid_state is not None and grid_state.converged:
        if grid_state.v_max_pu is not None:
            figures.append(Figure(name="v_max_pu", value=round(grid_state.v_max_pu, 3)))
        if grid_state.trafo_loading_pct is not None:
            figures.append(
                Figure(name="trafo_loading_pct", value=round(grid_state.trafo_loading_pct))
            )
    return Explanation(text=text, figures=figures)


def grounded(explanation: Explanation) -> bool:
    allowed = {float(f.value) for f in explanation.figures}
    return all(float(n) in allowed for n in NUMBER.findall(explanation.text))


def ensure_grounded(explanation: Explanation) -> Explanation:
    if grounded(explanation):
        return explanation
    return Explanation(
        text="The limit follows the planner rules; the figures list the numbers used.",
        figures=explanation.figures,
    )
