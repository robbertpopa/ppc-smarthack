import pandas as pd

from .twin import STATION_HOUSES


def read_period(source, start, days):
    frame = pd.read_csv(source, skiprows=1, low_memory=False)
    cl_customers = set(frame.loc[frame["Consumption Category"] == "CL", "Customer"])
    frame["date"] = pd.to_datetime(frame["date"], dayfirst=True)
    start = pd.Timestamp(start)
    frame = frame[(frame.date >= start) & (frame.date < start + pd.Timedelta(days=days))]
    if frame.empty:
        raise ValueError("No data in selected period")
    return frame, cl_customers


def half_hour_columns(frame):
    return list(frame.columns[5:53])


def select_households(frame, cl_customers, days, customers=None):
    """The station's customers, their rows and their capacity.

    Without ``customers``: the first ``STATION_HOUSES`` customers with complete rows.
    With ``customers`` (an earlier run of the same station): exactly those, in that
    order, and every one must have complete rows in this period.
    """
    count = (
        frame.groupby(["Customer", "Consumption Category"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=["GC", "GG", "CL"], fill_value=0)
    )
    complete = (count.GC == days) & (count.GG == days)
    complete &= (count.CL == days) | ~count.index.isin(cl_customers)
    if customers is None:
        eligible = list(count.index[complete][:STATION_HOUSES])
        if len(eligible) < STATION_HOUSES:
            raise ValueError(f"Fewer than {STATION_HOUSES} customers have complete GC and GG rows")
    else:
        eligible = list(customers)
        missing = [c for c in eligible if not complete.get(c, False)]
        if missing:
            raise ValueError(
                f"{len(missing)} station customers lack complete rows in this period "
                f"(first: {missing[:5]})"
            )
    frame = frame[frame.Customer.isin(eligible)]
    capacity = (
        frame[frame["Consumption Category"] == "GG"]
        .groupby("Customer")["Generator Capacity"]
        .first()
    )
    return eligible, frame, capacity


def day_profiles(day, eligible, hours):
    day = day.set_index(["Customer", "Consumption Category"])
    if not day.index.is_unique:
        raise ValueError("duplicate readings")
    load = day.xs("GC", level=1).loc[eligible, hours].astype(float)
    pv = day.xs("GG", level=1).loc[eligible, hours].astype(float)
    if "CL" in day.index.get_level_values(1):
        rows = day.xs("CL", level=1)
        controlled = rows.reindex(eligible)[hours].astype(float)
        controlled.loc[[c for c in eligible if c not in rows.index]] = 0.0
        load = load + controlled
    return 2 * load.to_numpy().T, 2 * pv.to_numpy().T


def house_readings(eligible, load_kw, pv_kw):
    return [
        {"house_id": str(c), "load_kw": float(load), "pv_kw": float(pv), "export_limit_kw": 0}
        for c, load, pv in zip(eligible, load_kw, pv_kw)
    ]
