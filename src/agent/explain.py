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


def _num(value: float) -> str:
    return str(round(float(value), 2))


def add_factors(
    explanation: Explanation, factors: dict | None, labels: dict[str, str]
) -> Explanation:
    """Append the model's top factors and similar cases, using only numbers from the figures.

    ``factors`` is the output of ``ml.explain.explain``. Nothing is invented: every number
    in the added text is also added as a figure.
    """
    if not factors or not factors.get("figures"):
        return explanation
    figures = list(explanation.figures)
    parts = []
    for item in factors["figures"]:
        name = item["name"]
        value = round(float(item["value"]), 2)
        effect = round(abs(float(item["effect"])) * 100)
        direction = "raises" if item["effect"] > 0 else "lowers"
        figures.append(Figure(name=f"factor_{name}", value=value))
        figures.append(Figure(name=f"factor_{name}_effect_pct", value=effect))
        parts.append(
            f"{labels.get(name, name)} is {_num(value)} and {direction} "
            f"the cautious limit by {effect} points"
        )
    text = explanation.text + " Main factors: " + "; ".join(parts) + "."
    offset = factors.get("offset")
    if offset:
        figures.append(Figure(name="offset_points", value=offset["points"]))
        text += (
            f" The online offset {'lowers' if offset['lowers'] else 'raises'} the limit by "
            f"{offset['points']} points because recent limits were "
            f"{'too high' if offset['lowers'] else 'all safe'}."
        )
    similar = factors.get("similar") or []
    if similar:
        realised = sorted(round(c["safe_share"] * 100) for c in similar)
        median = realised[len(realised) // 2]
        figures += [
            Figure(name="similar_cases", value=len(similar)),
            Figure(name="similar_median_safe_share_pct", value=median),
        ]
        text += (
            f" In {len(similar)} similar past cases the realised safe share had a median "
            f"of {median}%."
        )
    if factors.get("missing"):
        figures.append(Figure(name="missing_inputs", value=len(factors["missing"])))
        text += f" {len(factors['missing'])} inputs were missing."
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
