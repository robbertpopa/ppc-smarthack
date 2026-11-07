"""Audit a sample of saved labels with direct power flows above and at each cap."""

import argparse

import pandas as pd

from .twin import build_grid, power_flow

parser = argparse.ArgumentParser()
parser.add_argument("--source", required=True)
parser.add_argument("--labels", required=True)
args = parser.parse_args()
labels = pd.read_parquet(args.labels)
if labels.empty or labels[["pt_id", "interval_start"]].duplicated().any():
    raise ValueError("Labels are empty or contain duplicate intervals")
scale = float(labels.pv_scale.iloc[0])
trafo = float(labels.transformer_kva.iloc[0])
if labels.pv_scale.nunique() != 1 or labels.transformer_kva.nunique() != 1:
    raise ValueError("Expected one consistent scenario")
frame = pd.read_csv(args.source, skiprows=1, low_memory=False)
cl_customers = set(frame.loc[frame["Consumption Category"] == "CL", "Customer"])
frame["date"] = pd.to_datetime(frame["date"], dayfirst=True)
local = pd.to_datetime(labels.interval_start, utc=True).dt.tz_convert("Australia/Sydney")
start, end = (
    local.dt.tz_localize(None).dt.normalize().min(),
    local.dt.tz_localize(None).dt.normalize().max(),
)
days = (end - start).days + 1
frame = frame[(frame.date >= start) & (frame.date <= end)]
count = frame.groupby(["Customer", "Consumption Category"]).size().unstack(fill_value=0)
eligible = count[(count.get("GC", 0) == days) & (count.get("GG", 0) == days)].index
eligible = [
    c
    for c in eligible
    if c not in cl_customers or ("CL" in count.columns and count.loc[c, "CL"] == days)
][:210]
frame = frame[frame.Customer.isin(eligible)]
hours = list(frame.columns[5:53])
capacity = (
    frame[frame["Consumption Category"] == "GG"].groupby("Customer")["Generator Capacity"].first()
)
grid = build_grid(
    {
        "houses": [{"house_id": str(c), "kwp": float(capacity.loc[c]) * scale} for c in eligible],
        "transformer_kva": trafo,
    }
)
samples = labels[labels.safe_cap_share.notna() & (labels.safe_cap_share < 0.998)].sample(
    n=min(12, len(labels[labels.safe_cap_share.notna() & (labels.safe_cap_share < 0.998)])),
    random_state=42,
)
if samples.empty:
    raise ValueError("No finite boundary labels available to audit")
for row in samples.itertuples(index=False):
    t = pd.Timestamp(row.interval_start).tz_convert("Australia/Sydney")
    day = frame[frame.date == t.tz_localize(None).normalize()].set_index(
        ["Customer", "Consumption Category"]
    )
    hour = hours[t.hour * 2 + t.minute // 30]
    houses = []
    for c in eligible:
        load = float(day.loc[(c, "GC"), hour]) + (
            float(day.loc[(c, "CL"), hour]) if (c, "CL") in day.index else 0
        )
        pv = float(day.loc[(c, "GG"), hour])
        houses.append({"house_id": str(c), "load_kw": 2 * load, "pv_kw": 2 * pv * scale})
    for share, expected in (
        (row.safe_cap_share, True),
        (min(1, row.safe_cap_share + 0.002), False),
    ):
        reading = {
            "interval_start": row.interval_start,
            "houses": [
                {**h, "export_limit_kw": share * grid.houses[h["house_id"]]["kwp"]} for h in houses
            ],
        }
        state = power_flow(grid, reading, include_internal=True)
        if not state["converged"]:
            raise AssertionError(f"{row.interval_start}: did not converge")
        passed = (
            state["v_min_pu"] >= grid.min_voltage_pu
            and state["v_max_pu"] <= grid.voltage_limit_pu
            and state["line_loading_max_pct"] <= 100
            and state["trafo_loading_pct"] <= 100
        )
        if passed != expected:
            raise AssertionError(
                f"{row.interval_start}: unexpected safety at {share:.4f}, state={state}"
            )
print(
    f"{len(samples)} sampled boundaries passed at the label and failed 0.002 above; "
    f"{len(labels)} labels checked for duplicate times"
)
