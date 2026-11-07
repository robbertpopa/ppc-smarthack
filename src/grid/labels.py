"""Generate provisional safe-share labels from Ausgrid half-hourly CSV data."""

import argparse

import pandas as pd

from .twin import build_grid, safe_share


def generate(source, output, start, days, transformer_kva=400, pv_scale=1.0):
    if days < 1:
        raise ValueError("days must be positive")
    frame = pd.read_csv(source, skiprows=1, low_memory=False)
    cl_customers = set(frame.loc[frame["Consumption Category"] == "CL", "Customer"])
    frame["date"] = pd.to_datetime(frame["date"], dayfirst=True)
    start = pd.Timestamp(start)
    frame = frame[(frame.date >= start) & (frame.date < start + pd.Timedelta(days=days))]
    if frame.empty:
        raise ValueError("No data in selected period")
    hours = list(frame.columns[5:53])
    count = frame.groupby(["Customer", "Consumption Category"]).size().unstack(fill_value=0)
    eligible = count[(count.get("GC", 0) == days) & (count.get("GG", 0) == days)].index
    eligible = [
        c
        for c in eligible
        if c not in cl_customers or ("CL" in count.columns and count.loc[c, "CL"] == days)
    ][:210]
    if len(eligible) < 210:
        raise ValueError("Fewer than 210 customers have complete GC and GG rows")
    frame = frame[frame.Customer.isin(eligible)]
    capacity = (
        frame[frame["Consumption Category"] == "GG"]
        .groupby("Customer")["Generator Capacity"]
        .first()
    )
    if not 0 < pv_scale < float("inf"):
        raise ValueError("pv_scale must be positive and finite")
    houses = [{"house_id": str(c), "kwp": float(capacity.loc[c]) * pv_scale} for c in eligible]
    grid = build_grid(
        {
            "houses": houses,
            "transformer_kva": transformer_kva,
            "pt_id": f"PT-synthetic-{transformer_kva:g}kVA",
        }
    )
    labels = []
    for date, day in frame.groupby("date", sort=True):
        day = day.set_index(["Customer", "Consumption Category"])
        if not day.index.is_unique:
            raise ValueError(f"duplicate readings on {date}")
        for i in range(48):
            readings = []
            for customer in eligible:
                load = float(day.loc[(customer, "GC"), hours[i]])
                if (customer, "CL") in day.index:
                    load += float(day.loc[(customer, "CL"), hours[i]])
                pv = float(day.loc[(customer, "GG"), hours[i]])
                readings.append(
                    {
                        "house_id": str(customer),
                        "load_kw": 2 * load,
                        "pv_kw": 2 * pv * pv_scale,
                        "export_limit_kw": 0,
                    }
                )
            if not 6 <= i / 2 < 20 or sum(row["pv_kw"] for row in readings) <= 0:
                continue
            local = (date + pd.Timedelta(minutes=30 * i)).tz_localize("Australia/Sydney")
            utc = local.tz_convert("UTC").isoformat().replace("+00:00", "Z")
            share = safe_share(grid, {"interval_start": utc, "houses": readings})
            labels.append(
                {
                    "pt_id": grid.pt_id,
                    "interval_start": utc,
                    "safe_cap_share": share,
                    "provenance": "simulated",
                    "n_houses": len(houses),
                    "pv_scale": pv_scale,
                    "transformer_kva": transformer_kva,
                    "source": f"Ausgrid 2012-2013; synthetic radial {transformer_kva:g} kVA",
                }
            )
        print(f"{date.date()}: {len(labels)} labels", flush=True)
    pd.DataFrame(labels).to_parquet(output, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", default="2013-01-01")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--transformer-kva", type=float, default=400)
    parser.add_argument("--pv-scale", type=float, default=1)
    args = parser.parse_args()
    generate(args.source, args.output, args.start, args.days, args.transformer_kva, args.pv_scale)
