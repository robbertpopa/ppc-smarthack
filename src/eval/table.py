"""Formatting of the evaluation table: fixed decimals so diffs are meaningful."""

import pandas as pd

ROW_LABELS = {
    "fixed": "Fixed limit",
    "last_known": "Last known",
    "same_hour_yesterday": "Same hour yesterday",
    "model_q05": "Model (q05)",
    "model_fallback": "Model + fallback",
    "oracle": "Safe maximum (oracle)",
}
COLUMNS = [
    ("export_index", "Export index (fixed = 100)"),
    ("violation_rate", "Violation rate"),
    ("abstain_rate", "Abstention rate"),
    ("per_day_mean", "Flagged / day (mean)"),
    ("per_day_max", "Flagged / day (max)"),
    ("n_intervals", "Daylight intervals"),
]
ACCOUNTING_NOTE = (
    "Export is counted at the applied limit even in an interval where the limit was unsafe; "
    "the violation rate is reported next to it, so a policy cannot look good by exporting "
    "unsafely."
)
DECIMALS = 4


def to_frame(rows: dict[str, dict[str, dict]]) -> pd.DataFrame:
    """``{pt_id: {row_key: metrics}}`` as a flat frame, one line per station and policy."""
    lines = []
    for pt_id, per_row in rows.items():
        for key, metrics in per_row.items():
            label = metrics.get("label") or ROW_LABELS.get(key, key)
            lines.append(
                {"station": pt_id, "policy": label, **{c: metrics.get(c) for c, _ in COLUMNS}}
            )
    return pd.DataFrame(lines)


def to_csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, float_format=f"%.{DECIMALS}f", lineterminator="\n")


def _cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "–"
    if isinstance(value, (int, float)) and float(value).is_integer() and abs(value) >= 1:
        return f"{value:.0f}" if abs(value) >= 1000 else f"{value:.{DECIMALS}f}"
    return f"{value:.{DECIMALS}f}" if isinstance(value, float) else str(value)


def to_markdown(frame: pd.DataFrame, title: str, footer: list[str]) -> str:
    headers = ["Station", "Policy", *[label for _, label in COLUMNS]]
    out = [f"# {title}", ""]
    out.append("| " + " | ".join(headers) + " |")
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for _, row in frame.iterrows():
        cells = [row["station"], row["policy"], *[_cell(row[c]) for c, _ in COLUMNS]]
        out.append("| " + " | ".join(cells) + " |")
    out += ["", *[f"- {line}" for line in footer], ""]
    return "\n".join(out)
